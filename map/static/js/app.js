const wsStatusEl = document.getElementById("ws-status");
const eventStatusEl = document.getElementById("event-status");
const entitySelectEl = document.getElementById("entity-select");
const followButtonEl = document.getElementById("follow-btn");
const detailsEl = document.getElementById("details");
const infoBoxEl = document.getElementById("info-box");
const traceModeEl = document.getElementById("trace-mode");
const traceSecondsEl = document.getElementById("trace-seconds");
const traceSamplesEl = document.getElementById("trace-samples");
const saveSettingsEl = document.getElementById("save-settings");

const map = L.map("map", { zoomControl: true }).setView([57.72, 16.94], 11);
L.tileLayer(window.MAP_CONFIG.tileUrl, {
  attribution: window.MAP_CONFIG.tileAttribution,
  maxZoom: window.MAP_CONFIG.tileMaxZoom,
}).addTo(map);

const appState = {
  serverInstanceId: null,
  revision: 0,
  settings: null,
  entities: new Map(),
  selectedEntityId: null,
  followSelected: true,
  markerById: new Map(),
  lineById: new Map(),
  localStateLoaded: false,
};

const entityIcon = L.icon({
  iconUrl: "/static/img/entity.svg",
  iconSize: [28, 28],
  iconAnchor: [14, 14],
  className: "entity-marker",
});

let ws = null;
let reconnectTimer = null;
let reconnectAttempt = 0;
let programmaticMove = false;

function nowMs() {
  return Date.now();
}

function parseIso(value) {
  return new Date(value).getTime();
}

function stableColor(id) {
  let hash = 0;
  for (const ch of id) {
    hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  }
  const hue = hash % 360;
  return `hsl(${hue} 75% 45%)`;
}

function isStale(entity) {
  if (!appState.settings) return false;
  const ageSec = (nowMs() - parseIso(entity.received_at)) / 1000;
  return ageSec > appState.settings.stale_after_seconds;
}

function updateStatus(connected) {
  wsStatusEl.textContent = connected ? "WebSocket connected" : "WebSocket disconnected";
  wsStatusEl.style.background = connected ? "#d1fae5" : "#fee2e2";
}

function setEventStatus(text) {
  eventStatusEl.textContent = text;
}

function renderSelect() {
  const ids = [...appState.entities.keys()].sort();
  entitySelectEl.innerHTML = "";
  if (ids.length === 0) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No entities";
    entitySelectEl.append(opt);
    return;
  }
  for (const id of ids) {
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = id;
    if (id === appState.selectedEntityId) opt.selected = true;
    entitySelectEl.append(opt);
  }
}

function ensureEntityLayer(entity) {
  const id = entity.entity_id;
  let marker = appState.markerById.get(id);
  const latLng = [entity.position.latitude, entity.position.longitude];
  const color = stableColor(id);

  if (!marker) {
    marker = L.marker(latLng, { icon: entityIcon }).addTo(map);
    marker.bindTooltip(id, { permanent: true, direction: "top", className: "entity-label" });
    marker.on("click", () => selectEntity(id, true));
    appState.markerById.set(id, marker);
  } else {
    marker.setLatLng(latLng);
  }

  const markerElement = marker.getElement();
  if (markerElement) {
    markerElement.style.transformOrigin = "center";
    markerElement.style.rotate = `${entity.heading_deg}deg`;
    markerElement.classList.toggle("stale", isStale(entity));
    markerElement.style.filter = id === appState.selectedEntityId ? "drop-shadow(0 0 4px #111)" : "none";
  }

  const linePoints = entity.trace.map((p) => [p.latitude, p.longitude]);
  let polyline = appState.lineById.get(id);
  if (!polyline) {
    polyline = L.polyline(linePoints, { color, weight: 3, opacity: 0.7 }).addTo(map);
    appState.lineById.set(id, polyline);
  } else {
    polyline.setLatLngs(linePoints);
  }
  polyline.setStyle({ weight: id === appState.selectedEntityId ? 5 : 3, opacity: id === appState.selectedEntityId ? 1 : 0.7 });
}

function renderMap() {
  for (const entity of appState.entities.values()) {
    ensureEntityLayer(entity);
  }

  if (!appState.selectedEntityId && appState.entities.size > 0) {
    selectEntity([...appState.entities.keys()].sort()[0], true);
  }

  if (appState.followSelected && appState.selectedEntityId && appState.entities.has(appState.selectedEntityId)) {
    const entity = appState.entities.get(appState.selectedEntityId);
    programmaticMove = true;
    map.panTo([entity.position.latitude, entity.position.longitude], { animate: true });
    setTimeout(() => {
      programmaticMove = false;
    }, 0);
  }
}

function renderDetails() {
  const entity = appState.selectedEntityId ? appState.entities.get(appState.selectedEntityId) : null;
  if (!entity) {
    detailsEl.textContent = "No entity selected.";
    infoBoxEl.textContent = "";
    return;
  }

  const sourceTime = new Date(entity.timestamp);
  const receivedTime = new Date(entity.received_at);
  const telemetryAge = ((Date.now() - sourceTime.getTime()) / 1000).toFixed(1);

  detailsEl.textContent = [
    `Entity: ${entity.entity_id}${isStale(entity) ? " (stale)" : ""}`,
    `Lat/Lon: ${entity.position.latitude.toFixed(6)}, ${entity.position.longitude.toFixed(6)}`,
    `Speed: ${entity.speed_kmh.toFixed(1)} km/h`,
    `Heading: ${entity.heading_deg.toFixed(1)}°`,
    `Source timestamp (UTC): ${entity.timestamp}`,
    `Source timestamp (local): ${sourceTime.toLocaleString()}`,
    `Last server receipt (local): ${receivedTime.toLocaleString()}`,
    `Telemetry age: ${telemetryAge} s`,
  ].join("\n");

  infoBoxEl.textContent = entity.info.join("\n");
}

