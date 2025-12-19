from flask import Flask, request, Response, jsonify, send_from_directory
from flask_cors import CORS
from pathlib import Path
import os, json, time, threading, queue, math

from traceroute import traceroute_generator
from geo import geolocate_ip, is_private_ip
from bgp import get_as_path_for_ip
from physical import infer_physical_segments, CONTINENT
from backbone import route_between, route_submarine

app = Flask(__name__)
CORS(app)

# --- Role heuristics (unchanged-ish) ---
EDGE_KEYWORDS = [
    "google", "1e100.net", "cloudflare", "cdn", "akamai", "facebook",
    "fbcdn", "netflix", "amazonaws", "azure", "cloudfront", "fastly",
    "limelight", "edgecast", "msedge", "yahoo", "gstatic", "youtube",
    "ytimg", "baidu", "tencent", "alibaba", "qq.com", "icloud",
    "apple", "snapchat", "xcdn", "vimeo", "discord", "zoom",
    "linkedin", "verizon", "edgesuite", "cdn77", "edgekey", "akamaihd",
    "ovh", "hetzner", "voxility", "microsoft", "akamai.net", "cdn.cloudflare.net"
]

def classify_hop(ip, hostname, rtt, index, org=None, asn=None, seen_ips=None, rtt_delta=None):
    if ip is None:
        return "Timeout / Filtered"
    if is_private_ip(ip):
        return "Local Gateway"
    if index == 1:
        return "ISP Entry Point"
    seen_ips = seen_ips or []
    host_org_str = " ".join([hostname or "", org or "", asn or ""]).lower()
    for keyword in EDGE_KEYWORDS:
        if keyword in host_org_str:
            return "Destination Network Edge"
    if rtt is not None and rtt > 300:
        return "Possible Exit / Destination"
    if rtt_delta is not None and rtt_delta > 80:
        return "Long Haul / Interconnect"
    if seen_ips.count(ip) >= 3:
        return "Probe Catcher"
    return "Transit Node"

def detect_device_type(ip, hostname, org, rtt, index, total_hops, seen_count):
    host = (hostname or "").lower()
    org = (org or "").lower()
    if any(k in host for k in ["elb","lb","loadbalancer","vip","proxy","edgekey"]): return "Load Balancer"
    if any(k in host for k in ["web","app","origin","node","login","api","cdn"]):   return "Application Server"
    if any(k in host for k in ["ttl","trap","blackhole","ttlcatch"]):               return "Probe Catcher"
    if any(k in host for k in ["edge","gw","gwr","border","er","bdr"]):             return "Edge Router"
    if seen_count > 2: return "Probe Catcher"
    if index == total_hops: return "Application Server"
    if rtt is not None and rtt > 200 and index >= total_hops - 2: return "Application Server"
    if index == 2 and rtt is not None and rtt < 20: return "Edge Router"
    return "Unknown"

def guess_medium(distance_km, rtt_delta, rtt):
    """
    Heuristic medium guess based on distance and RTT deltas.
    Only directional hints; not authoritative.
    """
    # If RTT is implausibly low for the geo distance, flag the geo as suspect/anycast
    if distance_km is not None and rtt is not None:
        # ~0.009 ms per km round-trip in fiber (speed-of-light discount)
        min_fiber_rtt = distance_km * 0.009
        if rtt < min_fiber_rtt * 0.6:
            return "Geo likely wrong/anycast (RTT too low for distance)"

    if rtt and rtt >= 400:
        return "Likely satellite/space link"
    if rtt_delta is not None and rtt_delta >= 350:
        return "Likely satellite/space link"
    if distance_km is not None:
        if distance_km > 2000:
            if rtt_delta is not None and rtt_delta < 120:
                return "Likely long-haul fiber (subsea/backbone)"
            return "Possible long-haul fiber/backbone"
        if distance_km > 400:
            return "Likely terrestrial fiber/backbone"
        if distance_km < 120 and rtt_delta is not None and rtt_delta < 12:
            return "Likely metro fiber/ethernet"
    if rtt_delta is not None and rtt_delta > 120:
        return "Possible wireless/microwave backhaul"
    return "Unknown"

def haversine_km(a, b):
    if not a or not b: return None
    (lat1, lon1), (lat2, lon2) = a, b
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None: return None
    R=6371.0
    import math
    dlat=math.radians(lat2-lat1); dlon=math.radians(lon2-lon1)
    p=(math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2)
    return 2*R*math.asin(math.sqrt(p))

