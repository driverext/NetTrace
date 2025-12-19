import math

CONTINENT = {
    "US":"NA","CA":"NA","MX":"NA","PR":"NA",
    "GB":"EU","IE":"EU","FR":"EU","DE":"EU","NL":"EU","ES":"EU","IT":"EU","SE":"EU","NO":"EU","DK":"EU","PL":"EU",
    "BR":"SA","AR":"SA","CL":"SA","CO":"SA","PE":"SA",
    "JP":"AS","CN":"AS","KR":"AS","SG":"AS","HK":"AS","TW":"AS","IN":"AS","AE":"AS","SA":"AS","TR":"AS","IL":"AS",
    "AU":"OC","NZ":"OC",
    "ZA":"AF","NG":"AF","EG":"AF","MA":"AF","KE":"AF",
}

CORRIDORS = [
    {"name":"Transatlantic (NA <-> EU)", "from":"NA", "to":"EU"},
    {"name":"Transpacific (NA <-> AS)", "from":"NA", "to":"AS"},
    {"name":"Europe <-> Asia (Med/Suez)", "from":"EU", "to":"AS"},
    {"name":"Europe <-> Africa", "from":"EU", "to":"AF"},
    {"name":"US <-> South America", "from":"NA", "to":"SA"},
    {"name":"Asia <-> Australia", "from":"AS", "to":"OC"},
]

def haversine_km(a, b):
    if not a or not b: return 0
    (lat1, lon1), (lat2, lon2) = a, b
    if None in (lat1, lon1, lat2, lon2): return 0
    R=6371.0
    dlat=math.radians(lat2-lat1); dlon=math.radians(lon2-lon1)
    p=(math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2)
    return 2*R*math.asin(math.sqrt(p))

def infer_physical_segments(hops):
    """
    Infer likely submarine/long-haul segments from hop geos and RTTs.
    Filters false positives (e.g. intra-US or anycast).
    """
    segments = []
    prev = None
    for hop in hops:
        if not hop or not hop.get("ip"): 
            continue
        if hop.get("lat") is None or hop.get("lon") is None:
            continue
        curr = hop
        if prev:
            a = (prev["lat"], prev["lon"])
            b = (curr["lat"], curr["lon"])
            dist = haversine_km(a, b)
            cc_a = prev.get("country_code")
            cc_b = curr.get("country_code")
            cont_a = CONTINENT.get(cc_a, None)
            cont_b = CONTINENT.get(cc_b, None)
            rtt_jump = 0
            if hop.get("rtt") and prev.get("rtt"):
                rtt_jump = hop["rtt"] - prev["rtt"]

            # --- smarter filters ---
            if not (dist and dist > 2000):
                prev = curr
                continue
            if abs(rtt_jump) < 50 and dist < 8000:
                prev = curr
                continue

            if cont_a and cont_b and cont_a != cont_b:
                label = None
                for cor in CORRIDORS:
                    if ((cor["from"]==cont_a and cor["to"]==cont_b) or
                        (cor["from"]==cont_b and cor["to"]==cont_a)):
                        label = cor["name"]
                        break
                if label:
                    segments.append({
                        "from": {"lat": prev["lat"], "lon": prev["lon"], "city": prev.get("city"), "cc": cc_a},
                        "to":   {"lat": curr["lat"], "lon": curr["lon"], "city": curr.get("city"), "cc": cc_b},
                        "km": round(dist, 1),
                        "label": label,
                        "rtt_jump": round(rtt_jump, 1)
                    })
        prev = curr
    return segments
