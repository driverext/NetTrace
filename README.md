## NetTrace

Real-time TCP-first traceroute visualizer with live geolocation, ASN/WHOIS enrichment, hop classification, and SSE streaming to a Leaflet map.

### Features
- TCP SYN traceroute with ICMP/UDP fallback (Scapy).
- Reverse DNS + RDAP WHOIS for ASN/org + HTTP geolocation lookup.
- Heuristic hop role + device-type labeling.
- Server-Sent Events stream every hop; client draws markers/paths live.
- Leaflet map with gap-aware polylines, sidebar of hop details, and optional user-location anchoring for private hops.

### Built-in file browser API (read-only)
- List: `GET /api/fs/list?path=.` (relative to project root; returns dirs/files for that path)
- Read: `GET /api/fs/read?path=templates/index.html&max_bytes=50000` (UTF-8, truncated if over limit)
Paths are sanitized to stay within the project directory.

### Quickstart
1) Create a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```
2) Install deps:
```bash
pip install -r requirements.txt
```
3) Run:
```bash
python app.py
```
4) Open http://127.0.0.1:5000 and start a trace.

### UI assets
- Leaflet JS/CSS and marker images vendored locally in `static/` to avoid CDN issues.

### Notes
- Geolocation uses ipapi.co; WHOIS uses RDAP via ipwhois. Offline use will still stream hops but enrichment may be partial.
- Scapy may require elevated privileges or WinPcap/Npcap depending on OS.
- Stop condition: stream ends after the destination is reached and 5 trailing hops are observed (or max TTL).
- Frontend extras: protocol picker, max TTL control, stop button, compare mode (keep prior traces), hop copy/focus, JSON/CSV export, RTT mini-chart, run toggles, and local Leaflet assets.
