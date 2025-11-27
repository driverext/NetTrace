import ipaddress
import socket
from functools import lru_cache
from typing import Dict, Optional

import requests
from dns import reversename, resolver
from ipwhois import IPWhois


def is_private_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


def _reverse_dns(ip: str) -> Optional[str]:
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        try:
            reversed_dns = reversename.from_address(ip)
            return str(resolver.resolve(reversed_dns, "PTR")[0])
        except Exception:
            return None


@lru_cache(maxsize=512)
def _whois_lookup(ip: str) -> Dict[str, Optional[str]]:
    try:
        w = IPWhois(ip)
        data = w.lookup_rdap(depth=1)
        return {
            "asn": data.get("asn"),
            "org": data.get("network", {}).get("name") or data.get("asn_description"),
        }
    except Exception:
        return {"asn": None, "org": None}


@lru_cache(maxsize=1024)
def _geo_lookup(ip: str) -> Dict[str, Optional[str]]:
    # Provider 1: ipapi.co
    try:
        resp = requests.get(f"https://ipapi.co/{ip}/json/", timeout=2.0)
        if resp.ok:
            data = resp.json()
            if data.get("latitude") and data.get("longitude"):
                return {
                    "city": data.get("city"),
                    "region": data.get("region"),
                    "country": data.get("country_name"),
                    "country_code": data.get("country_code"),
                    "latitude": data.get("latitude"),
                    "longitude": data.get("longitude"),
                }
    except Exception:
        pass

    # Provider 2: ip-api.com (HTTP, free-tier)
    try:
        resp = requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,regionName,city,lat,lon", timeout=2.0)
        data = resp.json()
        if data.get("status") == "success":
            return {
                "city": data.get("city"),
                "region": data.get("regionName"),
                "country": data.get("country"),
                "country_code": data.get("countryCode"),
                "latitude": data.get("lat"),
                "longitude": data.get("lon"),
            }
    except Exception:
        pass

    return {"city": None, "region": None, "country": None, "country_code": None, "latitude": None, "longitude": None}


def geolocate_ip(ip: str, user_lat: Optional[float] = None, user_lon: Optional[float] = None) -> Dict:
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return {
            "ip": ip,
            "hostname": None,
            "city": None,
            "region": None,
            "country": None,
            "country_code": None,
            "latitude": None,
            "longitude": None,
            "asn": None,
            "org": None,
        }

    if is_private_ip(ip):
        return {
            "ip": ip,
            "hostname": None,
            "city": "Private Network",
            "region": None,
            "country": "Local",
            "country_code": None,
            "latitude": user_lat,
            "longitude": user_lon,
            "asn": None,
            "org": "Local Device",
        }

    whois = _whois_lookup(ip)
    geo = _geo_lookup(ip)
    hostname = _reverse_dns(ip)

    return {
        "ip": ip,
        "hostname": hostname,
        "city": geo.get("city"),
        "region": geo.get("region"),
        "country": geo.get("country"),
        "country_code": geo.get("country_code"),
        "latitude": geo.get("latitude"),
        "longitude": geo.get("longitude"),
        "asn": whois.get("asn"),
        "org": whois.get("org"),
    }
