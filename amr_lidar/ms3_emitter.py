#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SEER LiDAR -> SICK "MS3 " UDP emitter (subscribe / pull model).

Pulls the AMR's per-device laser scans from the SEER API and re-emits each as
raw SICK nanoScan3 ``MS3 `` datagrams -- but ONLY to clients that have
authenticated with id/pw and keep their lease alive with periodic pings.
Nothing is ever broadcast, and with zero subscribers nothing leaves the machine
(no spray, no contamination). Only a PC that knows the control ip:port + id/pw
can pull the stream.

Beams are emitted RAW in each sensor's own frame (angle/dist) -- exactly what a
calibration tool needs (it computes the mount transform itself). The app's
passive MS3 receivers consume the data unchanged.

  emitter:    python -m amr_lidar.ms3_emitter --seer 192.168.44.82 \
                  --control-port 6099 --id amr --pw lidar2026 --hz 10
  subscriber: python -m amr_lidar.ms3_subscriber 127.0.0.1 --control-port 6099 \
                  --id amr --pw lidar2026 --front-port 6060 --rear-port 6061

Control plane -- JSON over UDP on --control-port:
  client -> {"cmd":"auth","id","pw","front_port","rear_port"}
         <- {"status":"ok","hz","lease"} | {"status":"denied"}
  client -> {"cmd":"ping"}   (every lease/3 s, holds the lease)
         <- (silent) | {"status":"reauth"} if the client is not/no-longer known
  client -> {"cmd":"bye"}    (unsubscribe)

Data plane: raw MS3 datagrams are UNICAST to each live subscriber's
<ip>:front_port (front device) and <ip>:rear_port (rear device). This is a
DIFFERENT socket/port from the control plane, so JSON replies never mix into the
scan-data stream the app parses.

