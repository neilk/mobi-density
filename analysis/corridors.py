"""Corridor routing: the sampler behind flood-routing.md.

Per-station distance tables prune the street graph to the corridor an
odometer reading allows; routes are drawn as shortest paths under per-street
cost shakes; round trips chain three legs through two waypoints whose
purpose (leisure or errand) is read from the start station's surroundings.
flood_demo.py illustrates it; flows.py runs it over a month of trips.
"""
import heapq
import random
from collections import defaultdict
from math import exp


class NoRoute(Exception):
    """No sampled route fit the odometer window after repeated draws."""


SIGMA = 0.35          # strength of the per-street cost shake (log-normal scale)
SLACK = 0.05          # a route may exceed the odometer distance by this fraction
REUSE_PENALTY = 3.0   # round trips: outbound streets cost this much more on the way back
WAYPOINT_SD = 0.12    # round trips: waypoints sit this fraction of D (as sd) around D/3 and 2D/3
MIN_FILL = 0.85       # a route must use at least this fraction of the odometer distance
PLEASANT_K = {"leisure": 0.05, "errand": 0.3}   # a waypoint reached at this much lower average cost per metre is e times
                                                # likelier: decisive for a ride taken for its own sake, mild for an errand
TURN_CELL = 200       # round trips: one turnaround candidate per grid cell of this size, in metres
# Why a round trip was taken is told by where it starts, not by who rides it:
# nobody lives in Stanley Park, so every round trip from the booth is a park
# ride, member or not. A station's leisure share is how scenic its
# surroundings are, cut by how much housing is nearby; rider type nudges it.
# A leisure ride: every waterfront edge costs this fraction, on every leg and
# in the waypoint weights. An errand: waypoints are this many times more
# attractive among shops and amenities.
SCENIC_WAY, COMMERCIAL_BONUS = 0.35, 10.0
SCENIC_NEAR_M = 300          # how far round a station counts as its surroundings
HOME_CUT = 0.7               # a fully residential neighbourhood cuts the leisure share by this much
RIDER_NUDGE = {"casual": 0.15, "member": -0.15}



def build_graph(net):
    """Forward and reverse adjacency: node -> [(other, metres, way, perceived cost)].
    Cost is per edge, so slope and dismount penalties stay with the edge that earns them."""
    fwd, rev = defaultdict(list), defaultdict(list)
    for u, lst in enumerate(net.adj):
        for v, c, wi in lst:
            m = net.dist(u, v)
            if m > 0:
                fwd[u].append((v, m, wi, c))
                rev[v].append((u, m, wi, c))
    return fwd, rev


