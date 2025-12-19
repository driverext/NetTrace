import socket, platform, subprocess, os, re
from time import time, sleep
from scapy.all import IP, TCP, ICMP, UDP, sr1, conf

MAX_HOPS = 30
TIMEOUT = 2
DEST_PORT = 80
UDP_PROBE_PORT = 33434

def warmup_ping(host):
    try:
        system = platform.system().lower()
        if system == "windows":
            subprocess.run(["ping", "-n", "1", host], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["ping", "-c", "1", host], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def traceroute_generator(host, protocol="tcp", max_hops=MAX_HOPS, probes_per_ttl=2, dest_port=DEST_PORT):
    system = platform.system().lower()

    # Windows: use tracert -4 -d and average 3 RTTs
    if system == "windows":
        print(f"[info] Using Windows tracert fallback for host: {host}")
        warmup_ping(host)
        try:
            proc = subprocess.Popen(
                [
                    "tracert",
                    "-4",
                    "-d",
                    "-h", str(max_hops),
                    "-w", str(int(TIMEOUT * 1000)),
                    host,
                ],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, universal_newlines=True,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            hop_pattern = re.compile(r"^\s*(\d+)\s+(?:(?:\d+\s*ms\s+){0,3})?(?P<ip>(\d{1,3}\.){3}\d{1,3}|[0-9a-fA-F:]+)?")
            for line in proc.stdout:
                line=line.strip()
                if not line or "Tracing route" in line or "over a maximum" in line or "Trace complete" in line:
                    continue
                match = hop_pattern.search(line)
                ip, rtt = None, None
                if match:
                    ip = match.group("ip")
                    rtts = [float(x) for x in re.findall(r"(\d+)\s*ms", line)]
                    if rtts: rtt = round(sum(rtts)/len(rtts), 2)
                yield {"ip": ip, "rtt": rtt}
            return
        except Exception as e:
            print("[error] tracert failed:", e)
            yield {"ip": None, "rtt": None}
            return

    # Non-Windows: Scapy
    print(f"\nTracing route to {host} using Scapy ({protocol.upper()}) ...")
    try:
        target_ip = socket.gethostbyname(host)
    except socket.gaierror:
        print("❌ Failed to resolve hostname.")
        yield None
        return

    conf.verb = 0
    warmup_ping(target_ip)

    destination_hit = False
    destination_hit_ttl = None
    consecutive_timeouts = 0
    repeating_ip = None
    repeat_count = 0

    for ttl in range(1, max_hops + 1):
        rtts, hop_ip = [], None
        reply = None

        for _ in range(probes_per_ttl):
            if protocol == "tcp":
                pkt = IP(dst=target_ip, ttl=ttl) / TCP(dport=dest_port, flags="S")
            elif protocol == "icmp":
                pkt = IP(dst=target_ip, ttl=ttl) / ICMP()
            elif protocol == "udp":
                pkt = IP(dst=target_ip, ttl=ttl) / UDP(dport=UDP_PROBE_PORT)
            else:
                pkt = IP(dst=target_ip, ttl=ttl) / TCP(dport=dest_port, flags="S")

            start_time = time()
            reply = sr1(pkt, timeout=TIMEOUT, verbose=0)
            rtt_ms = round((time() - start_time) * 1000, 2)

            # fallback to ICMP for early silent hops
            if not reply and ttl <= 3:
                icmp_pkt = IP(dst=target_ip, ttl=ttl) / ICMP()
                start_time = time()
                reply = sr1(icmp_pkt, timeout=TIMEOUT, verbose=0)
                if reply:
                    rtt_ms = round((time() - start_time) * 1000, 2)

            if reply and reply.haslayer(IP):
                hop_ip = reply.src
                rtts.append(rtt_ms)

        if not rtts and hop_ip is None:
            consecutive_timeouts += 1
            yield {"ip": None, "rtt": None}
        else:
            avg_rtt = round(sum(rtts)/len(rtts), 2) if rtts else None
            yield {"ip": hop_ip, "rtt": avg_rtt}
            consecutive_timeouts = 0

            if reply:
                if protocol == "tcp" and reply.haslayer(TCP) and reply.getlayer(TCP).flags == 0x12:
                    destination_hit = True; destination_hit_ttl = ttl
                elif protocol == "udp" and reply.haslayer(ICMP) and reply.getlayer(ICMP).type == 3:
                    destination_hit = True; destination_hit_ttl = ttl

            if hop_ip and hop_ip == repeating_ip:
                repeat_count += 1
            else:
                repeat_count = 0
                repeating_ip = hop_ip

        if destination_hit and ttl >= (destination_hit_ttl or 0) + 1: break
        if repeat_count >= 2: break
        if consecutive_timeouts >= 3 and destination_hit: break

        sleep(0.05)
