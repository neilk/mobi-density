// Overpass QL query for what surrounds a station and draws round-trip riders:
// the waterfront, parks and beaches (scenic), residential land use (homes
// nearby, so round trips may be errands) and shops and amenities (commercial). Same bounding box as query.ql. Run it with
// ./download_attractors.sh, which saves the result as vancouver_attractors.json.
[out:json][timeout:300];
(
  way["natural"="coastline"](49.215,-123.275,49.325,-123.015);
  way["natural"="water"](49.215,-123.275,49.325,-123.015);
  way["natural"="beach"](49.215,-123.275,49.325,-123.015);
  way["leisure"="park"](49.215,-123.275,49.325,-123.015);
  relation["leisure"="park"](49.215,-123.275,49.325,-123.015);
  relation["natural"="water"](49.215,-123.275,49.325,-123.015);
  way["landuse"="residential"](49.215,-123.275,49.325,-123.015);
  relation["landuse"="residential"](49.215,-123.275,49.325,-123.015);
  node["shop"](49.215,-123.275,49.325,-123.015);
  way["shop"](49.215,-123.275,49.325,-123.015);
  node["amenity"~"^(cafe|restaurant|bar|pub|fast_food|ice_cream|bank|pharmacy|cinema|theatre|library|marketplace|community_centre|childcare|dentist|doctors|clinic|post_office)$"](49.215,-123.275,49.325,-123.015);
  way["amenity"~"^(cafe|restaurant|bar|pub|fast_food|ice_cream|bank|pharmacy|cinema|theatre|library|marketplace|community_centre|childcare|dentist|doctors|clinic|post_office)$"](49.215,-123.275,49.325,-123.015);
);
out body;
>;
out skel qt;
