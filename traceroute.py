import platform
import re
import socket
import subprocess
import time
from typing import Dict, Generator, Optional

from scapy.all import IP, ICMP, TCP, UDP, conf, sr1

conf.verb = 0  # Silence Scapy console noise


def resolve_target(target: str) -> str:
    return socket.gethostbyname(target)


def _send_probe(packet, timeout: float) -> Optional[object]:
    start = time.time()
    ans = sr1(packet, timeout=timeout)
    if ans:
        ans.rtt_ms = (time.time() - start) * 1000.0
    return ans


def _windows_tracert(destination_ip: str, max_hops: int = 30) -> Generator[Dict, None, None]:
    """
    Fallback for Windows when raw sockets/Scapy are blocked. Streams parsed tracert output.
    """
    cmd = ["tracert", "-d", "-h", str(max_hops), destination_ip]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="ignore")

    hop_line = re.compile(r"^\s*(\d+)\s+(.+)$")
    for line in proc.stdout:
        m = hop_line.match(line)
        if not m:
            continue
        hop_num = int(m.group(1))
        rest = m.group(2).strip()

        if "Request timed out" in rest or rest.startswith("*"):
            yield {"hop": hop_num, "method": "TRACERT", "reached": False, "timeout": True, "ip": "timeout", "rtt": None}
            continue

        parts = rest.split()
        ip = parts[-1]
        rtts = [p for p in parts if p.endswith("ms")]
        rtt_ms = None
        if rtts:
            try:
                rtt_ms = float(rtts[0].replace("<", "").replace("ms", ""))
            except ValueError:
                rtt_ms = None

        yield {
            "hop": hop_num,
            "method": "TRACERT",
            "reached": ip == destination_ip,
            "timeout": False,
            "ip": ip,
            "rtt": rtt_ms,
        }


def traceroute_generator(destination_ip: str, max_hops: int = 30, timeout: float = 1.5, dport: int = 80, mode: str = "auto") -> Generator[Dict, None, None]:
    """
    Attempt TCP-based traceroute with ICMP + UDP fallbacks (or user-selected mode).
    Yields hop dictionaries. Stops a few hops after first reach to mirror traceroute.
    Falls back to system tracert on Windows if raw sockets are blocked.
    """
    try:
        yield from _scapy_traceroute(destination_ip, max_hops=max_hops, timeout=timeout, dport=dport, mode=mode)
    except (PermissionError, OSError) as exc:
        # Common on Windows without admin/Npcap.
        if platform.system().lower().startswith("win"):
            yield from _windows_tracert(destination_ip, max_hops=max_hops)
        else:
            raise exc


def _scapy_traceroute(destination_ip: str, max_hops: int, timeout: float, dport: int, mode: str) -> Generator[Dict, None, None]:
    reached = False
    post_reach = 0
    mode = mode.lower()

    for ttl in range(1, max_hops + 1):
        probes = []
        if mode in ("auto", "tcp"):
            probes.append(("TCP", IP(dst=destination_ip, ttl=ttl) / TCP(dport=dport, flags="S")))
        if mode in ("auto", "icmp"):
            probes.append(("ICMP", IP(dst=destination_ip, ttl=ttl) / ICMP()))
        if mode in ("auto", "udp"):
            probes.append(("UDP", IP(dst=destination_ip, ttl=ttl) / UDP(dport=33434)))

        ans = None
        method = "TCP"
        for probe_method, pkt in probes:
            ans = _send_probe(pkt, timeout)
            method = probe_method
            if ans:
                break

        hop_data: Dict[str, object] = {
            "hop": ttl,
            "method": method,
            "reached": False,
            "timeout": ans is None,
        }

        if ans:
            hop_data["ip"] = ans.src
            hop_data["rtt"] = round(ans.rtt_ms, 2) if hasattr(ans, "rtt_ms") else None

            if ans.haslayer(TCP) and ans.getlayer(TCP).flags == 0x12:
                hop_data["reached"] = True
                reached = True
            elif ans.haslayer(ICMP) and ans.getlayer(ICMP).type == 0:
                hop_data["reached"] = True
                reached = True
        else:
            hop_data["ip"] = "timeout"
            hop_data["rtt"] = None

        yield hop_data

        if reached:
            post_reach += 1
            if post_reach >= 5:
                break
