import ipaddress, socket, requests
from functools import lru_cache

_session = requests.Session()
_session.headers.update({"User-Agent": "NetTrace/2.1"})
DEFAULT_TIMEOUT = 6

ANYCAST_ASNS = {
    "AS15169": "Google LLC",
    "AS13335": "Cloudflare, Inc.",
    "AS54113": "Fastly, Inc.",
    "AS20940": "Akamai Technologies",
    "AS32934": "Meta Platforms",
    "AS16509": "Amazon.com, Inc.",
    "AS14618": "Amazon AWS",
    "AS8075": "Microsoft Corporation",
    "AS7018": "AT&T Services",
    "AS3356": "Lumen / Level3",
}
ANYCAST_KEYS = ["google","1e100","cloudflare","fastly","akamai","fbcdn","ytimg","gstatic","cdn","msedge","edgekey","edgesuite","limelight"]

def is_private_ip(ip):
    try:
        return ip and ipaddress.ip_address(ip).is_private
    except Exception:
        return False

@lru_cache(maxsize=2048)
def _reverse_dns(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return None

@lru_cache(maxsize=4096)
def _fetch_json(url):
    try:
        r = _session.get(url, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}

def geolocate_ip(ip, rtt=None):
    base = {
        "ip": ip, "lat": None, "lon": None, "city": "Unknown",
        "country": "Unknown", "country_code": None,
        "asn": None, "asn_name": None,
        "org": None, "isp": None, "hostname": None,
        "anycast": False, "geo_warning": None,
    }
    if not ip:
        return base
    if is_private_ip(ip):
        base.update({
            "city": "Private Network", "country": "Internal",
            "isp": "Local", "org": "Private", "asn": "N/A",
            "asn_name": "Private", "hostname": _reverse_dns(ip)
        })
        return base

    # 1) geo
    geo = _fetch_json(f"https://ipwho.is/{ip}")
    if geo:
        base.update({
            "lat": geo.get("latitude"),
            "lon": geo.get("longitude"),
            "city": geo.get("city") or geo.get("region") or "Unknown",
            "country": geo.get("country") or "Unknown",
            "country_code": geo.get("country_code"),
        })
        conn = geo.get("connection") or {}
        # use IPWho data as a fallback for org/ISP/asn
        if not base.get("org") and conn.get("org"):
            base["org"] = conn.get("org")
        if not base.get("isp") and conn.get("isp"):
            base["isp"] = conn.get("isp")
        if not base.get("asn") and conn.get("asn"):
            base["asn"] = f"AS{conn.get('asn')}"
            base["asn_name"] = base.get("asn_name") or conn.get("org") or conn.get("isp")

    # 2) asn/bgp
    bgp = _fetch_json(f"https://api.bgpview.io/ip/{ip}")
    if bgp and bgp.get("data"):
        d = bgp["data"]
        if "prefixes" in d and d["prefixes"]:
            p = d["prefixes"][0]
            if p.get("asn"): base["asn"] = f"AS{p.get('asn')}"
            base["asn_name"] = p.get("name")
            base["org"] = p.get("name")
        if "asn" in d and isinstance(d["asn"], dict):
            a = d["asn"]
            if a.get("asn"): base["asn"] = base["asn"] or f"AS{a.get('asn')}"
            base["asn_name"] = base["asn_name"] or a.get("name")
            base["org"] = base["org"] or a.get("name")
            base["isp"] = a.get("description") or base["org"]

    base["hostname"] = _reverse_dns(ip)

    # 3) anycast hints
    host = (base["hostname"] or "").lower()
    org = (base["org"] or "").lower()
    if any(k in host or k in org for k in ANYCAST_KEYS): base["anycast"] = True
    if base.get("asn") in ANYCAST_ASNS:
        base["anycast"] = True
        base["asn_name"] = ANYCAST_ASNS[base["asn"]]
        if not base["org"]: base["org"] = base["asn_name"]

    # 4) sanity with RTT
    if rtt is not None and base["country"] not in ("Internal", "Unknown"):
        if rtt < 50 and base["country"] not in ("United States","Canada","Mexico"):
            base["geo_warning"] = f"Likely Anycast: RTT={rtt} ms too short for {base['country']}."
            base["anycast"] = True

    if not base["isp"]: base["isp"] = base["org"] or base["asn_name"]
    return base
