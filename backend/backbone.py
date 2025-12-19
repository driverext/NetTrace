"""
Synthetic backbone graph for approximate hop-to-hop routing without real cable data.

- Nodes: curated major cities/IXPs with continent code and lat/lon.
- Edges: k-nearest neighbors within same continent, plus a handful of intercontinental gateways.
- Routing: simple Dijkstra over great-circle distances.
"""
from __future__ import annotations

import heapq
import math
import zipfile
import csv
import io
import pathlib
import bisect
import hashlib
import json
import os
from typing import Dict, List, Tuple, Optional

# continent codes
CONT = {
    "NA": ["nyc","chicago","la","sf","dallas","atl","miami","seattle","toronto","vancouver","mexico_city"],
    "SA": ["sao_paulo","rio","buenos_aires","santiago","bogota","lima"],
    "EU": ["london","paris","frankfurt","amsterdam","madrid","rome","stockholm","oslo","warsaw","prague","vienna","zurich","lisbon","istanbul","moscow"],
    "AF": ["cairo","lagos","nairobi","johannesburg","capetown"],
    "AS": ["dubai","riyadh","tel_aviv","mumbai","delhi","chennai","bangalore","karachi","dhaka","colombo","singapore","kuala_lumpur","bangkok","hanoi","ho_chi_minh","hong_kong","tokyo","osaka","seoul","beijing","shanghai","taipei"],
    "OC": ["sydney","melbourne","perth","auckland"],
}

COUNTRY_CONT = {
    "US":"NA","CA":"NA","MX":"NA",
    "BR":"SA","AR":"SA","CL":"SA","CO":"SA","PE":"SA","UY":"SA","PY":"SA","VE":"SA","EC":"SA","BO":"SA","GY":"SA","SR":"SA",
    "GB":"EU","IE":"EU","FR":"EU","DE":"EU","NL":"EU","ES":"EU","IT":"EU","SE":"EU","NO":"EU","DK":"EU","PL":"EU","PT":"EU","BE":"EU",
    "CH":"EU","AT":"EU","CZ":"EU","SK":"EU","HU":"EU","RO":"EU","BG":"EU","HR":"EU","RS":"EU","BA":"EU","AL":"EU","MK":"EU","GR":"EU",
    "TR":"EU","UA":"EU","LT":"EU","LV":"EU","EE":"EU","FI":"EU","IS":"EU",
    "AE":"AS","SA":"AS","IL":"AS","JO":"AS","LB":"AS","QA":"AS","KW":"AS","BH":"AS","OM":"AS","AM":"AS","AZ":"AS","GE":"AS",
    "IN":"AS","PK":"AS","BD":"AS","LK":"AS","NP":"AS","KZ":"AS","UZ":"AS","KG":"AS","TJ":"AS","MN":"AS","CN":"AS","JP":"AS","KR":"AS",
    "TW":"AS","HK":"AS","SG":"AS","MY":"AS","TH":"AS","VN":"AS","KH":"AS","LA":"AS","MM":"AS","ID":"AS","PH":"AS",
    "AU":"OC","NZ":"OC","PG":"OC","FJ":"OC","NC":"OC","WS":"OC",
    "ZA":"AF","NG":"AF","EG":"AF","MA":"AF","DZ":"AF","TN":"AF","LY":"AF","KE":"AF","UG":"AF","RW":"AF","ET":"AF","TZ":"AF","SD":"AF",
    "SN":"AF","CI":"AF","GH":"AF","CM":"AF","AO":"AF","NA":"AF","BW":"AF","MZ":"AF","ZW":"AF","ZM":"AF","MG":"AF",
}

