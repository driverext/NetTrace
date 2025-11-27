let map;
let evtSource = null;
let userLocation = null;
let runCounter = 0;
const runs = [];
const palette = ["#38bdf8", "#f97316", "#22c55e", "#a855f7", "#f59e0b"];
const roleColors = {
  "Local Gateway": "#4ade80",
  "Private Segment": "#6ee7b7",
  "ISP Entry Point": "#34d399",
  "Network Edge": "#38bdf8",
  "Transit / Cloud Backbone": "#60a5fa",
  "Transit Node": "#8b5cf6",
  "CDN Edge / Destination Network Edge": "#f59e0b",
  "Destination Server": "#fb923c",
  "Timeout / Filtered": "#9ca3af",
  Unknown: "#94a3b8",
};

function initMap() {
  map = L.map("map", { worldCopyJump: true }).setView([20, 0], 2);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 18,
  }).addTo(map);
  renderLegend();
  drawStatus("Idle", "Waiting to trace");
}

function renderLegend() {
  const legend = document.getElementById("legend");
  legend.innerHTML = "";
  Object.entries(roleColors).forEach(([role, color]) => {
    const item = document.createElement("div");
    item.className = "legend-item";
    const swatch = document.createElement("span");
    swatch.className = "legend-swatch";
    swatch.style.background = color;
    item.appendChild(swatch);
    const label = document.createElement("span");
    label.textContent = role;
    item.appendChild(label);
    legend.appendChild(item);
  });
}

function resetView() {
  runs.forEach((r) => clearRun(r));
  runs.length = 0;
  document.getElementById("hop-list").innerHTML = "";
  document.getElementById("run-toggles").innerHTML = "";
  clearChart();
  setStatus("Idle");
}

function setStatus(text) {
  document.getElementById("status-text").textContent = text;
}

function drawStatus(pill, detail) {
  document.getElementById("status-pill").textContent = pill;
  document.getElementById("status-detail").textContent = detail;
}

function flagFromCode(code) {
  if (!code) return "";
  const base = 0x1f1e6;
  const offset = (char) => char.charCodeAt(0) - 65;
  const upper = code.toUpperCase();
  return String.fromCodePoint(base + offset(upper[0]), base + offset(upper[1]));
}

function createRun(target) {
  const color = palette[runCounter % palette.length];
  const run = { id: ++runCounter, target, color, hops: [], markers: [], lines: [], visible: true, lastCoord: null, gaps: 0 };
  runs.push(run);
  addRunToggle(run);
  return run;
}

function addRunToggle(run) {
  const container = document.getElementById("run-toggles");
  const btn = document.createElement("button");
  btn.className = "run-toggle";
  btn.dataset.runId = run.id;
  const sw = document.createElement("span");
  sw.className = "run-swatch";
  sw.style.background = run.color;
  btn.appendChild(sw);
  const label = document.createElement("span");
  label.textContent = `Trace ${run.id}: ${run.target}`;
  btn.appendChild(label);
  btn.onclick = () => toggleRunVisibility(run.id);
  container.appendChild(btn);
}

function toggleRunVisibility(runId) {
  const run = runs.find((r) => r.id === runId);
  if (!run) return;
  run.visible = !run.visible;
  run.markers.forEach((m) => {
    if (run.visible) m.addTo(map);
    else m.remove();
  });
  run.lines.forEach((l) => {
    if (run.visible) l.addTo(map);
    else l.remove();
  });
  const cards = document.querySelectorAll(`[data-run="${runId}"]`);
  cards.forEach((c) => {
    c.style.display = run.visible ? "" : "none";
  });
}

function clearRun(run) {
  run.markers.forEach((m) => m.remove());
  run.lines.forEach((l) => l.remove());
}

