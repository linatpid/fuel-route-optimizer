# Fuel Route Optimizer

A Django REST API that, given a **start** and **finish** anywhere in the USA,
returns:

- the **driving route** (GeoJSON geometry you can draw on a map),
- the **cost-optimal fuel stops** along that route, and
- the **total fuel cost** for the trip.

The vehicle is assumed to have a **maximum range of 500 miles** and to achieve
**10 miles per gallon** (a 50-gallon tank). Longer trips therefore return
multiple fuel-ups, chosen to minimise the total spend given the ~8,000 fuel
prices in the provided dataset.

Built with **Django 6.1** + **Django REST Framework**. Routing uses the free,
key-less **OSRM** service; endpoint geocoding uses **Nominatim** (OpenStreetMap).

---

## Why it's fast and makes few external calls

The dataset only gives each station a **name, city, state, and price — no
coordinates**, and the route API must not be hammered. The design handles both:

1. **Stations are geocoded once, offline.** A management command builds a
   `city -> (lat, lon)` lookup from the free **GeoNames US gazetteer** and the
   stations are loaded into the database with coordinates. Serving a request
   never geocodes the 8k stations.
2. **One routing call per request.** A single OSRM call returns the full route
   geometry. Stations are then matched to the route **locally** using a spatial
   hash grid (≈50 ms even for a cross-country route with 11k route points).
3. **Endpoint geocoding is minimal and cacheable.** Only the two endpoints are
   geocoded (Nominatim), results are cached, and passing raw `lat,lon` skips
   geocoding entirely — so a request can be served with a **single** external
   call (OSRM).

Typical timings (local compute is the same regardless of trip length):

| Trip | Distance | Fuel stops | Local compute | Wall time* |
|------|----------|-----------|---------------|-----------|
| Chicago → Houston | ~1,087 mi | 12 | ~50 ms | ~1.5 s |
| New York → Los Angeles | ~2,794 mi | 20 | ~50 ms | ~1.5 s |

\* Wall time is dominated by the single OSRM round-trip on the public server;
the API's own work is tens of milliseconds.

---

## How the optimizer works

Total fuel burned is fixed at `distance / 10` gallons, so cost depends only on
*where* those gallons are bought. Every mile of the trip must be powered by fuel
bought at a station **no more than 500 miles behind** it (you can't carry fuel
further than one tank, and you can't buy from a station you haven't reached
yet). Assigning each mile to the **cheapest station within that backward
range** is both a lower bound on cost and achievable, so it is **optimal**.

The algorithm evaluates that assignment exactly with a sweep over the points
where the "stations currently in range" set changes. See
[`routing/services/optimizer.py`](routing/services/optimizer.py) for the full
explanation. It is covered by unit tests with hand-computed expected costs.

> Assumption: the vehicle starts with an empty tank and buys all fuel for the
> trip; the short stretch before the first station is attributed to that first
> stop (in the US a truck-stop is always within a few miles of the start).

---

## Setup

Requires Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1) Create the database schema
python manage.py migrate

# 2) Build the offline city->coordinates cache (downloads the GeoNames US
#    gazetteer once; the derived cache is already committed, so this is only
#    needed if the station CSV changes).
python manage.py build_geo_cache

# 3) Load the ~8k stations into the DB with coordinates (offline, ~1 second)
python manage.py load_stations

# 4) Run
python manage.py runserver
```

Then open the interactive map demo at <http://127.0.0.1:8000/map> or call the
API directly.

---

## API

### `GET|POST /api/route`

| Param    | Description |
|----------|-------------|
| `start`  | US location — a place name (`"Chicago, IL"`) or `"lat,lon"` (`"41.85,-87.65"`). |
| `finish` | Same formats. |

`GET` takes query params; `POST` takes a JSON body `{"start": ..., "finish": ...}`.

#### Example

```bash
curl "http://127.0.0.1:8000/api/route?start=Chicago,%20IL&finish=Houston,%20TX"
```

Response (geometry trimmed — see [`sample_response.json`](sample_response.json)
for the full shape):

```json
{
  "start":  { "query": "Chicago, IL", "label": "Chicago, ...", "latitude": 41.88, "longitude": -87.63 },
  "finish": { "query": "Houston, TX", "label": "Houston, ...", "latitude": 29.76, "longitude": -95.37 },
  "route": {
    "total_distance_miles": 1086.6,
    "estimated_drive_time_hours": 16.1,
    "geometry": { "type": "LineString", "coordinates": [[-87.63, 41.88], "..."] }
  },
  "vehicle": { "max_range_miles": 500.0, "miles_per_gallon": 10.0, "tank_capacity_gallons": 50.0 },
  "fuel_stops": [
    {
      "order": 1, "name": "HUCKS FOOD & FUEL #379", "city": "Marion", "state": "IL",
      "price_per_gallon": 2.929, "latitude": 37.73, "longitude": -88.93,
      "distance_from_start_miles": 317.0, "detour_miles": 1.2,
      "gallons_purchased": 47.781, "cost_usd": 139.95
    }
  ],
  "summary": {
    "number_of_fuel_stops": 12,
    "total_gallons": 108.655,
    "total_fuel_cost_usd": 319.48,
    "average_price_per_gallon": 2.94
  }
}
```

### `GET /map`

An interactive Leaflet map (OpenStreetMap tiles, no key) that calls the API and
draws the route and fuel stops. Handy for demos:
`/map?start=Denver, CO&finish=Dallas, TX`.

A **Postman collection** is included: [`postman_collection.json`](postman_collection.json).

### `GET /demo`

Resets the demo to a clean, known state: redirects to the map pre-loaded with
the canonical Chicago → Houston trip, ignoring any previous input. Open this
single URL at the start of a screen recording so the demo always looks the same.

#### Errors

| Status | When |
|--------|------|
| `400`  | Missing params, a location that can't be geocoded, or an endpoint outside the USA (checked for both place names and raw `lat,lon`). |
| `422`  | A stretch of the route has no fuel station within 500 miles. |
| `502`  | The routing service is unavailable. |

---

## Project layout

```
fuelroute/                 Django project (settings, urls)
routing/
  models.py                FuelStation (name, city, state, price, lat/lon)
  geo.py                   Haversine / polyline geometry helpers
  services/
    geocoding.py           Nominatim endpoint geocoding (cached; lat,lon fast-path)
    osrm.py                OSRM routing client (the one external call)
    stations.py            Spatial-grid corridor station finder
    optimizer.py           Provably-optimal fuel-stop cost minimiser
    planner.py             Orchestration + response shaping
  management/commands/
    build_geo_cache.py     GeoNames -> city coords cache (offline, one-time)
    load_stations.py       CSV -> DB with coordinates
  templates/routing/map.html   Leaflet demo map
  tests/                   Optimizer, geo, and API tests
routing/data/city_coords.json  Committed offline geocoding cache
```

## Tests

```bash
python manage.py test routing
```

## Configuration

Behaviour is tunable via environment variables (see `fuelroute/settings.py`):
`VEHICLE_MAX_RANGE_MILES`, `VEHICLE_MPG`, `ROUTE_CORRIDOR_MILES`,
`OSRM_BASE_URL`, `NOMINATIM_BASE_URL`.
