# GitHub Copilot startup prompt: live truck map

Build a complete, runnable first version of a local-network web application for tracking multiple trucks. Implement the application, simulator, documentation, and automated tests; do not stop at a plan or scaffold. Inspect the repository first and preserve unrelated work. If a product requirement is genuinely ambiguous, ask before inventing one. The implementation choices and configurable initial defaults below are authorized starting points, not additional fixed product requirements.

## 1. Goal and scope

An external Linux node sends telemetry over a persistent WebSocket connection to a Python server. The server validates and stores the latest state and a bounded route trace in memory, then broadcasts accepted updates to browser clients. Browsers obtain initial state through an HTTP API and receive live changes over WebSocket. Multiple senders and browsers must work concurrently.

Version 1 runs on a trusted LAN without accounts, login, or sender authentication. No database or persistent route history is required. Implement only the simulated sender now; document the public contract so a real Linux sender can be implemented later.

## 2. Technology and architecture

- Python, Flask application factory, Flask-Sock/simple-websocket for native RFC 6455 WebSockets. Do not substitute Socket.IO: clients must work with a standard WebSocket library and the browser WebSocket API.
- Gunicorn with ONE process and configurable threads; start with 32 threads. All state and the broadcast hub are process-local. Explicitly document why multiple Gunicorn workers/replicas are unsupported without a shared state/pub-sub design. Do not add Redis for v1.
- Serve HTML, CSS, JavaScript, and locally bundled Leaflet assets from Flask. Plain JavaScript ES modules are sufficient; avoid a large frontend framework and avoid requiring a frontend build service at runtime.
- Leaflet with configurable tile URL, attribution, and zoom limit. Default: https://tile.openstreetmap.org/{z}/{x}/{y}.png with visible linked OpenStreetMap contributor attribution. Keep attribution unobscured by the info box. Follow https://operations.osmfoundation.org/policies/tiles/: normal interactive tile requests only, browser caching, valid Referer, no bulk download/prefetch or cache bypass. Public tiles are best effort, not an unlimited guaranteed hosting service. No paid API keys, offline map requirement, geocoding, or routing service.
- Keep validation, telemetry/state storage, route retention, WebSocket transport, HTTP routes, and frontend state/rendering separated. Inject clocks into state logic for deterministic tests.
- Choose compatible maintained dependency versions, lock/pin them reproducibly, and include licenses for vendored assets.

## 3. User interface

- A responsive page dominated by the map, showing all known trucks and their traces with stable distinct colors and readable truck IDs.
- Use a bundled SVG truck icon whose forward direction at zero rotation points north. Rotate the icon by heading while keeping labels readable. No third-party icon API.
- Select a truck from a dropdown or by clicking its marker. Visually highlight selection and its route.
- Follow the selected truck, preserving the user's zoom. Selecting a truck resumes following. Automatically select the first available truck only when no truck is selected.
- User-initiated map panning suspends following; provide a clearly visible "Follow truck" button to resume. Programmatic map movement must not accidentally suspend follow mode.
- Show selected truck latitude, longitude, speed in km/h, heading in degrees, source timestamp, last server receipt time, and telemetry age in a readable map overlay/panel. The original timestamp is UTC; displayed local time must be clearly labelled.
- A scrollable information box anchored at the bottom-right inside the map area shows ONLY the selected truck's strings. Every accepted message REPLACES its contents. An empty array clears it. Render strings and IDs as text, never executable HTML. Preserve Unicode and line boundaries.
- Show connection/reconnection state and per-truck stale status. Retain the last marker when telemetry stops; mark it stale rather than making it appear live. Sender connection and fresh telemetry are distinct concepts.
- Route traces show the last configurable X seconds OR X samples. Offer a retention-mode selector and numeric setting, backed by server configuration endpoints below. Changes apply globally to all browser clients in v1. Explain that increasing retention cannot recover discarded points.
- Empty state, unavailable tiles, missing selection, and disconnected backend must be understandable. Avoid map resets on every update. Keep map attribution and controls accessible on small screens.

## 4. Wire protocol v1

UTF-8 JSON text messages only, one complete JSON object per WebSocket message. Use snake_case. All fields below are required unless explicitly marked optional. Add JSON Schema files for every message family and document examples in docs/protocol.md. Reject unsupported versions and unknown fields in inbound v1 messages to expose sender mistakes.