# node_id -> (lat, lon, continent)
NODES: Dict[str, Tuple[float, float, str]] = {
    # North America
    "nyc": (40.7128, -74.0060, "NA"),
    "washington_dc": (38.9072, -77.0369, "NA"),
    "boston": (42.3601, -71.0589, "NA"),
    "philadelphia": (39.9526, -75.1652, "NA"),
    "baltimore": (39.2904, -76.6122, "NA"),
    "chicago": (41.8781, -87.6298, "NA"),
    "detroit": (42.3314, -83.0458, "NA"),
    "minneapolis": (44.9778, -93.2650, "NA"),
    "st_louis": (38.6270, -90.1994, "NA"),
    "kansas_city": (39.0997, -94.5786, "NA"),
    "dallas": (32.7767, -96.7970, "NA"),
    "houston": (29.7604, -95.3698, "NA"),
    "austin": (30.2672, -97.7431, "NA"),
    "san_antonio": (29.4241, -98.4936, "NA"),
    "denver": (39.7392, -104.9903, "NA"),
    "phoenix": (33.4484, -112.0740, "NA"),
    "salt_lake_city": (40.7608, -111.8910, "NA"),
    "la": (34.0522, -118.2437, "NA"),
    "sf": (37.7749, -122.4194, "NA"),
    "san_diego": (32.7157, -117.1611, "NA"),
    "portland_us": (45.5152, -122.6784, "NA"),
    "seattle": (47.6062, -122.3321, "NA"),
    "las_vegas": (36.1699, -115.1398, "NA"),
    "atl": (33.7490, -84.3880, "NA"),
    "charlotte": (35.2271, -80.8431, "NA"),
    "orlando": (28.5383, -81.3792, "NA"),
    "tampa": (27.9506, -82.4572, "NA"),
    "miami": (25.7617, -80.1918, "NA"),
    "toronto": (43.6532, -79.3832, "NA"),
    "montreal": (45.5017, -73.5673, "NA"),
    "ottawa": (45.4215, -75.6972, "NA"),
    "calgary": (51.0447, -114.0719, "NA"),
    "edmonton": (53.5461, -113.4938, "NA"),
    "vancouver": (49.2827, -123.1207, "NA"),
    "winnipeg": (49.8951, -97.1384, "NA"),
    "quebec_city": (46.8139, -71.2080, "NA"),
    "halifax": (44.6488, -63.5752, "NA"),
    "mexico_city": (19.4326, -99.1332, "NA"),
    "monterrey_mx": (25.6866, -100.3161, "NA"),
    "guadalajara": (20.6597, -103.3496, "NA"),
    "tijuana": (32.5149, -117.0382, "NA"),
    "juarez": (31.6904, -106.4245, "NA"),
    "cancun": (21.1619, -86.8515, "NA"),

    # South America
    "sao_paulo": (-23.5505, -46.6333, "SA"),
    "rio": (-22.9068, -43.1729, "SA"),
    "brasilia": (-15.7939, -47.8828, "SA"),
    "belo_horizonte": (-19.9167, -43.9345, "SA"),
    "recife": (-8.0476, -34.8770, "SA"),
    "fortaleza": (-3.7319, -38.5267, "SA"),
    "curitiba": (-25.4284, -49.2733, "SA"),
    "porto_alegre": (-30.0346, -51.2177, "SA"),
    "salvador": (-12.9777, -38.5016, "SA"),
    "buenos_aires": (-34.6037, -58.3816, "SA"),
    "montevideo": (-34.9011, -56.1645, "SA"),
    "santiago": (-33.4489, -70.6693, "SA"),
    "bogota": (4.7110, -74.0721, "SA"),
    "medellin": (6.2442, -75.5812, "SA"),
    "cali": (3.4516, -76.5320, "SA"),
    "quito": (-0.1807, -78.4678, "SA"),
    "guayaquil": (-2.1709, -79.9224, "SA"),
    "lima": (-12.0464, -77.0428, "SA"),
    "asuncion": (-25.2637, -57.5759, "SA"),
    "la_paz": (-16.4897, -68.1193, "SA"),
    "santa_cruz": (-17.8146, -63.1561, "SA"),
    "maracaibo": (10.6545, -71.6533, "SA"),
    "caracas": (10.4806, -66.9036, "SA"),
    "georgetown_guy": (6.8013, -58.1551, "SA"),
    "paramaribo": (5.8520, -55.2038, "SA"),

    # Europe
    "london": (51.5074, -0.1278, "EU"),
    "dublin": (53.3498, -6.2603, "EU"),
    "belfast": (54.5973, -5.9301, "EU"),
    "glasgow": (55.8642, -4.2518, "EU"),
    "manchester": (53.4808, -2.2426, "EU"),
    "birmingham_uk": (52.4862, -1.8904, "EU"),
    "edinburgh": (55.9533, -3.1883, "EU"),
    "paris": (48.8566, 2.3522, "EU"),
    "lyon": (45.7640, 4.8357, "EU"),
    "marseille": (43.2965, 5.3698, "EU"),
    "nice": (43.7102, 7.2620, "EU"),
    "geneva": (46.2044, 6.1432, "EU"),
    "barcelona": (41.3851, 2.1734, "EU"),
    "valencia": (39.4699, -0.3763, "EU"),
    "seville": (37.3891, -5.9845, "EU"),
    "bilbao": (43.2630, -2.9350, "EU"),
    "frankfurt": (50.1109, 8.6821, "EU"),
    "munich": (48.1351, 11.5820, "EU"),
    "stuttgart": (48.7758, 9.1829, "EU"),
    "berlin": (52.5200, 13.4050, "EU"),
    "hamburg": (53.5511, 9.9937, "EU"),
    "cologne": (50.9375, 6.9603, "EU"),
    "duesseldorf": (51.2277, 6.7735, "EU"),
    "amsterdam": (52.3676, 4.9041, "EU"),
    "madrid": (40.4168, -3.7038, "EU"),
    "rome": (41.9028, 12.4964, "EU"),
    "milan": (45.4642, 9.1900, "EU"),
    "turin": (45.0703, 7.6869, "EU"),
    "naples": (40.8518, 14.2681, "EU"),
    "florence": (43.7696, 11.2558, "EU"),
    "bologna": (44.4949, 11.3426, "EU"),
    "stockholm": (59.3293, 18.0686, "EU"),
    "oslo": (59.9139, 10.7522, "EU"),
    "copenhagen": (55.6761, 12.5683, "EU"),
    "helsinki": (60.1699, 24.9384, "EU"),
    "tallinn": (59.4370, 24.7536, "EU"),
    "riga": (56.9496, 24.1052, "EU"),
    "vilnius": (54.6872, 25.2797, "EU"),
    "warsaw": (52.2297, 21.0122, "EU"),
    "krakow": (50.0647, 19.9450, "EU"),
    "gdansk": (54.3520, 18.6466, "EU"),
    "prague": (50.0755, 14.4378, "EU"),
    "vienna": (48.2082, 16.3738, "EU"),
    "budapest": (47.4979, 19.0402, "EU"),
    "belgrade": (44.7866, 20.4489, "EU"),
    "bucharest": (44.4268, 26.1025, "EU"),
    "sofia": (42.6977, 23.3219, "EU"),
    "zagreb": (45.8150, 15.9819, "EU"),
    "sarajevo": (43.8563, 18.4131, "EU"),
    "tirana": (41.3275, 19.8187, "EU"),
    "ljubljana": (46.0569, 14.5058, "EU"),
    "thessaloniki": (40.6401, 22.9444, "EU"),
    "athens": (37.9838, 23.7275, "EU"),
    "porto": (41.1579, -8.6291, "EU"),
    "lisbon": (38.7223, -9.1393, "EU"),
    "istanbul": (41.0082, 28.9784, "EU"),
    "kiev": (50.4501, 30.5234, "EU"),
    "lviv": (49.8397, 24.0297, "EU"),
    "moscow": (55.7558, 37.6176, "EU"),

    # Africa
    "cairo": (30.0444, 31.2357, "AF"),
    "alexandria": (31.2001, 29.9187, "AF"),
    "lagos": (6.5244, 3.3792, "AF"),
    "accra": (5.6037, -0.1870, "AF"),
    "abidjan": (5.6037, -3.7570, "AF"),
    "dakar": (14.7167, -17.4677, "AF"),
    "casablanca": (33.5731, -7.5898, "AF"),
    "algiers": (36.7538, 3.0588, "AF"),
    "tunis": (36.8065, 10.1815, "AF"),
    "tripoli": (32.8872, 13.1913, "AF"),
    "nairobi": (-1.2921, 36.8219, "AF"),
    "kampala": (0.3476, 32.5825, "AF"),
    "kigali": (-1.9579, 30.1127, "AF"),
    "addis_ababa": (9.0033, 38.7636, "AF"),
    "dar_es_salaam": (-6.7924, 39.2083, "AF"),
    "khartoum": (15.5007, 32.5599, "AF"),
    "johannesburg": (-26.2041, 28.0473, "AF"),
    "capetown": (-33.9249, 18.4241, "AF"),
    "durban": (-29.8587, 31.0218, "AF"),
    "gaborone": (-24.6282, 25.9231, "AF"),
    "windhoek": (-22.5609, 17.0658, "AF"),
    "lusaka": (-15.3875, 28.3228, "AF"),
    "harare": (-17.8252, 31.0335, "AF"),
    "maputo": (-25.9692, 32.5732, "AF"),
    "luanda": (-8.8390, 13.2894, "AF"),
    "douala": (4.0511, 9.7679, "AF"),
    "yaounde": (3.8480, 11.5021, "AF"),
    "bamako": (12.6392, -8.0029, "AF"),
    "antananarivo": (-18.8792, 47.5079, "AF"),

    # Asia
    "dubai": (25.2048, 55.2708, "AS"),
    "abu_dhabi": (24.4539, 54.3773, "AS"),
    "riyadh": (24.7136, 46.6753, "AS"),
    "jeddah": (21.4858, 39.1925, "AS"),
    "tel_aviv": (32.0853, 34.7818, "AS"),
    "amman": (31.9454, 35.9284, "AS"),
    "beirut": (33.8938, 35.5018, "AS"),
    "doha": (25.2854, 51.5310, "AS"),
    "kuwait_city": (29.3759, 47.9774, "AS"),
    "manama": (26.2235, 50.5876, "AS"),
    "muscat": (23.5859, 58.4059, "AS"),
    "yerevan": (40.1792, 44.4991, "AS"),
    "baku": (40.4093, 49.8671, "AS"),
    "tbilisi": (41.7151, 44.8271, "AS"),
    "mumbai": (19.0760, 72.8777, "AS"),
    "delhi": (28.7041, 77.1025, "AS"),
    "jaipur": (26.9124, 75.7873, "AS"),
    "ahmedabad": (23.0225, 72.5714, "AS"),
    "chennai": (13.0827, 80.2707, "AS"),
    "bangalore": (12.9716, 77.5946, "AS"),
    "hyderabad": (17.3850, 78.4867, "AS"),
    "pune": (18.5204, 73.8567, "AS"),
    "kolkata": (22.5726, 88.3639, "AS"),
    "karachi": (24.8607, 67.0011, "AS"),
    "lahore": (31.5204, 74.3587, "AS"),
    "islamabad": (33.6844, 73.0479, "AS"),
    "peshawar": (34.0151, 71.5249, "AS"),
    "dhaka": (23.8103, 90.4125, "AS"),
    "chittagong": (22.3569, 91.7832, "AS"),
    "colombo": (6.9271, 79.8612, "AS"),
    "male": (4.1755, 73.5093, "AS"),
    "kathmandu": (27.7172, 85.3240, "AS"),
    "tashkent": (41.2995, 69.2401, "AS"),
    "almaty": (43.2220, 76.8512, "AS"),
    "astana": (51.1605, 71.4704, "AS"),
    "ulaanbaatar": (47.8864, 106.9057, "AS"),
    "singapore": (1.3521, 103.8198, "AS"),
    "kuala_lumpur": (3.1390, 101.6869, "AS"),
    "jakarta": (-6.2088, 106.8456, "AS"),
    "surabaya": (-7.2575, 112.7521, "AS"),
    "bandung": (-6.9175, 107.6191, "AS"),
    "medan": (3.5952, 98.6722, "AS"),
    "makassar": (-5.1477, 119.4327, "AS"),
    "manila": (14.5995, 120.9842, "AS"),
    "cebu": (10.3157, 123.8854, "AS"),
    "bangkok": (13.7563, 100.5018, "AS"),
    "hanoi": (21.0278, 105.8342, "AS"),
    "ho_chi_minh": (10.8231, 106.6297, "AS"),
    "phnom_penh": (11.5564, 104.9282, "AS"),
    "vientiane": (17.9757, 102.6331, "AS"),
    "yangon": (16.8409, 96.1735, "AS"),
    "mandalay": (21.9588, 96.0891, "AS"),
    "hong_kong": (22.3193, 114.1694, "AS"),
    "shenzhen": (22.5431, 114.0579, "AS"),
    "guangzhou": (23.1291, 113.2644, "AS"),
    "fuzhou": (26.0745, 119.2965, "AS"),
    "xiamen": (24.4798, 118.0894, "AS"),
    "nanjing": (32.0603, 118.7969, "AS"),
    "hangzhou": (30.2741, 120.1551, "AS"),
    "shanghai": (31.2304, 121.4737, "AS"),
    "qingdao": (36.0671, 120.3826, "AS"),
    "beijing": (39.9042, 116.4074, "AS"),
    "tianjin": (39.3434, 117.3616, "AS"),
    "wuhan": (30.5928, 114.3055, "AS"),
    "chengdu": (30.5728, 104.0668, "AS"),
    "chongqing": (29.5630, 106.5516, "AS"),
    "xian": (34.3416, 108.9398, "AS"),
    "dalian": (38.9140, 121.6147, "AS"),
    "shenyang": (41.8057, 123.4315, "AS"),
    "osaka": (34.6937, 135.5023, "AS"),
    "tokyo": (35.6762, 139.6503, "AS"),
    "nagoya": (35.1815, 136.9066, "AS"),
    "fukuoka": (33.5904, 130.4017, "AS"),
    "sapporo": (43.0621, 141.3544, "AS"),
    "seoul": (37.5665, 126.9780, "AS"),
    "incheon": (37.4563, 126.7052, "AS"),
    "busan": (35.1796, 129.0756, "AS"),
    "daegu": (35.8714, 128.6014, "AS"),
    "taipei": (25.0330, 121.5654, "AS"),

    # Oceania
    "sydney": (-33.8688, 151.2093, "OC"),
    "melbourne": (-37.8136, 144.9631, "OC"),
    "brisbane": (-27.4698, 153.0251, "OC"),
    "adelaide": (-34.9285, 138.6007, "OC"),
    "perth": (-31.9523, 115.8613, "OC"),
    "canberra": (-35.2809, 149.1300, "OC"),
    "hobart": (-42.8821, 147.3272, "OC"),
    "auckland": (-36.8485, 174.7633, "OC"),
    "wellington": (-41.2865, 174.7762, "OC"),
    "christchurch": (-43.5321, 172.6362, "OC"),
    "suva": (-18.1248, 178.4501, "OC"),
    "port_moresby": (-9.4438, 147.1803, "OC"),
    "noumea": (-22.2558, 166.4505, "OC"),
    "apia": (-13.8507, -171.7514, "OC"),
}

