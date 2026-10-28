"""Ground elevation from Terrarium PNG tiles in data/elevation (see download.sh there).

Pure Python PNG decoding, since the project carries no third-party packages:
the tiles are small 8-bit RGB images and the only work is zlib plus the five
PNG scanline filters. Elevation in metres = R * 256 + G + B / 256 - 32768.
"""
import struct
import zlib
from math import cos, log, pi, radians, tan

from common import DATA

TILES = DATA / "elevation"
ZOOM = 13
SIZE = 256


def _decode_png(raw):
    """Return (width, height, channels, bytes) for an 8-bit non-interlaced PNG."""
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos, idat, w = 8, [], None
    while pos < len(raw):
        length, kind = struct.unpack(">I4s", raw[pos:pos + 8])
        body = raw[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
            assert depth == 8 and interlace == 0, "unsupported PNG layout"
            ch = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    data = zlib.decompress(b"".join(idat))
    stride = w * ch
    out, prev = bytearray(), bytearray(stride)
    for y in range(h):
        f = data[y * (stride + 1)]
        line = bytearray(data[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - ch] if i >= ch else 0
            b = prev[i]
            c = prev[i - ch] if i >= ch else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out += line
        prev = line
    return w, h, ch, bytes(out)


class Terrain:
    """Elevation lookup; .available is False when no tiles have been downloaded."""

    def __init__(self):
        self.tiles = {}
        self.available = (TILES / str(ZOOM)).is_dir()

    def _tile(self, tx, ty):
        t = self.tiles.get((tx, ty))
        if t is None:
            path = TILES / str(ZOOM) / str(tx) / f"{ty}.png"
            if not path.is_file():
                t = self.tiles[(tx, ty)] = False
            else:
                w, h, ch, px = _decode_png(path.read_bytes())
                t = self.tiles[(tx, ty)] = (w, ch, px)
        return t

    def _sample(self, tx, ty, px_x, px_y):
        t = self._tile(tx, ty)
        if not t:
            return None
        w, ch, px = t
        i = (px_y * w + px_x) * ch
        return px[i] * 256 + px[i + 1] + px[i + 2] / 256 - 32768

    def ele(self, lat, lon):
        """Metres above sea level, bilinear between pixel centres; None outside the tiles."""
        if not self.available:
            return None
        n = 2 ** ZOOM
        r = radians(lat)
        fx = (lon + 180) / 360 * n * SIZE - 0.5
        fy = (1 - log(tan(r) + 1 / cos(r)) / pi) / 2 * n * SIZE - 0.5
        x0, y0 = int(fx // 1), int(fy // 1)
        wx, wy = fx - x0, fy - y0
        vals = []
        for dx, dy, wgt in ((0, 0, (1 - wx) * (1 - wy)), (1, 0, wx * (1 - wy)), (0, 1, (1 - wx) * wy), (1, 1, wx * wy)):
            gx, gy = x0 + dx, y0 + dy
            v = self._sample(gx // SIZE, gy // SIZE, gx % SIZE, gy % SIZE)
            if v is None:
                return None
            vals.append(v * wgt)
        return sum(vals)
