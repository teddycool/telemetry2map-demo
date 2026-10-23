# Borgholm → Byxelkrok synthetic telemetry

280 messages, exactly 10 seconds apart. Road length: 61.983 km; timeline: 46 min 30 s.
Vehicle ID: car-01 (the protocol field remains truck_id).
Start: 2026-10-23T10:00:00Z. WGS84; km/h; heading clockwise from north.

JSON is an array; JSONL has one complete WebSocket payload per line. Send each OBJECT separately to /ws/v1/ingest, not the complete array.
Each sample replaces info with 3–5 reproducibly randomized strings.

Positions are interpolated along OSRM driving road geometry using spherical geodesic distance (mean Earth radius 6,371,008.8 m), about 222.22 m per 10-second interval. Heading follows the local road segment. Speed is synthetic constant 80 km/h regardless of bends, traffic or speed limits, not driving guidance. The final sample is at the destination with speed 0; the car reaches the endpoint during the final interval and waits until its next scheduled sample. The initial sample is already moving; acceleration/deceleration are not modeled.

Endpoints are approximate town locations snapped to Östra Kyrkogatan, Borgholm, and Brokvägen, Byxelkrok, not specific addresses.

## Replay
Read JSONL line by line and send each parsed object as a JSON text WebSocket message every 10 seconds. Read/check server ACKs. For live tests, replace each timestamp with the actual UTC send time; preserve intervals and use a fresh message_id prefix for each run. This avoids future-skew rejection and old timestamps after restarting a replay. For accelerated playback use a shorter send interval and current timestamps; the displayed speed remains synthetic 80 km/h. A server retaining only 300 samples can retain this entire run; seconds retention must cover at least 2790 seconds.

## Geometry source and attribution
Retrieved 2026-10-23 from OSRM's public demo routing service:
https://router.project-osrm.org/route/v1/driving/16.6563,56.879;17.014,57.325?overview=full&geometries=geojson
Routing: OSRM, https://project-osrm.org/
Map data © OpenStreetMap contributors, https://www.openstreetmap.org/copyright (ODbL).
route-source.json preserves the original routing response; telemetry and text are synthetic, not recorded GPS data.