def extend_with_geonames(zip_path: str = "data/cities5000.zip", min_pop: int = 50000, max_per_cont: int = 800) -> None:
    """
    Extend NODES with top cities from local GeoNames cities5000.zip.
    Skips if file missing. Caps per continent to keep graph light.
    """
    path = pathlib.Path(zip_path)
    if not path.exists():
        return
    try:
        with zipfile.ZipFile(path, "r") as zf:
            target = next((n for n in zf.namelist() if n.endswith("cities5000.txt")), None)
            if not target:
                return
            data = zf.read(target)
    except Exception:
        return
    cont_counts: Dict[str, int] = {}
    reader = csv.reader(io.StringIO(data.decode("utf-8")), delimiter="\t")
    for row in reader:
        try:
            name = row[1]; lat = float(row[4]); lon = float(row[5]); country = row[8]; pop = int(row[14])
        except Exception:
            continue
        if pop < min_pop:
            continue
        cont = COUNTRY_CONT.get(country)
        if not cont:
            continue
        if cont_counts.get(cont, 0) >= max_per_cont:
            continue
        nid = f"{name.lower().replace(' ','_')}_{country.lower()}"
        if nid in NODES:
            continue
        NODES[nid] = (lat, lon, cont)
        cont_counts[cont] = cont_counts.get(cont, 0) + 1