def metres_table(adj, src, limit):
    """Dijkstra by physical metres from src over adj, stopping beyond limit.
    Returns node -> metres. adj maps node -> [(other, metres, way, cost)]."""
    dist, heap = {src: 0.0}, [(0.0, src)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for v, m, _, _ in adj[u]:
            nd = d + m
            if nd <= limit and nd < dist.get(v, 1e18):
                dist[v] = nd
                heapq.heappush(heap, (nd, v))
    return dist


def cost_table(adj, src, limit_metres, edge_mult=lambda u, v: 1.0):
    """Dijkstra by perceived cost; returns node -> cost, bounded by the metres table."""
    cost, heap = {src: 0.0}, [(0.0, src)]
    while heap:
        c, u = heapq.heappop(heap)
        if c > cost[u]:
            continue
        for v, m, wi, ec in adj[u]:
            if v not in limit_metres:
                continue
            nc = c + ec * edge_mult(u, v)
            if nc < cost.get(v, 1e18):
                cost[v] = nc
                heapq.heappush(heap, (nc, v))
    return cost


def corridor(fwd, out_m, in_m, budget):
    """Edges (u, v, way, metres, cost) that lie on some route from A to B within budget."""
    edges = []
    for u, d_u in out_m.items():
        for v, m, wi, c in fwd[u]:
            d_v = in_m.get(v)
            if d_v is not None and d_u + m + d_v <= budget:
                edges.append((u, v, wi, m, c))
    return edges


HOP_TRIES = 12        # direct shakes before a one-way trip is routed through a waypoint instead
WINDOW_SD = 3.0       # waypoint candidates further than this many sd from their target spacing are skipped


class Bounded(dict):
    """A memo that keeps only its newest cap entries."""

    def __init__(self, cap):
        super().__init__()
        self.cap = cap

    def fetch(self, key, make):
        v = self.get(key)
        if v is None:
            v = self[key] = make()
            while len(self) > self.cap:
                del self[next(iter(self))]
        return v


def corridor_adj(edges, edge_mult=lambda u, v: 1.0):
    """Adjacency over the corridor, node -> [(other, metres, way, cost)], with a per-edge
    multiplier (a rider's taste for the waterfront) baked into the cost. Built once per group."""
    adj = defaultdict(list)
    for u, v, wi, m, c in edges:
        adj[u].append((v, m, wi, c * edge_mult(u, v)))
    return adj


def corridor_ways(adj):
    return {wi for lst in adj.values() for _, _, wi, _ in lst}


def shortest(adj, src, dst, factor, way_mult):
    """Cheapest route from src to dst over a corridor adjacency under shaken costs;
    (nodes, ways, metres) or None. way_mult: extra per-way multipliers (re-use penalties)."""
    best, prev, heap = {src: 0.0}, {}, [(0.0, src)]
    get = way_mult.get
    while heap:
        c, u = heapq.heappop(heap)
        if u == dst:
            break
        if c > best[u]:
            continue
        for v, m, wi, ec in adj.get(u, ()):
            nc = c + ec * factor[wi] * get(wi, 1.0)
            if nc < best.get(v, 1e18):
                best[v] = nc
                prev[v] = (u, wi, m)
                heapq.heappush(heap, (nc, v))
    if dst not in prev and dst != src:
        return None
    nodes, ways, metres, n = [dst], [], 0.0, dst
    while n != src:
        n, wi, m = prev[n]
        nodes.append(n); ways.append(wi); metres += m
    return nodes[::-1], ways[::-1], metres


def shake(ways, rng):
    return {wi: exp(rng.gauss(0, SIGMA)) for wi in ways}


def legs(adj, stops, f, budget, metres):
    """Shaken shortest paths chained through stops, later legs paying REUSE_PENALTY on earlier
    legs' ways; (nodes, ways, metres) if the whole fits the odometer window, else None."""
    nodes, ways, total, used = [stops[0]], [], 0.0, {}
    for src, dst in zip(stops, stops[1:]):
        leg = shortest(adj, src, dst, f, used)
        if not leg:
            return None
        nodes += leg[0][1:]; ways += leg[1]; total += leg[2]
        used.update({wi: REUSE_PENALTY for wi in leg[1]})
    if not MIN_FILL * metres <= total <= budget:
        return None
    return nodes, ways, total


def plain_route(edges, a, b):
    """The physically shortest route over the corridor, for a rider whose odometer says they took it."""
    adj = defaultdict(list)
    for u, v, wi, m, c in edges:
        adj[u].append((v, m, wi, m))
    return shortest(adj, a, b, defaultdict(lambda: 1.0), {})


def sample_hop(adj, a, b, budget, metres, rng, tries=HOP_TRIES):
    """One shaken route from a to b using between MIN_FILL * metres and budget metres; (factor, route)."""
    ways = corridor_ways(adj)
    for _ in range(tries):
        f = shake(ways, rng)
        r = shortest(adj, a, b, f, {})
        if r and MIN_FILL * metres <= r[2] <= budget:
            return f, r
    raise NoRoute(f"no route from {a} to {b} fits {metres:.0f} m")


def gauss(x, sd):
    return exp(-0.5 * (x / sd) ** 2)


def pleasant(kind):
    """Weight for a waypoint reached at average cost c over m metres: a cheaper ride there is likelier."""
    k = PLEASANT_K[kind]
    return lambda c, m: exp(-(c / m - 1) / k)


def waypoint_candidates(net, nodes, score):
    """Candidate waypoints and their weights: the best-scoring node per grid cell, so a dense
    street grid does not outvote a single seawall path. Raises NoRoute if nothing scores."""
    best = {}
    for t in nodes:
        w = score(t)
        if w <= 0:
            continue
        cell = (int(net.xy[t][0] // TURN_CELL), int(net.xy[t][1] // TURN_CELL))
        if w > best.get(cell, (0.0,))[0]:
            best[cell] = (w, t)
    if not best:
        raise NoRoute("no waypoint candidate")
    weights, cands = zip(*best.values())
    return cands, weights


def leisure_share(attractors, x, y, rider):
    """Probability that a round trip from this spot is a leisure ride rather than an errand."""
    scenic = attractors.scenic_near(x, y, SCENIC_NEAR_M)
    home = attractors.home(x, y)
    p = scenic * (1 - HOME_CUT * home)
    p += RIDER_NUDGE.get(rider, 0.0) * min(1.0, home / 0.25)   # rider type only matters where anyone lives
    return min(1.0, max(0.0, p))


class Rider:
    """What a trip is for: an edge cost multiplier and a waypoint attraction, memoised per node.
    kind is "leisure" or "errand"."""

    def __init__(self, net, attractors, kind):
        self.net, self.attractors, self.kind, self.cache, self.acache = net, attractors, kind, {}, {}

    def scenic(self, n):
        v = self.cache.get(n)
        if v is None:
            v = self.cache[n] = self.attractors.scenic(*self.net.xy[n], parks=False)
        return v

    def edge_mult(self, u, v):
        if self.kind == "leisure" and (self.scenic(u) or self.scenic(v)):
            return SCENIC_WAY
        return 1.0

    def attract(self, t):
        if self.kind != "errand":
            return 1.0
        v = self.acache.get(t)
        if v is None:
            v = self.acache[t] = 1.0 + COMMERCIAL_BONUS * self.attractors.commercial(*self.net.xy[t])
        return v


def sample_loop(net, adjs, a, budget, out_m, in_m, purposes, metres, rng, memo):
    """A round trip as three legs A -> t1 -> t2 -> A, each a shaken shortest path.
    Two waypoints, not one, because with a single turnaround the way back is
    always the shortcut and no loop can ever come out. Waypoints are drawn about
    a third of the odometer distance apart, preferring pleasant streets, and
    the whole route must use most of the odometer distance.
    purposes: [(probability, Rider, cost table out, cost table in), ...]; one is drawn per sample.
    adjs: kind -> corridor adjacency under that rider's edge costs. memo: a Bounded per group,
    holding the waypoint candidates, which do not change between draws. Returns
    (factor, route, [t1, t2], kind)."""
    p, rider, out_c, in_c = rng.choices(purposes, [q[0] for q in purposes])[0]
    adj, attract, kind = adjs[rider.kind], rider.attract, rider.kind
    nice = pleasant(kind)
    third, sd = metres / 3, WAYPOINT_SD * metres
    window = WINDOW_SD * sd
    ways = corridor_ways(adj)

    def first():
        pool = [t for t in out_m if t != a and t in out_c and abs(out_m[t] - third) <= window
                and in_m.get(t, 1e18) + out_m[t] <= budget]
        return waypoint_candidates(net, pool, lambda t: gauss(out_m[t] - third, sd) * nice(out_c[t], out_m[t]) * attract(t))

    def onward(t1):
        """Second-waypoint candidates after t1, or False when there are none."""
        m1 = metres_table(adj, t1, budget - out_m[t1])
        c1 = cost_table(adj, t1, m1)
        pool = [t for t in m1 if t not in (a, t1) and t in c1 and t in in_c
                and abs(m1[t] - third) <= window and abs(in_m.get(t, 1e18) - third) <= window
                and out_m[t1] + m1[t] + in_m[t] <= budget]
        try:
            return waypoint_candidates(net, pool, lambda t: gauss(m1[t] - third, sd) * gauss(in_m[t] - third, sd)
                                       * nice(c1[t], m1[t]) * nice(in_c[t], in_m[t]) * attract(t))
        except NoRoute:
            return False

    cands1 = memo.fetch(("first", kind), first)
    for _ in range(200):
        t1 = rng.choices(*cands1)[0]
        cands2 = memo.fetch((t1, kind), lambda: onward(t1))
        if not cands2:
            continue
        t2 = rng.choices(*cands2)[0]
        f = shake(ways, rng)
        route = legs(adj, (a, t1, t2, a), f, budget, metres)
        if route:
            return f, route, [t1, t2], kind
    raise NoRoute(f"no round trip from {a} fits {metres:.0f} m")


def sample_detour(net, adj, a, b, budget, out_m, in_m, rider, out_c, in_c, metres, rng, memo):
    """A one-way trip whose odometer runs well past the direct distance: A -> t -> B through
    one waypoint, drawn where the two legs add up to about the odometer reading and preferring
    pleasant streets, as for a round trip. in_m and in_c are the tables into B. (factor, route, t)."""
    nice, attract = pleasant(rider.kind), rider.attract
    # Shaking only lengthens a leg, so the two shortest legs should add up to a little under
    # the odometer: the middle of the fill window, with the window's half-width as spread.
    target, sd = (MIN_FILL + 1) / 2 * metres, (1 - MIN_FILL) / 2 * metres
    window = WINDOW_SD * sd
    ways = corridor_ways(adj)

    def candidates():
        pool = [t for t in out_m if t not in (a, b) and t in out_c and t in in_c
                and out_m[t] + in_m.get(t, 1e18) <= budget and abs(out_m[t] + in_m[t] - target) <= window]
        return waypoint_candidates(net, pool, lambda t: gauss(out_m[t] + in_m[t] - target, sd)
                                   * nice(out_c[t], out_m[t]) * nice(in_c[t], in_m[t]) * attract(t))

    cands = memo.fetch(("detour", rider.kind), candidates)
    for _ in range(200):
        t = rng.choices(*cands)[0]
        f = shake(ways, rng)
        route = legs(adj, (a, t, b), f, budget, metres)
        if route:
            return f, route, t
    raise NoRoute(f"no detour from {a} to {b} fits {metres:.0f} m")


class Corridors:
    """One call per trip group: sample(a, b, rider, metres, draws, seed) -> routes.

    Holds the graph and memoises per-station distance tables and round-trip
    purposes, so a run over many groups from the same origin pays for each
    table once. Tables are keyed on the budget rounded up to 500 m; only the
    newest TABLE_CACHE of each kind are kept, so a worker's memory stays flat
    when its jobs arrive sorted by destination."""

    TABLE_STEP = 500.0
    TABLE_CACHE = 8       # tables kept per cache
    MEMO = 64             # waypoint candidate lists kept per group

    def __init__(self, net, attractors):
        self.net, self.attractors = net, attractors
        self.fwd, self.rev = build_graph(net)
        self.riders = {kind: Rider(net, attractors, kind) for kind in ("leisure", "errand")}
        self._out, self._in, self._purposes, self._cost_out, self._cost_in = {}, {}, {}, {}, {}
        self._grid = defaultdict(list)
        for n in net.snappable:
            self._grid[(int(net.xy[n][0] // 100), int(net.xy[n][1] // 100))].append(n)

    def forget(self):
        """Drop memoised tables, e.g. between origins in a long run."""
        for cache in (self._out, self._in, self._purposes, self._cost_out, self._cost_in):
            cache.clear()

    def station_node(self, lat, lon):
        """Nearest snappable street node and its distance in metres."""
        return self.net.nearest(lat, lon, self._grid)

    def _limit(self, budget):
        return -(-budget // self.TABLE_STEP) * self.TABLE_STEP

    def _memo(self, cache, key, make):
        v = cache.get(key)
        if v is None:
            v = cache[key] = make()
            while len(cache) > self.TABLE_CACHE:
                del cache[next(iter(cache))]
        return v

    def out_table(self, node, budget):
        limit = self._limit(budget)
        return self._memo(self._out, (node, limit), lambda: metres_table(self.fwd, node, limit))

    def in_table(self, node, budget):
        limit = self._limit(budget)
        return self._memo(self._in, (node, limit), lambda: metres_table(self.rev, node, limit))

    def cost_tables(self, a, b, rider, budget):
        """Perceived-cost tables out of a and into b under one rider's costs: detour waypoint weights."""
        limit = self._limit(budget)
        out_c = self._memo(self._cost_out, (a, rider.kind, limit),
                           lambda: cost_table(self.fwd, a, self.out_table(a, budget), rider.edge_mult))
        in_c = self._memo(self._cost_in, (b, rider.kind, limit),
                          lambda: cost_table(self.rev, b, self.in_table(b, budget), rider.edge_mult))
        return out_c, in_c

    def purposes(self, a, rider, budget):
        """[(probability, Rider, cost table out, cost table in)] for round trips from a."""
        def make():
            p_leisure = leisure_share(self.attractors, *self.net.xy[a], rider)
            found = []
            for p, kind in ((p_leisure, "leisure"), (1 - p_leisure, "errand")):
                if p > 0:
                    r = self.riders[kind]
                    found.append((p, r) + self.cost_tables(a, a, r, budget))
            return found
        return self._memo(self._purposes, (a, rider, self._limit(budget)), make)

    def sample(self, a, b, rider, metres, draws, seed):
        """draws routes for a trip group, each (nodes, ways, route metres). Raises NoRoute.
        One-way trips are shaken directly. Once HOP_TRIES shakes fail to fit the odometer, the
        remaining draws are either the plain shortest route, when the direct distance itself
        fits the fill window (the cheap streets are longer than the odometer allows, so the
        rider took the direct road), or detours through a waypoint."""
        budget = metres * (1 + SLACK)
        out_m, in_m = self.out_table(a, budget), self.in_table(b, budget)
        edges = corridor(self.fwd, out_m, in_m, budget)
        rng, memo, routes = random.Random(seed), Bounded(self.MEMO), []
        if a == b:
            purposes = self.purposes(a, rider, budget)
            adjs = {r.kind: corridor_adj(edges, r.edge_mult) for _, r, _, _ in purposes}
            for _ in range(draws):
                _, route, _, _ = sample_loop(self.net, adjs, a, budget, out_m, in_m, purposes, metres, rng, memo)
                routes.append(route)
            return routes
        r = self.riders["leisure" if rider == "casual" else "errand"]
        adj = corridor_adj(edges, r.edge_mult)
        mode = "shake"
        for _ in range(draws):
            if mode == "shake":
                try:
                    routes.append(sample_hop(adj, a, b, budget, metres, rng)[1])
                    continue
                except NoRoute:
                    if MIN_FILL * metres <= out_m.get(b, 1e18) <= budget:
                        mode, plain = "plain", plain_route(edges, a, b)
                    else:
                        mode, tables = "detour", self.cost_tables(a, b, r, budget)
            if mode == "plain":
                routes.append(plain)
            else:
                routes.append(sample_detour(self.net, adj, a, b, budget, out_m, in_m, r, *tables, metres, rng, memo)[1])
        return routes
