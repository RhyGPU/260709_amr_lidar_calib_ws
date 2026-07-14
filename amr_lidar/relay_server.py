#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SEER LiDAR -> UDP publishing relay.

Holds one SEER API connection, transforms each scan into the robot base_link
frame, and publishes one binary datagram per frame to authenticated subscribers.

    python -m amr_lidar.relay_server --seer 192.168.44.82 --port 6900 \
        --id amr --pw lidar2026 --hz 10

See PROTOCOL.md for the wire format.
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import threading
import time

from .seer_client import SeerLaserClient, beams_to_base, STATUS_PORT

MAGIC = b"LDR1"


def encode_frame(seq: int, devices: list[tuple[str, list[tuple[float, float]]]]) -> bytes:
    parts = [MAGIC, struct.pack("<IIB", seq & 0xFFFFFFFF,
                                int(time.monotonic() * 1000) & 0xFFFFFFFF, len(devices))]
    for name, pts in devices:
        name_bytes = name.encode()[:255]
        n = min(len(pts), 65535)
        parts.append(struct.pack("<B", len(name_bytes)) + name_bytes)
        parts.append(struct.pack("<H", n))
        flat = [c for xy in pts[:n] for c in xy]
        parts.append(struct.pack("<%df" % (n * 2), *flat))
    return b"".join(parts)


class LidarRelay:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.subscribers: dict[tuple, float] = {}   # addr -> lease expiry (monotonic)
        self.lock = threading.Lock()
        self.seq = 0
        self.frames = 0
        self.running = True

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Windows: prevent a sendto() to a vanished client from raising
        # WSAECONNRESET (10054) on the next recvfrom(). No-op elsewhere.
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            try:
                self.sock.ioctl(socket.SIO_UDP_CONNRESET, 0)
            except OSError:
                pass
        self.sock.bind(("0.0.0.0", args.port))

    def _reply(self, addr, obj) -> None:
        try:
            self.sock.sendto(json.dumps(obj).encode(), addr)
        except OSError:
            pass

    def control_loop(self) -> None:
        self.sock.settimeout(1.0)
        while self.running:
            try:
                data, addr = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            except ConnectionResetError:
                continue
            except OSError:
                if not self.running:
                    break
                continue
            try:
                msg = json.loads(data.decode())
            except Exception:
                continue

            cmd = msg.get("cmd")
            if cmd == "auth":
                if msg.get("id") == self.args.id and msg.get("pw") == self.args.pw:
                    with self.lock:
                        self.subscribers[addr] = time.monotonic() + self.args.lease
                    self._reply(addr, {"status": "ok", "hz": self.args.hz, "lease": self.args.lease})
                    print(f"[auth] {addr[0]}:{addr[1]} subscribed ({len(self.subscribers)} total)")
                else:
                    self._reply(addr, {"status": "denied"})
                    print(f"[auth] {addr[0]}:{addr[1]} DENIED")
            elif cmd == "ping":
                with self.lock:
                    if addr in self.subscribers:
                        self.subscribers[addr] = time.monotonic() + self.args.lease
                    else:
                        self._reply(addr, {"status": "reauth"})
            elif cmd == "bye":
                with self.lock:
                    self.subscribers.pop(addr, None)
                print(f"[bye ] {addr[0]}:{addr[1]} left")

    def publish_loop(self) -> None:
        client = SeerLaserClient(self.args.seer)
        period = 1.0 / self.args.hz
        while self.running:
            start = time.monotonic()
            try:
                resp = client.get_lasers()
                devices = [(L.get("device_info", {}).get("device_name", f"laser{i}"),
                            beams_to_base(L)) for i, L in enumerate(resp.get("lasers", []))]
                self.seq += 1
                packet = encode_frame(self.seq, devices)
                now = time.monotonic()
                with self.lock:
                    for addr in [a for a, exp in self.subscribers.items() if exp < now]:
                        del self.subscribers[addr]
                        print(f"[lease] {addr[0]}:{addr[1]} expired")
                    targets = list(self.subscribers.keys())
                for addr in targets:
                    try:
                        self.sock.sendto(packet, addr)
                    except OSError:
                        pass
                self.frames += 1
                if self.frames % 50 == 0:
                    npts = sum(len(p) for _, p in devices)
                    print(f"[pub ] frame {self.seq}: {len(devices)} dev, {npts} pts, "
                          f"{len(targets)} subs, {len(packet)} B")
            except Exception as exc:  # noqa: BLE001
                print(f"[seer] fetch failed: {exc}; retrying")
                time.sleep(0.5)
            elapsed = time.monotonic() - start
            if elapsed < period:
                time.sleep(period - elapsed)

    def run(self) -> None:
        a = self.args
        print("SEER LiDAR UDP relay")
        print(f"  source (SEER API): {a.seer}:{STATUS_PORT}")
        print(f"  publishing UDP on: 0.0.0.0:{a.port}  (all of this PC's IPs)")
        print(f"  credentials: id='{a.id}'  pw='{a.pw}'   rate={a.hz} Hz  lease={a.lease}s")
        print(f"  client: python -m amr_lidar.relay_client <this-pc-ip> "
              f"--port {a.port} --id {a.id} --pw {a.pw}")
        threading.Thread(target=self.control_loop, daemon=True).start()
        try:
            self.publish_loop()
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            self.sock.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Publish SEER LiDAR over UDP to authed clients")
    p.add_argument("--seer", default="192.168.44.82", help="AMR / SEER API IP")
    p.add_argument("--port", type=int, default=6900, help="UDP publish port")
    p.add_argument("--id", default="amr", help="subscriber id")
    p.add_argument("--pw", default="lidar2026", help="subscriber password")
    p.add_argument("--hz", type=float, default=10.0, help="publish rate (<=10)")
    p.add_argument("--lease", type=float, default=10.0, help="subscription TTL seconds")
    LidarRelay(p.parse_args()).run()


if __name__ == "__main__":
    main()
