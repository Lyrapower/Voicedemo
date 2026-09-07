#!/usr/bin/env python3
"""Supervisor-initiated isolation probe. --network none. No cc tools."""
from __future__ import annotations
import os, socket, sys

def try_connect(host, port, timeout=1.5):
    try:
        s = socket.create_connection((host, port), timeout)
        s.close()
        return "OPEN"
    except Exception as e:
        return type(e).__name__

def extra_routed_ifaces():
    extra = []
    if os.path.exists("/proc/net/route"):
        for i, line in enumerate(open("/proc/net/route", encoding="ascii")):
            if i == 0:
                continue
            cols = line.split()
            if cols and cols[0] not in {"lo", "lo0"}:
                extra.append(cols[0])
    if os.path.exists("/proc/net/if_inet6"):
        for line in open("/proc/net/if_inet6", encoding="ascii"):
            parts = line.split()
            if len(parts) >= 6 and parts[5] not in {"lo", "lo0"}:
                extra.append(parts[5])
    return sorted(set(extra))

def main():
    nets = []
    sys_net = "/sys/class/net"
    if os.path.isdir(sys_net):
        nets = sorted(os.listdir(sys_net))
    print("nets", ",".join(nets))
    fail = 0
    targets = os.environ.get("ISOLATE_TARGETS", "")
    for item in [t for t in targets.split(",") if t.strip()]:
        host, port_s = item.rsplit(":", 1)
        host = host.strip("[]")
        port = int(port_s)
        st = try_connect(host, port)
        print(f"connect {host}:{port} {st}")
        if st == "OPEN":
            fail = 1
    extra = extra_routed_ifaces()
    print("extra_if", ",".join(extra) if extra else "-")
    if extra:
        fail = 1
    return fail

if __name__ == "__main__":
    raise SystemExit(main())