### Producer connection

Endpoint: `/ws/v1/ingest`. A connection may publish telemetry for several truck IDs. The server is authoritative: the browser never connects directly to a sender. Initial defaults: at most 64 KiB per message, at most 100 info strings, 512 characters per string, and truck IDs matching `[A-Za-z0-9_-]{1,64}`. Expose these limits through configuration and document them.

Example producer message:

```json
{
  "type": "telemetry",
  "version": 1,
  "message_id": "sim-a-000042",
  "truck_id": "truck-a",
  "timestamp": "2026-10-23T12:34:56.123Z",
  "position": {"latitude": 57.7201, "longitude": 16.9402},
  "speed_kmh": 42.5,
  "heading_deg": 125.0,
  "info": ["Status: driving", "Load: test cargo", "Temperature: 18 °C"]
}
```

Semantics:

- Position is WGS84 decimal degrees: latitude [-90,90], longitude [-180,180]. Speed is finite and nonnegative. Heading is finite in [0,360), clockwise from true north; 360 is invalid. Reject booleans as numeric values and reject NaN/Infinity.
- Timestamp is RFC 3339 with an explicit UTC offset; accept `Z` or a numeric offset and normalize outbound timestamps to UTC `Z`. It represents sampling time on the Linux node. Server adds `received_at`; use server receipt time for liveness and time-based trace retention so sender clock errors cannot break expiry.
- `message_id` is a nonempty bounded string used to correlate replies, not a promise of persistent deduplication.
- Per truck, accept only timestamps strictly newer than its last accepted timestamp. Equal timestamps are duplicate/stale and must not append a trace point or broadcast. Older timestamps must not roll back state. Document this clock-ordering requirement for real senders. A server restart clears ordering state.
- Reject timestamps more than configurable `MAX_FUTURE_SKEW_SECONDS` ahead of server time, initially 30 seconds, without changing existing truck state. Older but otherwise ordered telemetry may be accepted; show source age so delayed telemetry is visible.
- Apply each valid telemetry object atomically: latest telemetry, complete replacement info array, and one trace sample. Serialize concurrent updates under the store lock.

Accepted reply:

```json
{"type":"ack","version":1,"message_id":"sim-a-000042","truck_id":"truck-a","status":"accepted","revision":42,"received_at":"2026-10-23T12:34:56.140Z"}
```

Stale/duplicate reply uses `status: "ignored"`, adds `reason: "stale_timestamp"`, and returns the current revision. It does not mutate state. Validation errors use:

```json
{"type":"error","version":1,"message_id":null,"code":"invalid_payload","message":"position.latitude must be between -90 and 90"}
```

Include the input message_id only when safely recoverable. Define stable codes including invalid_json, invalid_payload, unsupported_version, future_timestamp, capacity_exceeded, and unsupported_message. Recoverable errors keep the connection usable and do not broadcast or mutate state. Reject binary messages and oversized frames with appropriate standard close codes (1003 and 1009). Configure the transport's size limit rather than only checking after decoding. Do not echo entire malformed payloads into logs.

### Browser connection and synchronization

Endpoint: `/ws/v1/events`, read-only except documented application ping messages. Every newly connected viewer receives a `snapshot` message containing the exact state shape described below, then ordered live events. A snapshot on every reconnect is mandatory; do not depend on an unbounded replay log.

Also provide `GET /api/v1/state` for initial HTTP state, diagnostics, and non-WebSocket consumers. The frontend may show this while connecting, but must replace it with the WebSocket snapshot and never let a late HTTP response overwrite newer WebSocket state.

State object:

```json
{
  "server_instance_id": "random-uuid-generated-on-server-start",
  "revision": 42,
  "server_time": "2026-10-23T12:34:56.150Z",
  "settings": {"trace_mode":"seconds","trace_seconds":300,"trace_samples":300,"stale_after_seconds":15},
  "trucks": [
    {
      "truck_id":"truck-a",
      "timestamp":"2026-10-23T12:34:56.123Z",
      "received_at":"2026-10-23T12:34:56.140Z",
      "position":{"latitude":57.7201,"longitude":16.9402},
      "speed_kmh":42.5,
      "heading_deg":125.0,
      "info":["Status: driving"],
      "trace":[{"latitude":57.7201,"longitude":16.9402,"timestamp":"2026-10-23T12:34:56.123Z","received_at":"2026-10-23T12:34:56.140Z"}]
    }
  ]
}
```

