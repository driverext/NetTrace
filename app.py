import json
import socket
from pathlib import Path
from typing import Dict, Generator, Optional

from flask import Flask, Response, jsonify, render_template, request
from flask_cors import CORS

from geo import geolocate_ip, is_private_ip
from traceroute import traceroute_generator, resolve_target


BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)


def classify_hop(hop_index: int, hop: Dict, destination_ip: str) -> str:
    """
    Attempt to categorize the hop's network role using lightweight heuristics.
    """
    hostname = (hop.get("hostname") or "").lower()
    org = (hop.get("org") or "").lower()
    rtt = hop.get("rtt") or 0
    ip_addr = hop.get("ip") or ""

    if hop.get("timeout"):
        return "Timeout / Filtered"
    if is_private_ip(ip_addr):
        return "Local Gateway" if hop_index <= 2 else "Private Segment"
    if ip_addr == destination_ip:
        return "Destination Server"
    if any(keyword in hostname for keyword in ("edge", "cdn", "akamai", "cloudfront", "cloudflare")):
        return "CDN Edge / Destination Network Edge"
    if any(keyword in hostname for keyword in ("gw", "gateway", "border", "brdr", "peering")):
        return "Network Edge"
    if any(keyword in hostname for keyword in ("core", "backbone", "transit", "xe-", "ae")):
        return "Transit Node"
    if any(keyword in org for keyword in ("amazon", "aws", "google", "microsoft", "azure")):
        return "Transit / Cloud Backbone"
    if rtt < 10 and hop_index <= 3:
        return "ISP Entry Point"
    return "Transit Node"


def detect_device_type(hop: Dict) -> str:
    hostname = (hop.get("hostname") or "").lower()
    if hop.get("timeout"):
        return "Unknown / Silent"
    if any(k in hostname for k in ("edge", "gw", "router", "rtr")):
        return "Edge Router"
    if any(k in hostname for k in ("lb", "elb", "balancer", "gslb")):
        return "Load Balancer"
    if any(k in hostname for k in ("cache", "cdn", "pop")):
        return "Cache / POP"
    if any(k in hostname for k in ("srv", "app", "web")):
        return "Application Server"
    return "Network Device"


def event_stream(target: str, user_lat: Optional[float], user_lon: Optional[float], mode: str, max_ttl: int) -> Generator[str, None, None]:
    dest_ip = resolve_target(target)
    completion_buffer = 0
    stop_after = 5

    for hop in traceroute_generator(dest_ip, max_hops=max_ttl, mode=mode):
        hop_index = hop["hop"]
        geo = geolocate_ip(hop["ip"], user_lat=user_lat, user_lon=user_lon)
        geo.update(
            {
                "hop": hop_index,
                "rtt": hop.get("rtt"),
                "method": hop.get("method"),
                "reached_destination": hop.get("reached"),
                "timeout": hop.get("timeout", False),
                "target": target,
                "destination_ip": dest_ip,
            }
        )

        geo["role"] = classify_hop(hop_index, geo, dest_ip)
        geo["device_type"] = detect_device_type(geo)

        yield f"data: {json.dumps(geo)}\n\n"

        if hop.get("reached"):
            completion_buffer += 1
            if completion_buffer >= stop_after:
                break

    yield "event: done\ndata: end\n\n"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


def _safe_path(rel_path: str) -> Path:
    """
    Resolve a user-supplied path to an absolute path under BASE_DIR.
    Raises ValueError if the path escapes the allowed root.
    """
    target = (BASE_DIR / rel_path).resolve()
    if not str(target).startswith(str(BASE_DIR)):
        raise ValueError("Path escapes project root")
    return target


@app.route("/api/fs/list")
def fs_list():
    rel = request.args.get("path", "").strip()
    try:
        target = _safe_path(rel or ".")
    except ValueError:
        return Response("Invalid path", status=400)

    if not target.exists():
        return Response("Not found", status=404)

    if target.is_file():
        stat = target.stat()
        return jsonify(
            {"path": str(target.relative_to(BASE_DIR)), "type": "file", "size": stat.st_size}
        )

    entries = []
    for child in target.iterdir():
        try:
            stat = child.stat()
        except OSError:
            continue
        entries.append(
            {
                "name": child.name,
                "type": "dir" if child.is_dir() else "file",
                "size": stat.st_size,
            }
        )
    entries.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))

    return jsonify(
        {
            "path": str(target.relative_to(BASE_DIR)),
            "type": "dir",
            "entries": entries,
        }
    )


@app.route("/api/fs/read")
def fs_read():
    rel = request.args.get("path", "").strip()
    max_bytes = request.args.get("max_bytes", default=50000, type=int)
    try:
        target = _safe_path(rel)
    except ValueError:
        return Response("Invalid path", status=400)

    if not target.exists():
        return Response("Not found", status=404)
    if target.is_dir():
        return Response("Path is a directory", status=400)

    try:
        data = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return Response("Unable to read file", status=500)

    truncated = False
    if len(data.encode("utf-8")) > max_bytes:
        data = data.encode("utf-8")[:max_bytes].decode("utf-8", errors="replace")
        truncated = True

    return jsonify(
        {
            "path": str(target.relative_to(BASE_DIR)),
            "size": target.stat().st_size,
            "truncated": truncated,
            "content": data,
        }
    )


@app.route("/trace-stream")
def trace_stream():
    target = request.args.get("url") or request.args.get("target")
    if not target:
        return Response("Missing url parameter", status=400)

    user_lat = request.args.get("lat", type=float)
    user_lon = request.args.get("lon", type=float)
    mode = request.args.get("mode", default="auto").lower()
    max_ttl = request.args.get("ttl", default=30, type=int)
    max_ttl = 1 if max_ttl < 1 else (64 if max_ttl > 64 else max_ttl)
    if mode not in ("auto", "tcp", "icmp", "udp"):
        mode = "auto"

    try:
        stream = event_stream(target, user_lat, user_lon, mode, max_ttl)
    except socket.gaierror:
        return Response("Unable to resolve target", status=400)

    return Response(stream, mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)
