# WebSocket protocol v1

## Endpoints

- Producer ingest: `/ws/v1/ingest`
- Browser events: `/ws/v1/events`

Messages are UTF-8 JSON text messages only, one object per message, snake_case fields.

## Ingest (`/ws/v1/ingest`)

### Producer -> server telemetry

See schema: `docs/schemas/ingest.telemetry.json`.

Validation notes:

- Unknown fields are rejected.
- `version` must be `1`.
- `timestamp` must be RFC3339 with explicit offset (`Z` or numeric offset).
- `heading_deg` is `[0,360)`; `360` is invalid.
- Booleans are rejected for numeric fields.
- Per truck, timestamp must be strictly newer than last accepted timestamp.
- Future skew beyond `MAX_FUTURE_SKEW_SECONDS` is rejected.

### Server replies

Accepted ACK:

```json
{"type":"ack","version":1,"message_id":"sim-a-000042","truck_id":"truck-a","status":"accepted","revision":42,"received_at":"2026-10-23T12:34:56.140Z"}
```

Ignored stale/duplicate timestamp:

```json
{"type":"ack","version":1,"message_id":"sim-a-000042","truck_id":"truck-a","status":"ignored","reason":"stale_timestamp","revision":42,"received_at":"2026-10-23T12:34:56.140Z"}
```

Error:

```json
{"type":"error","version":1,"message_id":null,"code":"invalid_payload","message":"position.latitude must be between -90 and 90"}
```

Stable error codes:

- `invalid_json`
- `invalid_payload`
- `unsupported_version`
- `unsupported_message`
- `future_timestamp`
- `capacity_exceeded`

Binary frames are rejected with close code `1003`. Message size is transport-limited (`MAX_MESSAGE_BYTES`), with oversized frames rejected with `1009` by the websocket stack.

## Browser events (`/ws/v1/events`)

### Snapshot on connect

First event is always:

```json
{"type":"snapshot","version":1,"state":{...}}
```

State schema: `docs/schemas/state.json`.

### Live events

- Truck update: `docs/schemas/events.truck_updated.json`
- State update: `docs/schemas/events.state_updated.json`

`revision` is monotonic per server instance. Clients should resync on revision gap or `server_instance_id` change.

## Ping/pong

Either endpoint accepts:

```json
{"type":"ping","version":1}
```

And returns:

```json
{"type":"pong","version":1,"server_time":"2026-10-23T12:34:56.150Z"}
```

## Retention semantics

- `trace_mode=seconds`: keep points with `received_at >= now - trace_seconds`.
- `trace_mode=samples`: keep newest `trace_samples` points.
- Both modes also enforce `HARD_TRACE_CAP`.
- Increasing retention does not restore already-pruned points.

## Scaling limitations

This v1 implementation keeps state and viewer queues in-process. Run Gunicorn with one worker only. Multiple workers/replicas require shared state + pub/sub to keep snapshots/revisions/events coherent.
