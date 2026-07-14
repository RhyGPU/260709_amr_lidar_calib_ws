#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live 2D LiDAR viewer reading directly from the SEER API.

    python -m amr_lidar.viewer                 # default 192.168.44.82 (WiFi)
    python -m amr_lidar.viewer 192.168.192.5   # wired robot LAN
    python -m amr_lidar.viewer 192.168.44.82 --hz 8 --range 10
"""
from __future__ import annotations

import argparse
import threading
import time

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

from .seer_client import SeerLaserClient, beams_to_base, STATUS_PORT

DEVICE_COLORS = ["#33c7ee", "#f5a83f", "#7ef07e", "#ff6b9d", "#b48bff", "#ffd34d"]


class ScanPoller(threading.Thread):
    """Background thread holding the latest SEER 1009 response."""

    def __init__(self, client: SeerLaserClient, hz: float):
        super().__init__(daemon=True)
        self.client = client
        self.period = 1.0 / hz
        self.latest: dict | None = None
        self.error: str | None = None
        self.frames = 0
        self.last_ok = 0.0
        self._running = True

    def run(self) -> None:
        while self._running:
            start = time.monotonic()
            try:
                self.latest = self.client.get_lasers()
                self.error = None
                self.frames += 1
                self.last_ok = time.monotonic()
            except Exception as exc:  # noqa: BLE001
                self.error = str(exc)
                time.sleep(0.5)
            elapsed = time.monotonic() - start
            if elapsed < self.period:
                time.sleep(self.period - elapsed)

    def stop(self) -> None:
        self._running = False


def main() -> None:
    parser = argparse.ArgumentParser(description="Live SEER-API 2D LiDAR viewer")
    parser.add_argument("ip", nargs="?", default="192.168.44.82", help="robot IP")
    parser.add_argument("--hz", type=float, default=10.0, help="poll rate (<=10)")
    parser.add_argument("--range", type=float, default=0.0,
                        help="axis half-extent in m (0 = auto-fit)")
    args = parser.parse_args()

    print(f"Connecting to SEER API at {args.ip}:{STATUS_PORT} ...")
    client = SeerLaserClient(args.ip)
    first = client.get_lasers()
    names = [dev.get("device_info", {}).get("device_name", f"laser{i}")
             for i, dev in enumerate(first.get("lasers", []))]
    print(f"Connected. Laser devices: {names}")

    poller = ScanPoller(client, args.hz)
    poller.latest = first
    poller.start()

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(9, 9))
    fig.canvas.manager.set_window_title(f"SEER 2D LiDAR - {args.ip}")
    ax.set_aspect("equal")
    ax.grid(True, color="#1c2634", linewidth=0.6)
    ax.set_facecolor("#0a0e15")
    fig.patch.set_facecolor("#0a0e15")
    ax.set_xlabel("x (m)  -  base_link forward", color="#8aa0b6")
    ax.set_ylabel("y (m)", color="#8aa0b6")
    ax.plot(0, 0, marker="o", color="#eef3f9", markersize=6, zorder=5)
    ax.annotate("", xy=(0.6, 0), xytext=(0, 0),
                arrowprops=dict(arrowstyle="->", color="#e5484d", lw=2), zorder=5)

    scatters: dict[str, object] = {}

    def update(_frame):
        resp = poller.latest
        if not resp:
            return []
        lasers = resp.get("lasers", [])
        xs_all, ys_all = [], []
        for i, laser in enumerate(lasers):
            name = laser.get("device_info", {}).get("device_name", f"laser{i}")
            pts = beams_to_base(laser)
            if name not in scatters:
                scatters[name] = ax.scatter([], [], s=4,
                                            c=DEVICE_COLORS[i % len(DEVICE_COLORS)],
                                            label=name, zorder=3)
                ax.legend(loc="upper right", facecolor="#0f151e",
                          edgecolor="#1e2836", labelcolor="#dbe4ef", fontsize=9)
            if pts:
                arr = np.array(pts)
                scatters[name].set_offsets(arr)
                xs_all.append(arr[:, 0])
                ys_all.append(arr[:, 1])
            else:
                scatters[name].set_offsets(np.empty((0, 2)))

        if args.range > 0:
            ax.set_xlim(-args.range, args.range)
            ax.set_ylim(-args.range, args.range)
        elif xs_all:
            allpts = np.abs(np.concatenate([np.concatenate(xs_all), np.concatenate(ys_all)]))
            m = max(2.0, float(np.percentile(allpts, 98)) * 1.15)
            ax.set_xlim(-m, m)
            ax.set_ylim(-m, m)

        age = time.monotonic() - poller.last_ok if poller.last_ok else 99
        state = "LIVE" if age < 1.5 else f"STALE {age:.1f}s"
        err = f"  |  reconnecting: {poller.error}" if poller.error else ""
        total = sum(len(beams_to_base(L)) for L in lasers)
        ax.set_title(f"SEER 2D LiDAR @ {args.ip}   [{state}]   "
                     f"{len(lasers)} devices - {total} pts - frame {poller.frames}{err}",
                     color="#dbe4ef", fontsize=11)
        return list(scatters.values())

    ani = FuncAnimation(fig, update, interval=max(60, int(1000 / args.hz)),
                        blit=False, cache_frame_data=False)
    try:
        plt.show()
    finally:
        poller.stop()
        client.close()


if __name__ == "__main__":
    main()
