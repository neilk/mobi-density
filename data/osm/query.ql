// Overpass QL query for the Vancouver street network used by analysis/routes.py.
// Run it with ./download.sh (same directory), which saves the result as
// vancouver_highways.json.
//
// Bounding box is (south, west, north, east): the City of Vancouver plus UBC,
// with a margin into Burnaby and the North Shore so routes near the edges have
// somewhere to go.
[out:json][timeout:300];
way["highway"](49.215,-123.275,49.325,-123.015);
out body;
node(w);
out body;
relation["route"="bicycle"](49.215,-123.275,49.325,-123.015);
out body;