Wire format: 24-byte datagram header + 52-byte data header + DerivedValues(20) +
MeasurementData, per sick_safetyscanners_base (matches the app's DataParser).
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import threading
import time

from .seer_client import SeerLaserClient, STATUS_PORT

MARKER = b"MS3 "
ANGLE_SCALE = 4194304.0
DATAGRAM_HDR = 24
DATA_HDR = 52
DERIVED = 20


def build_ms3(seq: int, beams: list[dict]) -> bytes:
    """Encode one device's beams into a single MS3 datagram.

    beams: list of {'angle': deg, 'dist': m, 'valid': bool, 'rssi': int}
    """
    n = len(beams)
    if n >= 2:
        start_deg = beams[0].get("angle", 0.0)
        res_deg = (beams[-1].get("angle", 0.0) - start_deg) / (n - 1)
    else:
        start_deg, res_deg = 0.0, 0.0

    # --- data header (52 bytes) ---
    dh = bytearray(DATA_HDR)
    struct.pack_into("<BBBB", dh, 0, 1, 1, 0, 0)        # version, major, minor, release
    struct.pack_into("<I", dh, 4, seq & 0xFFFFFFFF)     # serial device (reuse as id)
    struct.pack_into("<I", dh, 8, 0)                    # serial plug
    dh[12] = 0                                          # channel
    struct.pack_into("<I", dh, 16, seq & 0xFFFFFFFF)    # sequence number
    struct.pack_into("<I", dh, 20, seq & 0xFFFFFFFF)    # scan number
    struct.pack_into("<H", dh, 32, 0); struct.pack_into("<H", dh, 34, 0)   # gen state off/size
    struct.pack_into("<H", dh, 36, DATA_HDR)            # derived values offset = 52
    struct.pack_into("<H", dh, 38, DERIVED)             # derived values size = 20
    meas_off = DATA_HDR + DERIVED                       # 72
    meas_size = 4 + 4 * n
    struct.pack_into("<H", dh, 40, meas_off)
    struct.pack_into("<H", dh, 42, meas_size & 0xFFFF)
    # intrusion / application blocks absent (offsets/sizes = 0)

    # --- derived values (20 bytes) ---
    dv = bytearray(DERIVED)
    struct.pack_into("<H", dv, 0, 1)                    # multiplication factor
    struct.pack_into("<H", dv, 2, n)                    # number of beams
    struct.pack_into("<H", dv, 4, 0)                    # scan time
    struct.pack_into("<i", dv, 8, int(round(start_deg * ANGLE_SCALE)))
    struct.pack_into("<i", dv, 12, int(round(res_deg * ANGLE_SCALE)))
    struct.pack_into("<I", dv, 16, 0)                   # interbeam period

    # --- measurement data ---
    md = bytearray(4 + 4 * n)
    struct.pack_into("<I", md, 0, n)
    for i, b in enumerate(beams):
        valid = bool(b.get("valid"))
        dist_mm = int(round((b.get("dist") or 0.0) * 1000.0)) if valid else 0
        dist_mm = max(0, min(65535, dist_mm))
        refl = int(b.get("rssi") or 0) & 0xFF
        status = 0x01 if valid else 0x00
        struct.pack_into("<HBB", md, 4 + i * 4, dist_mm, refl, status)

    complete = bytes(dh) + bytes(dv) + bytes(md)

    # --- datagram header (24 bytes), single fragment ---
    hdr = bytearray(DATAGRAM_HDR)
    hdr[0:4] = MARKER
    struct.pack_into(">H", hdr, 4, 1)                   # protocol (BE; parser ignores)
    hdr[6] = 1; hdr[7] = 0                              # major, minor
    struct.pack_into("<I", hdr, 8, len(complete))       # total length
    struct.pack_into("<I", hdr, 12, seq & 0xFFFFFFFF)   # identification
    struct.pack_into("<I", hdr, 16, 0)                  # fragment offset
    return bytes(hdr) + complete


def pick(lasers, key):
    """Return the laser dict whose device_name contains key (case-insensitive)."""
    for L in lasers:
        if key.lower() in L.get("device_info", {}).get("device_name", "").lower():
            return L
    return None


class Ms3Emitter:
    """Auth-gated, pull-based raw-MS3 emitter.

    A single SEER connection feeds any number of authenticated subscribers.
    Concurrency: ``subscribers`` is guarded by ``lock``; the control thread is
    the only writer, the publish thread only snapshots under the lock.
    """

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        # ctrl_addr (ip, ephemeral_port) -> {"ip","front_port","rear_port","expiry"}
        self.subscribers: dict[tuple, dict] = {}
        self.lock = threading.Lock()
        self.running = True

        self.ctrl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ctrl.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Windows: stop a sendto() to a vanished client from raising
        # WSAECONNRESET (10054) on the next recvfrom(). No-op elsewhere.
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            try:
                self.ctrl.ioctl(socket.SIO_UDP_CONNRESET, 0)
            except OSError:
                pass
        self.ctrl.bind((args.bind, args.control_port))
        # send-only socket for MS3 data (never broadcast: SO_BROADCAST unset)
        self.data = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _reply(self, addr, obj) -> None:
        try:
            self.ctrl.sendto(json.dumps(obj).encode(), addr)
        except OSError:
            pass

    def control_loop(self) -> None:
        self.ctrl.settimeout(1.0)
        while self.running:
            try:
                data, addr = self.ctrl.recvfrom(2048)
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
                    fp = int(msg.get("front_port", self.args.front_port))
                    rp = int(msg.get("rear_port", self.args.rear_port))
                    with self.lock:
                        self.subscribers[addr] = {
                            "ip": addr[0], "front_port": fp, "rear_port": rp,
                            "expiry": time.monotonic() + self.args.lease,
                        }
                        nsub = len(self.subscribers)
                    self._reply(addr, {"status": "ok", "hz": self.args.hz,
                                       "lease": self.args.lease})
                    print(f"[auth] {addr[0]}:{addr[1]} -> data {addr[0]}:{fp}/{rp} "
                          f"({nsub} subs)")
                else:
                    self._reply(addr, {"status": "denied"})
                    print(f"[auth] {addr[0]}:{addr[1]} DENIED")
            elif cmd == "ping":
                with self.lock:
                    sub = self.subscribers.get(addr)
                    if sub is not None:
                        sub["expiry"] = time.monotonic() + self.args.lease
                if sub is None:
                    self._reply(addr, {"status": "reauth"})
            elif cmd == "bye":
                with self.lock:
                    self.subscribers.pop(addr, None)
                print(f"[bye ] {addr[0]}:{addr[1]} left")

    def publish_loop(self) -> None:
        client = SeerLaserClient(self.args.seer)
        period = 1.0 / self.args.hz
        seq = 0
        frames = 0
        while self.running:
            t0 = time.monotonic()
            try:
                resp = client.get_lasers()
                lasers = resp.get("lasers", [])
                front = pick(lasers, "front") or (lasers[0] if lasers else None)
                rear = pick(lasers, "rear") or (lasers[1] if len(lasers) > 1 else None)
                seq += 1
                front_dg = build_ms3(seq, front.get("beams", [])) if front else None
                rear_dg = build_ms3(seq, rear.get("beams", [])) if rear else None

                now = time.monotonic()
                with self.lock:
                    for a in [a for a, s in self.subscribers.items() if s["expiry"] < now]:
                        del self.subscribers[a]
                        print(f"[lease] {a[0]}:{a[1]} expired")
                    targets = list(self.subscribers.values())

                for s in targets:
                    if front_dg is not None:
                        try:
                            self.data.sendto(front_dg, (s["ip"], s["front_port"]))
                        except OSError:
                            pass
                    if rear_dg is not None:
                        try:
                            self.data.sendto(rear_dg, (s["ip"], s["rear_port"]))
                        except OSError:
                            pass

                frames += 1
                if frames % 50 == 0:
                    fn = len(front.get("beams", [])) if front else 0
                    rn = len(rear.get("beams", [])) if rear else 0
                    print(f"[emit] frame {seq}: front {fn} beams, rear {rn} beams "
                          f"-> {len(targets)} subs")
            except Exception as exc:  # noqa: BLE001
                print(f"[seer] fetch failed: {exc}; retrying")
                time.sleep(0.5)
            dt = time.monotonic() - t0
            if dt < period:
                time.sleep(period - dt)

    def run(self) -> None:
        a = self.args
        print("SEER -> SICK MS3 UDP emitter (subscribe / pull, raw beams)")
        print(f"  source (SEER API): {a.seer}:{STATUS_PORT}")
        print(f"  control plane    : {a.bind}:{a.control_port}  id='{a.id}'  "
              f"lease={a.lease}s  rate={a.hz}Hz")
        print(f"  data plane       : raw MS3 UNICAST to each subscriber's "
              f"<ip>:{a.front_port}(front)/{a.rear_port}(rear)")
        print("  no subscribers = nothing sent. no broadcast, no spray.")
        print(f"  subscribe: python -m amr_lidar.ms3_subscriber <this-pc-ip> "
              f"--control-port {a.control_port} --id {a.id} --pw {a.pw}")
        threading.Thread(target=self.control_loop, daemon=True).start()
        try:
            self.publish_loop()
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            self.ctrl.close()
            self.data.close()


def main() -> None:
    p = argparse.ArgumentParser(
        description="Publish SEER LiDAR as raw SICK MS3 UDP to authed subscribers")
    p.add_argument("--seer", default="192.168.44.82", help="AMR / SEER API IP")
    p.add_argument("--bind", default="0.0.0.0",
                   help="control-socket bind interface (use 127.0.0.1 to contain "
                        "the control plane to this PC)")
    p.add_argument("--control-port", type=int, default=6099,
                   help="UDP control port subscribers auth/ping on (default 6099)")
    p.add_argument("--front-port", type=int, default=6060,
                   help="default data port for the front device (default 6060)")
    p.add_argument("--rear-port", type=int, default=6061,
                   help="default data port for the rear device (default 6061)")
    p.add_argument("--id", default="amr", help="subscriber id")
    p.add_argument("--pw", default="lidar2026", help="subscriber password")
    p.add_argument("--hz", type=float, default=10.0, help="publish rate (<=10)")
    p.add_argument("--lease", type=float, default=10.0, help="subscription TTL seconds")
    Ms3Emitter(p.parse_args()).run()


if __name__ == "__main__":
    main()
