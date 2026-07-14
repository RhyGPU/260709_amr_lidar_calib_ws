#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keepalive subscriber for the raw-MS3 emitter (amr_lidar.ms3_emitter).

Authenticates to the emitter's control port with id/pw, then pings on an
interval to hold the lease so the emitter keeps unicasting raw MS3 to THIS
machine's front/rear data ports. The calibration app's passive UDP receivers
consume that MS3 unchanged -- this process only manages the subscription.

    python -m amr_lidar.ms3_subscriber 127.0.0.1 --control-port 6099 \
        --id amr --pw lidar2026 --front-port 6060 --rear-port 6061

Robust by design:
  - Control replies arrive on THIS socket only (scan data goes to the data
    ports), so JSON and scan bytes never mix -- the reauth path actually works.
  - Re-authenticates automatically if the emitter forgets us (lease lost or
    emitter restarted -> it answers a ping with {"status":"reauth"}).
  - Never exits on transient errors; it retries with backoff so a GUI can keep
    it running for the whole session. Wrong id/pw is the only hard stop.
"""
from __future__ import annotations

import argparse
import json
import socket
import time


class Ms3Subscriber:
    """Holds a subscription to the emitter alive with periodic pings."""

    def __init__(self, server: str, control_port: int, sub_id: str, pw: str,
                 front_port: int, rear_port: int) -> None:
        self.server = (server, control_port)
        self.id = sub_id
        self.pw = pw
        self.front_port = front_port
        self.rear_port = rear_port

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            try:
                self.sock.ioctl(socket.SIO_UDP_CONNRESET, 0)
            except OSError:
                pass

        self.lease = 10.0
        self.authed = False
        self.running = True

    # -- callbacks (override / assign for GUI status wiring) --
    def on_state(self, connected: bool, detail: str) -> None:
        print(f"[sub] {'UP  ' if connected else 'DOWN'} {detail}")

    def _auth_pkt(self) -> bytes:
        return json.dumps({
            "cmd": "auth", "id": self.id, "pw": self.pw,
            "front_port": self.front_port, "rear_port": self.rear_port,
        }).encode()

    def authenticate(self) -> bool:
        """Send auth, wait for the JSON reply. True on success, False otherwise.

        Returns False (without raising) on timeout so the caller can back off
        and retry; only a 'denied' status is a definitive rejection.
        """
        self.sock.settimeout(2.0)
        for attempt in range(3):
            if not self.running:
                return False
            try:
                self.sock.sendto(self._auth_pkt(), self.server)
            except OSError as exc:
                self.on_state(False, f"send failed: {exc}")
                time.sleep(1.0)
                continue
            try:
                data, _ = self.sock.recvfrom(2048)
            except socket.timeout:
                self.on_state(False, f"no reply from {self.server[0]}:{self.server[1]} "
                                     f"(try {attempt + 1}/3)")
                continue
            except OSError:
                time.sleep(0.5)
                continue
            try:
                reply = json.loads(data.decode())
            except Exception:
                continue  # stray/non-JSON datagram -- ignore, keep waiting
            status = reply.get("status")
            if status == "ok":
                self.lease = float(reply.get("lease", 10))
                self.authed = True
                self.on_state(True, f"authenticated, lease {self.lease}s, "
                                    f"emitter {reply.get('hz')}Hz")
                return True
            if status == "denied":
                self.on_state(False, "AUTH DENIED - wrong id/pw")
                return False
        return False

    def run(self) -> None:
        """Auth, then ping forever; re-auth on demand. Blocks until stop()."""
        self.sock.settimeout(0.5)
        next_ping = 0.0
        denied = False
        while self.running:
            if not self.authed:
                if not self.authenticate():
                    # 'denied' -> back off long (won't help to hammer); else short
                    time.sleep(3.0)
                    continue
                next_ping = time.monotonic() + max(1.0, self.lease / 3.0)

            # drain control replies (only reauth matters); short timeout keeps ping cadence
            try:
                data, _ = self.sock.recvfrom(2048)
                try:
                    reply = json.loads(data.decode())
                except Exception:
                    reply = None
                if reply and reply.get("status") == "reauth":
                    self.on_state(False, "emitter asked to re-auth (forgotten/restarted)")
                    self.authed = False
                    continue
            except socket.timeout:
                pass
            except OSError:
                self.authed = False
                time.sleep(0.5)
                continue

            now = time.monotonic()
            if self.authed and now >= next_ping:
                try:
                    self.sock.sendto(json.dumps({"cmd": "ping"}).encode(), self.server)
                except OSError:
                    self.authed = False
                    continue
                next_ping = now + max(1.0, self.lease / 3.0)

    def stop(self) -> None:
        """Unsubscribe (best-effort 'bye') and end the run loop."""
        self.running = False
        try:
            self.sock.sendto(json.dumps({"cmd": "bye"}).encode(), self.server)
        except OSError:
            pass


def main() -> None:
    p = argparse.ArgumentParser(description="Subscribe to the raw-MS3 emitter and hold the lease")
    p.add_argument("server", help="emitter host IP (the PC running ms3_emitter)")
    p.add_argument("--control-port", type=int, default=6099)
    p.add_argument("--id", default="amr")
    p.add_argument("--pw", default="lidar2026")
    p.add_argument("--front-port", type=int, default=6060, help="local port the app binds for front")
    p.add_argument("--rear-port", type=int, default=6061, help="local port the app binds for rear")
    args = p.parse_args()

    sub = Ms3Subscriber(args.server, args.control_port, args.id, args.pw,
                        args.front_port, args.rear_port)
    print(f"Subscribing to emitter {args.server}:{args.control_port} as id='{args.id}' "
          f"-> data on :{args.front_port}/{args.rear_port}. Ctrl+C to stop.")
    try:
        sub.run()
    except KeyboardInterrupt:
        pass
    finally:
        sub.stop()


if __name__ == "__main__":
    main()
