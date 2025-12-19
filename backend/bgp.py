import requests

HEADERS = {"User-Agent": "NetTrace/ASPATH/1.0"}
RIPE_LG = "https://stat.ripe.net/data/looking-glass/data.json"

def get_as_path_for_ip(ip: str):
    """
    Query RIPEstat looking-glass to get an example AS_PATH for the IP's prefix.
    Returns list like ["AS7018","AS3356","AS15169"] or [] if unknown.
    """
    if not ip: return []
    try:
        r = requests.get(RIPE_LG, params={"resource": ip}, headers=HEADERS, timeout=5)
        if r.status_code != 200: return []
        data = r.json().get("data", {})
        # data["results"] is array of collectors -> peers -> routes; pick first with as_path
        results = data.get("results") or []
        for res in results:
            routes = res.get("routes") or []
            for route in routes:
                as_path = route.get("as_path") or []
                if as_path:
                    # normalize asns as "AS####"
                    norm = [f"AS{a}" if isinstance(a, int) or a.isdigit() else (a if a.startswith("AS") else a) for a in as_path]
                    # compact consecutive duplicates
                    compact = []
                    for a in norm:
                        if not compact or compact[-1] != a:
                            compact.append(a)
                    return compact
    except Exception:
        return []
    return []