Snapshot envelope: `{"type":"snapshot","version":1,"state":{...}}`.

Live telemetry envelope: `{"type":"truck_updated","version":1,"server_instance_id":"...","revision":43,"truck":{...}}`. For simplicity in v1, `truck` contains the complete current truck object including its bounded retained trace, not an ambiguous partial patch. A `state_updated` event contains a complete state object and is used after retention-setting changes and scheduled trace expiry. Define these schemas explicitly.

Assign one monotonically increasing global revision to every observable state mutation, including settings and trace expiry. ACKs and pings do not independently increment it. Enqueue updates in the same serialized order as mutations. Register a viewer and capture/enqueue its initial snapshot atomically relative to mutations so no update is missed between registration and snapshot. Never call socket send while holding the state lock.

Use a bounded queue per viewer and a single writer per socket. A slow viewer must not block ingestion or other viewers: close its connection with a documented retryable close code such as 1013 on queue overflow; reconnect receives a fresh snapshot. Include server_instance_id because revisions reset on restart. Browser ignores old/duplicate revisions within an instance and reconnects/resynchronizes on an unexpected revision gap or instance change. HTTP reads must not consume event revisions.

Support `{"type":"ping","version":1}` on either WebSocket endpoint with `{"type":"pong","version":1,"server_time":"..."}`. Document protocol-level heartbeat configuration too. Browser reconnect uses bounded exponential backoff with jitter, initially 1 second and capped at 30 seconds, and clears old sockets/timers. Do not confuse heartbeat responses with truck telemetry freshness.

## 5. HTTP endpoints and retention

- `GET /`: map page.
- `GET /healthz`: JSON health response suitable for container readiness.
- `GET /api/v1/state`: complete snapshot state, including current settings and retained traces.
- `GET /api/v1/settings`: current editable retention settings.
- `PATCH /api/v1/settings`: accepts a nonempty subset of trace_mode (`seconds` or `samples`), trace_seconds, trace_samples. Validate positive integers, reject unknown fields, enforce documented configurable upper bounds, return updated settings. Invalid settings return HTTP 400 with a stable JSON error and no partial mutation. GETs return 200. JSON responses use Cache-Control: no-store.

Start with trace_mode=seconds, trace_seconds=300, trace_samples=300, stale_after_seconds=15. Retain points by monotonic server receipt age in seconds mode, or newest N points in samples mode. Also enforce a configurable hard sample cap per truck in both modes, initially 3600, and a configurable maximum number of known trucks, initially 100; reject new truck IDs when capacity is reached without evicting existing trucks silently. Document why these bounds are needed. Clamp neither payloads nor invalid configuration silently.

Expiry runs even if trucks stop sending, using a periodic background task with clean startup/shutdown. Prune time-expired points on snapshots and setting changes as well; coordinate pruning, revisions, and notifications through the same mutation path. Do not lose the latest marker when a trace becomes empty. Distinguish a valid position at (0,0) from missing data. No persistence across server restarts.

Publish an OpenAPI document for HTTP endpoints and separate WebSocket protocol documentation/JSON Schemas; OpenAPI alone does not describe a bidirectional message contract.

## 6. Docker Compose local environment

Provide Dockerfile(s), compose.yaml, .dockerignore, .env.example, and reproducible dependencies.