def haversine_km(a: Tuple[float,float], b: Tuple[float,float]) -> float:
    if a is None or b is None:
        return float("inf")
    (lat1, lon1), (lat2, lon2) = a, b
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return float("inf")
    R=6371.0
    dlat=math.radians(lat2-lat1); dlon=math.radians(lon2-lon1)
    p=(math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2)
    return 2*R*math.asin(math.sqrt(p))

def build_adj(k_near: int = 12, cap_by_cont: Optional[Dict[str, float]] = None) -> Dict[str, List[Tuple[str,float]]]:
    """
    Build a k-NN graph per node with distance caps by continent to keep it sparse and fast.
    """
    if cap_by_cont is None:
        cap_by_cont = {"NA": 2000, "EU": 1800, "AS": 2400, "AF": 2200, "SA": 2200, "OC": 2200}

    adj: Dict[str, List[Tuple[str,float]]] = {k: [] for k in NODES}
    items = [(nid, lat, lon, cont) for nid, (lat, lon, cont) in NODES.items()]
    # sort by latitude for quick windowing
    items_sorted = sorted(items, key=lambda x: x[1])
    lats = [it[1] for it in items_sorted]

    for nid, lat, lon, cont in items:
        cap = cap_by_cont.get(cont, 2400)
        lat_band = cap / 111.0  # rough deg window
        lo = bisect.bisect_left(lats, lat - lat_band)
        hi = bisect.bisect_right(lats, lat + lat_band)
        candidates = []
        for j in range(lo, hi):
            onid, olat, olon, ocont = items_sorted[j]
            if onid == nid:
                continue
            d = haversine_km((lat, lon), (olat, olon))
            if d <= cap:
                candidates.append((d, onid))
        candidates.sort(key=lambda x: x[0])
        for d, other in candidates[:k_near]:
            adj[nid].append((other, d))
            adj[other].append((nid, d))
    return adj

