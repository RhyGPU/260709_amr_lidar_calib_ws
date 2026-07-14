#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Client for the SEER LiDAR UDP relay.

Authenticates with id/pw, receives published scan frames over UDP, keeps the
lease alive with periodic pings, and visualizes every device in the base_link
frame (or prints stats with --no-gui).

    python -m amr_lidar.relay_client <server-ip> --port 6900 --id amr --pw lidar2026
    python -m amr_lidar.relay_client <server-ip> --no-gui
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import threading
import time

MAGIC = b"LDR1"
DEVICE_COLORS = ["#33c7ee", "#f5a83f", "#7ef07e", "#ff6b9d", "#b48bff", "#ffd34d"]


def decode_frame(buf: bytes):
    if buf[:4] != MAGIC:
        return None
    seq, t_ms, ndev = struct.unpack_from("<IIB", buf, 4)
    off = 13
    devices = []
    for _ in range(ndev):
        nlen = buf[off]; off += 1
        name = buf[off:off + nlen].decode(errors="replace"); off += nlen
        npts = struct.unpack_from("<H", buf, off)[0]; off += 2
        vals = struct.unpack_from("<%df" % (npts * 2), buf, off); off += npts * 8
        devices.append((name, [(vals[i], vals[i + 1]) for i in range(0, len(vals), 2)]))
    return seq, t_ms, devices


class RelayClient:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.server = (args.server, args.port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(3)
        self.latest: dict[str, list] = {}
        self.lock = threading.Lock()
        self.seq = 0
        self.last_rx = 0.0
        self.lease = 10.0
        self.running = True

    def authenticate(self) -> None:
        pkt = json.dumps({"cmd": "auth", "id": self.args.id, "pw": self.args.pw}).encode()
        for attempt in range(3):
            self.sock.sendto(pkt, self.server)
            try:
                data, _ = self.sock.recvfrom(2048)
            except socket.timeout:
                if attempt < 2:
                    print(f"No reply from {self.server[0]}:{self.server[1]}, retrying...")
                    continue
                raise SystemExit(f"No response from relay at {self.server[0]}:{self.server[1]} "
                                 f"- check the server is running and the IP/port/firewall.")
            reply = json.loads(data.decode())
            status = reply.get("status")
            if status == "ok":
                self.lease = reply.get("lease", 10)
                print(f"Authenticated. Server rate {reply.get('hz')} Hz, lease {self.lease}s.")
                return
            if status == "denied":
                raise SystemExit("Auth denied - wrong id/pw.")
        raise SystemExit("Could not authenticate.")

    def _keepalive_loop(self) -> None:
        while self.running:
            time.sleep(max(2, self.lease / 3))
            try:
                self.sock.sendto(json.dumps({"cmd": "ping"}).encode(), self.server)
            except OSError:
                pass

    def _recv_loop(self) -> None:
        while self.running:
            try:
                data, _ = self.sock.recvfrom(200000)
            except socket.timeout:
                continue
            except OSError:
                break
            if data[:4] != MAGIC:
                continue
            frame = decode_frame(data)
            if not frame:
                continue
            seq, _t, devices = frame
            with self.lock:
                self.latest = {n: p for n, p in devices}
                self.seq = seq
                self.last_rx = time.monotonic()

    def start(self) -> None:
        self.authenticate()
        threading.Thread(target=self._recv_loop, daemon=True).start()
        threading.Thread(target=self._keepalive_loop, daemon=True).start()

    def stop(self) -> None:
        self.running = False
        try:
            self.sock.sendto(json.dumps({"cmd": "bye"}).encode(), self.server)
        except OSError:
            pass


def run_gui(client: RelayClient) -> None:
    import numpy as np
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(9, 9))
    fig.canvas.manager.set_window_title(f"AMR LiDAR (UDP) - {client.args.server}:{client.args.port}")
    ax.set_aspect("equal")
    ax.grid(True, color="#1c2634", linewidth=0.6)
    ax.set_facecolor("#0a0e15")
    fig.patch.set_facecolor("#0a0e15")
    ax.set_xlabel("x (m) - forward", color="#8aa0b6")
    ax.set_ylabel("y (m)", color="#8aa0b6")
    ax.plot(0, 0, "o", color="#eef3f9", ms=6, zorder=5)
    ax.annotate("", xy=(0.6, 0), xytext=(0, 0),
                arrowprops=dict(arrowstyle="->", color="#e5484d", lw=2), zorder=5)
    scatters: dict[str, object] = {}

    def update(_frame):
        with client.lock:
            latest = dict(client.latest)
            seq = client.seq
            age = time.monotonic() - client.last_rx if client.last_rx else 99
        xs_all, ys_all = [], []
        for i, (name, pts) in enumerate(latest.items()):
            if name not in scatters:
                scatters[name] = ax.scatter([], [], s=4,
                                            c=DEVICE_COLORS[i % len(DEVICE_COLORS)], label=name)
                ax.legend(loc="upper right", facecolor="#0f151e", edgecolor="#1e2836",
                          labelcolor="#dbe4ef", fontsize=9)
            if pts:
                arr = np.array(pts)
                scatters[name].set_offsets(arr)
                xs_all.append(arr[:, 0]); ys_all.append(arr[:, 1])
            else:
                scatters[name].set_offsets(np.empty((0, 2)))
        if xs_all:
            allpts = np.abs(np.concatenate([np.concatenate(xs_all), np.concatenate(ys_all)]))
            m = max(2.0, float(np.percentile(allpts, 98)) * 1.15)
            ax.set_xlim(-m, m); ax.set_ylim(-m, m)
        state = "LIVE" if age < 1.5 else f"STALE {age:.1f}s"
        n = sum(len(p) for p in latest.values())
        ax.set_title(f"AMR LiDAR via UDP relay   [{state}]   {len(latest)} dev - {n} pts - frame {seq}",
                     color="#dbe4ef", fontsize=11)
        return list(scatters.values())

    ani = FuncAnimation(fig, update, interval=100, blit=False, cache_frame_data=False)
    try:
        plt.show()
    finally:
        client.stop()


def run_headless(client: RelayClient) -> None:
    try:
        while True:
            time.sleep(1)
            with client.lock:
                age = time.monotonic() - client.last_rx if client.last_rx else 99
                n = sum(len(p) for p in client.latest.values())
                seq = client.seq
            print(f"frame {seq}  {n} pts  age {age:.2f}s  " + ("LIVE" if age < 1.5 else "STALE"))
    except KeyboardInterrupt:
        client.stop()


def main() -> None:
    p = argparse.ArgumentParser(description="Subscribe to the SEER LiDAR UDP relay")
    p.add_argument("server", help="relay host IP (the PC running relay_server)")
    p.add_argument("--port", type=int, default=6900)
    p.add_argument("--id", default="amr")
    p.add_argument("--pw", default="lidar2026")
    p.add_argument("--no-gui", action="store_true", help="print stats instead of plotting")
    args = p.parse_args()
    client = RelayClient(args)
    client.start()
    run_headless(client) if args.no_gui else run_gui(client)


if __name__ == "__main__":
    main()