- `app`: Flask/Gunicorn, binds 0.0.0.0:8000 inside its container; publish configurable host port 8000 for LAN access. One worker, configurable threads, no Flask debug/reloader. Non-root runtime user and graceful shutdown.
- `simulator`: Python process connecting to ws://app:8000/ws/v1/ingest using standard WebSockets. Wait for app health and retry with backoff because startup ordering alone is insufficient.
- Simulator emits at least three truck IDs on separate deterministic sample routes, initially one update/second/truck. Interpolate short local route segments, calculate heading and speed consistently, use current UTC timestamps, and replace changing info arrays. Simulate vehicles, not real GPS hardware. Keep simulator route/seed/truck count/interval configurable, handle ACK/errors, reconnect after app restart, and terminate cleanly. Avoid jumps when looping routes by using closed paths.
- `tests` profile/service: runs Python unit and real WebSocket/HTTP integration tests in containers and exits with the correct status. Use an isolated application process/port or isolated test Compose project; tests must not rely on the demo simulator or timing of its updates.
- A separate browser-test service/profile may use Playwright with its browser dependencies. Keep browser tests deterministic by intercepting/stubbing tile requests; automated tests must not request public OSM tiles.

Document and verify commands equivalent to:

```bash
docker compose up --build -d app simulator
# Open http://localhost:8000 or http://<host-LAN-IP>:8000
docker compose logs -f app simulator
docker compose --profile test run --build --rm tests
docker compose --profile browser-test run --build --rm browser-tests
docker compose down
```

Make actual service names, profiles, dependencies, and commands match. Explain how to run app alone without simulator and how to change port, retention, and stale timeout. No physical Linux node or paid service needed for testing.

## 7. Automated testing requirements

Use pytest for Python unit/integration tests, and small JavaScript unit tests or Playwright where frontend behaviour requires them. Do not mock away all WebSockets: include tests against the actual selected Gunicorn/Flask-Sock stack on a real local socket. Use bounded timeouts, explicit readiness/event synchronization, and injected clocks instead of arbitrary long sleeps.

Cover:

1. Valid telemetry, multiple independent trucks, atomic info replacement including empty arrays and Unicode.
2. Malformed JSON, binary/oversized messages, unsupported version/type, missing/unknown fields, invalid coordinates, speed, heading, timestamps, booleans, non-finite numbers, and configured limits. Connection remains usable after recoverable errors.
3. UTC normalization, stale/equal timestamp handling, future skew, timestamp ordering after reconnect, and no state/broadcast changes on rejected messages.
4. Seconds/sample retention, exact cutoff semantics, hard caps, expiry with no new telemetry, retained marker, settings validation/atomicity, and irrecoverability of already-pruned samples.
5. Snapshot/live registration race, monotonically ordered revisions under concurrent producers, HTTP/WS consistency, multiple viewers receiving updates, sender disconnect/reconnect, viewer reconnect snapshot, and clean disconnection resource cleanup.
6. Slow viewer isolation and queue overflow without blocking fast viewers/ingestion; use controlled transport barriers rather than flaky timing assumptions.
7. Maximum truck capacity and bounded data structures; server restart empties telemetry and changes server_instance_id.
8. Browser markers, heading rotation, trace updates/expiry, selection by dropdown and click, automatic first selection, pan-to-pause, resume-follow, and no accidental pause on programmatic movement.
9. Info-box replacement/clearing, empty states, stale-state timer without incoming messages, backend reconnect, revision gaps/instance changes, and safe literal rendering of HTML-like malicious strings.
10. App health and one complete simulator -> ingestion -> broadcast -> browser/state path. Browser tests use controlled telemetry and stub tiles; they need no external internet after dependencies/images are installed.

## 8. Deliverables and completion criteria

Use a clear small repository layout, for example application package, static/frontend modules, simulator package, tests/unit, tests/integration, tests/browser, docs/protocol.md, docs/openapi.yaml, docs/schemas, Dockerfile(s), compose.yaml, .env.example, README.md, and a Makefile if helpful. Explain any necessary variation.

README must include architecture/data flow, prerequisites, exact startup/test commands, LAN URL, example telemetry and ACK/error, retention semantics, server limits/thread capacity, concurrency limitations, map attribution/policy links, and troubleshooting WebSocket disconnects and unavailable tiles. Keep deployment assumptions explicit: LAN-only unauthenticated v1; internet deployment/authentication/TLS and multi-process scaling are future work.

Implement in coherent stages, run the relevant tests, fix failures, then summarize files created, exact commands verified, and any remaining limitations. If Docker or another dependency is unavailable in your environment, still deliver the runnable configuration, state precisely what could not be executed, and do not claim tests passed. Do not add real GPS integration, route planning, persistent storage, account management, or unrelated features.