HUBS = {
    "nyc","chicago","la","sf","dallas","atl","miami","seattle","toronto","vancouver",
    "london","paris","frankfurt","amsterdam","madrid","rome","singapore","hong_kong",
    "tokyo","osaka","seoul","beijing","shanghai","dubai","mumbai","delhi","sydney"
}

def edge_cost(u: str, v: str, dist: float) -> float:
    """
    Policy-ish weighting: penalize continent changes, reward hubs, discourage very long jumps, add tiny jitter.
    """
    cu = NODES[u][2]; cv = NODES[v][2]
    cost = dist
    if cu != cv:
        cost *= 2.5
    if u in HUBS or v in HUBS:
        cost *= 0.9
    if u in HUBS and v in HUBS:
        cost *= 0.85
    if dist > 4000:
        cost *= 1.15
    h = int(hashlib.sha1(f"{u}-{v}".encode()).hexdigest(), 16) % 1000
    cost *= (1 + (h/1000.0)*0.02)
    return cost

try:
    extend_with_geonames()
except Exception:
     pass
ADJ = build_adj()

# --- Submarine cables graph (polyline-based) ---
cable_nodes: List[Tuple[float, float]] = []
cable_adj: Dict[int, List[Tuple[int, float]]] = {}

def _resolve_data_path(path: str) -> pathlib.Path:
    p = pathlib.Path(path)
    if p.exists():
        return p
    return pathlib.Path(__file__).resolve().parent.parent / path