function addHopCard(run, data) {
  const list = document.getElementById("hop-list");
  const card = document.createElement("div");
  card.className = "hop-card";
  card.dataset.run = run.id;
  card.dataset.hop = data.hop;

  const title = document.createElement("p");
  title.className = "hop-title";
  title.textContent = `#${data.hop} · ${data.ip}`;

  const badge = document.createElement("span");
  badge.className = "badge";
  badge.style.borderColor = run.color;
  badge.textContent = data.role || "Unknown";

  const hostname = document.createElement("p");
  hostname.className = "hop-meta";
  hostname.textContent = data.hostname ? data.hostname : "No reverse DNS";

  const details = document.createElement("p");
  details.className = "hop-meta";
  const flag = flagFromCode(data.country_code);
  details.textContent = `${flag ? flag + " " : ""}${data.city || "Unknown city"}, ${data.country || "Unknown country"}`;

  const rtt = document.createElement("p");
  rtt.className = "hop-meta";
  const rttVal = data.rtt ? `${data.rtt.toFixed(2)} ms` : "?";
  rtt.textContent = `RTT: ${rttVal} · ASN: ${data.asn || "?"} · Org: ${data.org || "?"}`;

  const chips = document.createElement("div");
  chips.className = "card-actions";
  const copyBtn = document.createElement("button");
  copyBtn.textContent = "Copy hop";
  copyBtn.onclick = () => {
    const payload = JSON.stringify(data, null, 2);
    navigator.clipboard?.writeText(payload);
  };
  const panBtn = document.createElement("button");
  panBtn.textContent = "Focus";
  panBtn.onclick = () => focusHop(run, data.hop);
  chips.appendChild(copyBtn);
  chips.appendChild(panBtn);

  const roleChip = document.createElement("span");
  roleChip.className = "chip";
  roleChip.textContent = `${data.method || "TCP"} · ${data.device_type || data.role || ""}`;

  card.appendChild(title);
  card.appendChild(badge);
  card.appendChild(roleChip);
  card.appendChild(hostname);
  card.appendChild(details);
  card.appendChild(rtt);
  card.appendChild(chips);
  list.appendChild(card);
  list.scrollTop = list.scrollHeight;

  card.addEventListener("mouseenter", () => highlightHop(run, data.hop, true));
  card.addEventListener("mouseleave", () => highlightHop(run, data.hop, false));
}

function markerColor(role, runColor) {
  return roleColors[role] || runColor || roleColors.Unknown;
}

function drawHop(run, data) {
  run.hops.push(data);
  addHopCard(run, data);
  plotChart(run);

  if (!data.latitude || !data.longitude || data.timeout) {
    run.gaps += 1;
    return;
  }

  const coord = [data.latitude, data.longitude];
  const marker = L.circleMarker(coord, {
    radius: 8,
    color: markerColor(data.role, run.color),
    weight: 2,
    fillOpacity: 0.9,
  }).addTo(map);
  marker.runId = run.id;
  marker.hopNo = data.hop;

  marker.bindPopup(
    `<strong>Hop #${data.hop}</strong><br>${data.ip}<br>${data.hostname || ""}<br>${data.city || ""} ${data.country || ""}<br>RTT: ${data.rtt || "?"} ms<br>ASN ${data.asn || "?"} · ${data.org || ""}<br>${data.role}`
  );

  run.markers.push(marker);

  if (run.lastCoord) {
    const line = L.polyline([run.lastCoord, coord], {
      color: run.gaps > 0 ? "#9ca3af" : run.color,
      weight: 3,
      dashArray: run.gaps > 0 ? "6 6" : null,
      opacity: 0.85,
    }).addTo(map);
    line.runId = run.id;
    line.hopNo = data.hop;
    run.lines.push(line);
  }

  run.lastCoord = coord;
  run.gaps = 0;

  if (run.markers.length === 1) {
    map.setView(coord, 4);
  }
}

function highlightHop(run, hop, on) {
  const marker = run.markers.find((m) => m.hopNo === hop);
  if (marker) {
    marker.setStyle({ weight: on ? 4 : 2, radius: on ? 10 : 8 });
  }
  const line = run.lines.find((l) => l.hopNo === hop);
  if (line) {
    line.setStyle({ opacity: on ? 1 : 0.85, weight: on ? 5 : 3 });
  }
}