# ---------------------------------------------------------------------
# Timeout compression + stream
# ---------------------------------------------------------------------
def run_trace_to_queue(url, q, protocol, max_hops, probes_per_ttl, dport):
    try:
        seen_ips = []
        timeout_streak = 0
        prev_latlon = None
        prev_rtt = None
        prev_payload = None
        hop_index = 0
        collected_hops = []  # store enriched hops for post-processing
        pending_privates = []

        for hop in traceroute_generator(
            url,
            protocol=protocol,
            max_hops=max_hops,
            probes_per_ttl=probes_per_ttl,
            dest_port=dport
        ):
            if hop is None: 
                continue

            ip = hop.get("ip"); rtt = hop.get("rtt")

            # accumulate timeouts and flush later
            if not ip:
                timeout_streak += 1
                continue
            else:
                if timeout_streak > 0:
                    q.put({"ip": None, "rtt": None, "timeout_count": timeout_streak})
                    timeout_streak = 0

            hop_index += 1
            seen_ips.append(ip)

            geo = geolocate_ip(ip, rtt)
            rtt_delta = (rtt - prev_rtt) if (rtt is not None and prev_rtt is not None) else None

            role = classify_hop(
                ip, geo.get("hostname"), rtt, hop_index,
                geo.get("org"), geo.get("asn"), seen_ips, rtt_delta=rtt_delta
            )
            device_type = detect_device_type(
                ip, geo.get("hostname"), geo.get("org"), rtt,
                hop_index, max_hops, seen_ips.count(ip)
            )

            latlon = (geo.get("lat"), geo.get("lon")) if geo.get("lat") and geo.get("lon") else None

            # If this is a private/local hop without coordinates, hold it until we see the next geolocated hop
            if is_private_ip(ip) and not latlon:
                payload = {
                    **geo,
                    "rtt": rtt,
                    "rtt_delta": rtt_delta,
                    "role": role,
                    "device_type": device_type,
                    "distance_from_prev_km": None,
                    "medium_guess": guess_medium(None, rtt_delta, rtt),
                    "hop_index": hop_index,
                    "protocol": protocol,
                }
                pending_privates.append(payload)
                if rtt is not None:
                    prev_rtt = rtt  # still advance RTT history
                prev_payload = payload
                continue

            # Flush any pending private hops now that we have an anchor location
            if pending_privates:
                anchor_latlon = latlon if latlon else prev_latlon
                anchor_city = geo.get("city") if geo.get("city") else None
                anchor_country = geo.get("country") if geo.get("country") else None
                anchor_cc = geo.get("country_code") if geo.get("country_code") else None
                for pending in pending_privates:
                    if anchor_latlon:
                        pending["lat"], pending["lon"] = anchor_latlon
                        pending["city"] = pending.get("city") or anchor_city
                        pending["country"] = pending.get("country") or anchor_country
                        pending["country_code"] = pending.get("country_code") or anchor_cc
                        pending["geo_warning"] = pending.get("geo_warning") or "Approximate local location (using next hop)"
                    dist_prev = haversine_km(prev_latlon, anchor_latlon) if prev_latlon and anchor_latlon else None
                    pending["distance_from_prev_km"] = round(dist_prev, 1) if dist_prev else None
                    pending["medium_guess"] = guess_medium(dist_prev, pending.get("rtt_delta"), pending.get("rtt"))
                    collected_hops.append(pending)
                    q.put(pending)
                    if anchor_latlon:
                        prev_latlon = anchor_latlon
                    if pending.get("rtt") is not None:
                        prev_rtt = pending["rtt"]
                    prev_payload = pending
                pending_privates = []

            distance_km = haversine_km(prev_latlon, latlon) if prev_latlon and latlon else None
            medium_guess = guess_medium(distance_km, rtt_delta, rtt)
            prev_cc = prev_payload.get("country_code") if prev_payload else None
            curr_cc = geo.get("country_code")
            prev_cont = CONTINENT.get(prev_cc) if prev_cc else None
            curr_cont = CONTINENT.get(curr_cc) if curr_cc else None
            if distance_km and prev_cont and curr_cont and prev_cont != curr_cont:
                medium_guess = "Likely submarine fiber (intercontinental)"
            elif distance_km and medium_guess.startswith("Likely") and (prev_cont == curr_cont):
                medium_guess = "Likely terrestrial fiber"

            synthetic_path = None
            if latlon and prev_latlon:
                direct = haversine_km(prev_latlon, latlon) or 0
                # Try real submarine cable route for intercontinental
                if prev_cont and curr_cont and prev_cont != curr_cont and direct > 800:
                    sub_path = route_submarine(prev_latlon[0], prev_latlon[1], latlon[0], latlon[1])
                    if sub_path:
                        synthetic_path = sub_path
                if synthetic_path is None:
                    route = route_between(prev_latlon[0], prev_latlon[1], latlon[0], latlon[1])
                    if route:
                        backbone_coords, route_len, a_id, b_id, ids = route
                        path_coords = [prev_latlon] + [(lat, lon) for lat, lon in backbone_coords] + [latlon]
                        from backbone import node_coord
                        snap_a = node_coord(ids[0])
                        snap_b = node_coord(ids[1])
                        snap_dist_a = haversine_km(prev_latlon, snap_a) if snap_a else None
                        snap_dist_b = haversine_km(latlon, snap_b) if snap_b else None
                        if direct > 4000:
                            synthetic_path = path_coords
                        elif direct > 200 and snap_dist_a is not None and snap_dist_b is not None:
                            if snap_dist_a <= 150 and snap_dist_b <= 150 and route_len <= direct * 1.15:
                                synthetic_path = path_coords

            payload = {
                **geo,
                "rtt": rtt,
                "rtt_delta": rtt_delta,
                "role": role,
                "device_type": device_type,
                "distance_from_prev_km": round(distance_km, 1) if distance_km else None,
                "medium_guess": medium_guess,
                "hop_index": hop_index,
                "protocol": protocol,
                "synthetic_path": synthetic_path,
            }
            collected_hops.append(payload)
            q.put(payload)

            if latlon: prev_latlon = latlon
            if rtt is not None: prev_rtt = rtt
            prev_payload = payload

        # flush remaining timeout summary at the end
        if timeout_streak > 0:
            q.put({"ip": None, "rtt": None, "timeout_count": timeout_streak})

        # flush any remaining private hops without anchor
        if pending_privates:
            for pending in pending_privates:
                pending["geo_warning"] = pending.get("geo_warning") or "Location unavailable for private hop"
                collected_hops.append(pending)
                q.put(pending)
            pending_privates = []

        # --- POST: Enrich with AS-PATH + physical segments ---
        dest_ip = None
        for h in reversed(collected_hops):
            if h.get("ip"): 
                dest_ip = h["ip"]; 
                break

        as_path = get_as_path_for_ip(dest_ip) if dest_ip else []
        segments = infer_physical_segments(collected_hops)

        meta = {"as_path": as_path, "physical_segments": segments}
        q.put(("META", meta))

        q.put("DONE")

    except Exception as e:
        q.put({"error": f"Trace failed: {e}"})
        q.put("DONE")