def load_cables(path: str = "data/cables-geo.json") -> None:
    """
    Load cable polylines, downsample each, and build a graph along the vertices.
    """
    global cable_nodes, cable_adj
    f = _resolve_data_path(path)
    if not f.exists():
        cable_nodes = []
        cable_adj = {}
        return
    try:
        data = json.loads(f.read_text())
    except Exception:
        cable_nodes = []
        cable_adj = {}
        return

    coords_index: Dict[Tuple[float,float], int] = {}
    cable_nodes = []
    cable_adj = {}

    def to_float(v):
        try:
            return float(v)
        except Exception:
            return None

    def get_idx(lat: float, lon: float) -> int:
        key = (lat, lon)
        if key in coords_index:
            return coords_index[key]
        idx = len(cable_nodes)
        coords_index[key] = idx
        cable_nodes.append(key)
        cable_adj[idx] = []
        return idx

    def downsample(points, max_pts=200):
        pts = []
        for lon, lat in points:
            lon = to_float(lon); lat = to_float(lat)
            if None in (lat, lon):
                continue
            pts.append((lat, lon))
        if len(pts) <= 1:
            return []
        if len(pts) <= max_pts:
            return pts
        stride = max(1, len(pts)//max_pts)
        return [pts[i] for i in range(0, len(pts), stride)] + [pts[-1]]

    feats = data.get("features") or []
    for feat in feats:
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        lines = []
        if gtype == "LineString":
            lines = [coords]
        elif gtype == "MultiLineString":
            lines = coords
        for line in lines:
            ds = downsample(line, max_pts=200)
            if len(ds) < 2:
                continue
            prev_idx = None
            for lat, lon in ds:
                idx = get_idx(lat, lon)
                if prev_idx is not None and idx != prev_idx:
                    d = haversine_km(cable_nodes[prev_idx], cable_nodes[idx])
                    if math.isfinite(d):
                        cable_adj[prev_idx].append((idx, d))
                        cable_adj[idx].append((prev_idx, d))
                prev_idx = idx

def nearest_cable_node(lat: float, lon: float, max_km: float = 500.0) -> Optional[int]:
    if not cable_nodes:
        return None
    best = None
    for i, (clat, clon) in enumerate(cable_nodes):
        d = haversine_km((lat, lon), (clat, clon))
        if best is None or d < best[1]:
            best = (i, d)
    if best and best[1] <= max_km:
        return best[0]
    return None

def astar_cable(src: int, dst: int) -> List[int]:
    if src == dst:
        return [src]
    h = lambda idx: haversine_km(cable_nodes[idx], cable_nodes[dst]) * 0.9
    open_set = [(h(src), 0.0, src)]
    came_from: Dict[int, Optional[int]] = {src: None}
    g_score = {src: 0.0}
    closed = set()
    while open_set:
        _, g, current = heapq.heappop(open_set)
        if current in closed:
            continue
        if current == dst:
            break
        closed.add(current)
        for neighbor, w in cable_adj.get(current, []):
            tentative = g + w
            if tentative < g_score.get(neighbor, float("inf")):
                came_from[neighbor] = current
                g_score[neighbor] = tentative
                f = tentative + h(neighbor)
                heapq.heappush(open_set, (f, tentative, neighbor))
    if dst not in came_from:
        return []
    path = []
    cur: Optional[int] = dst
    while cur is not None:
        path.append(cur)
        cur = came_from.get(cur)
    return list(reversed(path))

def route_submarine(lat1: float, lon1: float, lat2: float, lon2: float) -> Optional[List[Tuple[float,float]]]:
    a = nearest_cable_node(lat1, lon1)
    b = nearest_cable_node(lat2, lon2)
    if a is None or b is None:
        return None
    ids = astar_cable(a, b)
    if not ids:
        return None
    coords = [cable_nodes[i] for i in ids]
    return [(lat1, lon1)] + coords + [(lat2, lon2)]

load_cables()

def snap_to_backbone(lat: float, lon: float, max_km: float = 300.0) -> Optional[str]:
    """
    Find nearest backbone node within max_km.
    """
    best = None
    for nid, (nlat, nlon, _) in NODES.items():
        d = haversine_km((lat, lon), (nlat, nlon))
        if best is None or d < best[1]:
            best = (nid, d)
    if best and best[1] <= max_km:
        return best[0]
    return None

def astar_path(src: str, dst: str, adj: Optional[Dict[str, List[Tuple[str,float]]]] = None) -> List[str]:
    """
    Simple A* over the backbone graph (or provided adj).
    """
    graph = adj if adj is not None else ADJ
    if src == dst:
        return [src]
    h = lambda a: haversine_km(NODES[a][:2], NODES[dst][:2]) * 0.9
    open_set = [(h(src), 0.0, src)]
    came_from: Dict[str, Optional[str]] = {src: None}
    g_score = {src: 0.0}
    closed = set()
    while open_set:
        _, g, current = heapq.heappop(open_set)
        if current in closed:
            continue
        if current == dst:
            break
        closed.add(current)
        for neighbor, w in graph.get(current, []):
            tentative = g + w
            if tentative < g_score.get(neighbor, float("inf")):
                came_from[neighbor] = current
                g_score[neighbor] = tentative
                f = tentative + h(neighbor)
                heapq.heappush(open_set, (f, tentative, neighbor))
    if dst not in came_from:
        return []
    path = []
    cur: Optional[str] = dst
    while cur is not None:
        path.append(cur)
        cur = came_from.get(cur)
    return list(reversed(path))

def path_coords(path_ids: List[str]) -> List[Tuple[float,float]]:
    coords = []
    for nid in path_ids:
        lat, lon, _ = NODES[nid]
        coords.append((lat, lon))
    return coords

def route_between(lat1: float, lon1: float, lat2: float, lon2: float) -> Optional[Tuple[List[Tuple[float,float]], float, str, str, Tuple[str,str]]]:
    """
    Snap endpoints to backbone and return path coordinates + metadata.
    """
    a = snap_to_backbone(lat1, lon1)
    b = snap_to_backbone(lat2, lon2)
    if not a or not b:
        return None
    ids = astar_path(a, b)
    if not ids:
        return None
    coords = path_coords(ids)
    total = 0.0
    for i in range(len(coords)-1):
        total += haversine_km(coords[i], coords[i+1])
    return coords, total, a, b, (a, b)

def node_coord(node_id: str) -> Optional[Tuple[float,float]]:
    if node_id in NODES:
        lat, lon, _ = NODES[node_id]
        return (lat, lon)
    return None
