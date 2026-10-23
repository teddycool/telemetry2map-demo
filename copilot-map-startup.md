# GitHub Copilot startup prompt: live telemetry map

Build and maintain a LAN-first telemetry map demo using Flask + Flask-Sock native RFC6455 websockets.

## Goal

Create a general application that accepts live position telemetry from any source and visualizes entities on a map with retained traces, stale detection, and settings control.

## Transport and endpoints

- Ingest websocket: `/ws/v1/ingest`
- Events websocket: `/ws/v1/events`
- HTTP state: `GET /api/v1/state`
- HTTP settings: `GET/PATCH /api/v1/settings`

## Telemetry envelope

```json
{
  "type": "telemetry",
  "version": 1,
  "message_id": "sim-a-000042",
  "entity_id": "entity-a",
  "timestamp": "2026-10-23T12:34:56.123Z",
  "position": {"latitude": 57.7201, "longitude": 16.9402},
  "speed_kmh": 42.5,
  "heading_deg": 125.0,
  "info": ["Status: active", "Source: demo", "Temperature: 18 °C"]
}
```

## ACK envelope

```json
{"type":"ack","version":1,"message_id":"sim-a-000042","entity_id":"entity-a","status":"accepted","revision":42,"received_at":"2026-10-23T12:34:56.140Z"}
```

## Event envelopes

- Snapshot: `{"type":"snapshot","version":1,"state":{...}}`
- Live entity update: `{"type":"entity_updated","version":1,"server_instance_id":"...","revision":43,"entity":{...}}`
- Full state update: `{"type":"state_updated","version":1,"server_instance_id":"...","revision":44,"state":{...}}`

## Constraints

- LAN-only v1 deployment
- In-memory process-local state
- Single Gunicorn worker only
- Strong payload validation with bounded resource usage

Use the JSON schemas under `docs/schemas` as protocol source of truth.