@app.route("/trace-stream")
def trace_stream():
    url = request.args.get("url")
    if not url:
        return jsonify({"error": "Missing url"}), 400

    protocol = (request.args.get("protocol") or "tcp").lower()
    max_hops = int(request.args.get("max_hops") or 30)
    probes = int(request.args.get("probes") or 2)
    dport = int(request.args.get("dport") or 80)

    q = queue.Queue()
    t = threading.Thread(target=run_trace_to_queue, args=(url, q, protocol, max_hops, probes, dport), daemon=True)
    t.start()

    def event_stream():
        while True:
            item = q.get()
            if item == "DONE":
                yield "event: done\ndata: end\n\n"
                break
            if isinstance(item, tuple) and item[0] == "META":
                yield f"event: meta\ndata: {json.dumps(item[1])}\n\n"
                continue
            yield f"data: {json.dumps(item)}\n\n"
            time.sleep(0.08)

    return Response(event_stream(), content_type="text/event-stream")


@app.route("/health")
def health():
    return jsonify({"ok": True})

# Static frontend
@app.route("/")
def serve_index():
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    index_path = frontend_dir / "index.html"
    if not index_path.exists():
        return f"index.html not found at {index_path}", 404
    return send_from_directory(frontend_dir, "index.html")

@app.route("/<path:filename>")
def serve_static(filename):
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    file_path = frontend_dir / filename
    if not file_path.exists():
        return f"File not found: {file_path}", 404
    return send_from_directory(frontend_dir, filename)

if __name__ == "__main__":
    print("[info] NetTrace backend running on http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