function focusHop(run, hop) {
  const marker = run.markers.find((m) => m.hopNo === hop);
  if (marker) {
    marker.openPopup();
    map.flyTo(marker.getLatLng(), 5, { duration: 0.5 });
  }
}

function stopStream() {
  if (evtSource) {
    evtSource.close();
    evtSource = null;
    drawStatus("Stopped", "Trace cancelled");
  }
}

function startTrace(target) {
  const compareMode = document.getElementById("compare-mode").checked;
  if (!compareMode) {
    stopStream();
    resetView();
  } else {
    stopStream();
  }

  const run = createRun(target);
  setStatus(`Tracing ${target}`);
  drawStatus("Tracing", `Target ${target}`);

  const params = new URLSearchParams({ url: target });
  const mode = document.getElementById("protocol").value;
  params.set("mode", mode);
  const maxTtl = parseInt(document.getElementById("max-ttl").value || "30", 10);
  params.set("ttl", String(maxTtl));
  if (userLocation) {
    params.set("lat", userLocation.lat);
    params.set("lon", userLocation.lon);
  }

  evtSource = new EventSource(`/trace-stream?${params.toString()}`);

  evtSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    drawHop(run, data);
  };

  evtSource.addEventListener("done", () => {
    setStatus("Complete");
    drawStatus("Complete", `Trace ${run.id} finished`);
    stopStream();
  });

  evtSource.onerror = () => {
    setStatus("Stream error");
    drawStatus("Error", "Stream failed; retry?");
    stopStream();
  };
}

async function getUserLocation() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      () => resolve(null),
      { enableHighAccuracy: false, timeout: 1500 }
    );
  });
}

function plotChart(run) {
  const canvas = document.getElementById("rtt-chart");
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const values = run.hops.filter((h) => typeof h.rtt === "number").map((h) => h.rtt);
  if (!values.length) return;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const pad = 8;
  ctx.strokeStyle = run.color;
  ctx.beginPath();
  values.forEach((v, idx) => {
    const x = pad + (idx / Math.max(values.length - 1, 1)) * (canvas.width - pad * 2);
    const norm = (v - min) / Math.max(max - min, 1);
    const y = canvas.height - pad - norm * (canvas.height - pad * 2);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function clearChart() {
  const canvas = document.getElementById("rtt-chart");
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function exportData(format) {
  if (!runs.length) return;
  const latest = runs[runs.length - 1];
  if (!latest.hops.length) return;
  let content = "";
  let mime = "application/json";
  let filename = `trace-${latest.target}.${format}`;
  if (format === "json") {
    content = JSON.stringify(latest.hops, null, 2);
  } else {
    mime = "text/csv";
    const header = ["hop", "ip", "rtt", "role", "asn", "org", "city", "country", "method"].join(",");
    const rows = latest.hops.map((h) =>
      [h.hop, h.ip, h.rtt || "", `"${h.role || ""}"`, `"${h.asn || ""}"`, `"${h.org || ""}"`, `"${h.city || ""}"`, `"${h.country || ""}"`, h.method || ""].join(",")
    );
    content = [header, ...rows].join("\n");
    filename = `trace-${latest.target}.csv`;
  }
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

document.addEventListener("DOMContentLoaded", async () => {
  initMap();
  const shareLocation = document.getElementById("share-location");
  if (shareLocation.checked) {
    userLocation = await getUserLocation();
  }

  shareLocation.addEventListener("change", async (e) => {
    if (e.target.checked) {
      userLocation = await getUserLocation();
    } else {
      userLocation = null;
    }
  });

  const submitTrace = () => {
    const target = document.getElementById("target").value.trim();
    if (!target) return;
    startTrace(target);
  };

  document.getElementById("trace-form").addEventListener("submit", (e) => {
    e.preventDefault();
    submitTrace();
  });

  document.getElementById("trace-button").addEventListener("click", submitTrace);
  document.getElementById("stop-button").addEventListener("click", stopStream);
  document.getElementById("export-json").addEventListener("click", () => exportData("json"));
  document.getElementById("export-csv").addEventListener("click", () => exportData("csv"));
});