function selectEntity(id, resumeFollow) {
  appState.selectedEntityId = id;
  if (resumeFollow) {
    appState.followSelected = true;
  }
  renderSelect();
  renderMap();
  renderDetails();
}

function setStateFromSnapshot(state) {
  appState.serverInstanceId = state.server_instance_id;
  appState.revision = state.revision;
  appState.settings = state.settings;
  appState.entities.clear();
  for (const entity of state.entities) {
    appState.entities.set(entity.entity_id, entity);
  }

  traceModeEl.value = state.settings.trace_mode;
  traceSecondsEl.value = state.settings.trace_seconds;
  traceSamplesEl.value = state.settings.trace_samples;

  if (appState.selectedEntityId && !appState.entities.has(appState.selectedEntityId)) {
    appState.selectedEntityId = null;
  }

  renderSelect();
  renderMap();
  renderDetails();
}

function applyEvent(event) {
  if (event.type === "snapshot") {
    setStateFromSnapshot(event.state);
    setEventStatus(`Snapshot revision ${event.state.revision}`);
    return;
  }

  if (!appState.serverInstanceId || event.server_instance_id !== appState.serverInstanceId) {
    reconnectNow();
    return;
  }

  if (event.revision <= appState.revision) {
    return;
  }

  if (event.revision !== appState.revision + 1) {
    reconnectNow();
    return;
  }

  appState.revision = event.revision;

  if (event.type === "entity_updated") {
    appState.entities.set(event.entity.entity_id, event.entity);
    if (!appState.selectedEntityId) {
      appState.selectedEntityId = event.entity.entity_id;
    }
    renderSelect();
    renderMap();
    renderDetails();
    setEventStatus(`Entity updated @ rev ${event.revision}`);
  } else if (event.type === "state_updated") {
    setStateFromSnapshot(event.state);
    setEventStatus(`State updated @ rev ${event.revision}`);
  }
}

function clearSocket() {
  if (ws) {
    ws.onopen = null;
    ws.onclose = null;
    ws.onerror = null;
    ws.onmessage = null;
    try {
      ws.close();
    } catch (_err) {
      // ignored
    }
    ws = null;
  }
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  const base = Math.min(30000, 1000 * 2 ** reconnectAttempt);
  const jitter = Math.floor(Math.random() * 300);
  reconnectAttempt += 1;
  reconnectTimer = setTimeout(connectEvents, base + jitter);
}

function reconnectNow() {
  clearSocket();
  updateStatus(false);
  scheduleReconnect();
}

function connectEvents() {
  clearSocket();
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${protocol}://${location.host}/ws/v1/events`);

  ws.onopen = () => {
    reconnectAttempt = 0;
    updateStatus(true);
  };

  ws.onclose = () => {
    updateStatus(false);
    scheduleReconnect();
  };

  ws.onerror = () => {
    updateStatus(false);
  };

  ws.onmessage = (msg) => {
    let event;
    try {
      event = JSON.parse(msg.data);
    } catch (_err) {
      return;
    }
    applyEvent(event);
  };
}

async function loadInitialHttpState() {
  try {
    const res = await fetch("/api/v1/state", { cache: "no-store" });
    if (!res.ok) return;
    const state = await res.json();
    if (!appState.serverInstanceId) {
      setStateFromSnapshot(state);
      appState.localStateLoaded = true;
      setEventStatus("Loaded HTTP initial state");
    }
  } catch (_err) {
    // ignored
  }
}

async function syncHttpStateFallback() {
  try {
    const res = await fetch("/api/v1/state", { cache: "no-store" });
    if (!res.ok) return;
    const state = await res.json();

    if (!appState.serverInstanceId) {
      setStateFromSnapshot(state);
      appState.localStateLoaded = true;
      setEventStatus("Loaded HTTP initial state");
      return;
    }

    if (state.server_instance_id !== appState.serverInstanceId || state.revision > appState.revision) {
      setStateFromSnapshot(state);
      if (wsStatusEl.textContent !== "WebSocket connected") {
        setEventStatus(`Refreshed via HTTP state @ rev ${state.revision}`);
      }
    }
  } catch (_err) {
    // ignored
  }
}

async function saveSettings() {
  const body = {
    trace_mode: traceModeEl.value,
    trace_seconds: Number(traceSecondsEl.value),
    trace_samples: Number(traceSamplesEl.value),
  };
  const res = await fetch("/api/v1/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ error: { message: "request failed" } }));
    setEventStatus(`Settings error: ${data.error.message}`);
    return;
  }
  setEventStatus("Settings applied globally");
}

entitySelectEl.addEventListener("change", () => {
  if (entitySelectEl.value) {
    selectEntity(entitySelectEl.value, true);
  }
});

followButtonEl.addEventListener("click", () => {
  appState.followSelected = true;
  renderMap();
});

saveSettingsEl.addEventListener("click", () => {
  void saveSettings();
});

map.on("movestart", () => {
  if (!programmaticMove) {
    appState.followSelected = false;
  }
});

setInterval(() => {
  renderDetails();
  for (const [id, marker] of appState.markerById.entries()) {
    const entity = appState.entities.get(id);
    if (!entity) continue;
    const el = marker.getElement();
    if (el) el.classList.toggle("stale", isStale(entity));
  }
}, 1000);

setInterval(() => {
  void syncHttpStateFallback();
}, 3000);

void loadInitialHttpState();
connectEvents();
