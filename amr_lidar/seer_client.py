#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SEER Robot Status API client and LiDAR beam geometry (shared).

Protocol (Seer-API.pdf 15.1.1.1): a 16-byte binary header followed by a JSON
body. Laser scans are message 1009 (``robot_status_laser_req``) on TCP 19204.

    header = 0x5A | 0x01 | serial(u16) | body_len(u32) | msg_type(u16) | 6x 0x00
"""
from __future__ import annotations

import json
import math
import socket
import struct

SYNC = 0x5A
VERSION = 0x01
STATUS_PORT = 19204
MSG_LASER = 1009


class SeerLaserClient:
    """Persistent TCP client to the SEER status API, with lazy reconnect."""

    def __init__(self, ip: str, port: int = STATUS_PORT, timeout: float = 3.0):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._serial = 0

    def _connect(self) -> None:
        self._sock = socket.create_connection((self.ip, self.port), timeout=self.timeout)
        self._sock.settimeout(self.timeout)

    def _request(self, msg_type: int, payload: dict | None = None) -> dict:
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self._serial = (self._serial + 1) & 0xFFFF
        header = struct.pack(">BBHIH6s", SYNC, VERSION, self._serial,
                             len(body), msg_type, b"\x00" * 6)
        self._sock.sendall(header + body)

        hdr = b""
        while len(hdr) < 16:
            chunk = self._sock.recv(16 - len(hdr))
            if not chunk:
                raise IOError("connection closed during header")
            hdr += chunk
        length = struct.unpack(">I", hdr[4:8])[0]

        data = b""
        while len(data) < length:
            chunk = self._sock.recv(length - len(data))
            if not chunk:
                raise IOError("connection closed mid-body")
            data += chunk
        return json.loads(data.decode("utf-8")) if data else {}

    def get_lasers(self, beams_3d: bool = False) -> dict:
        """Return the parsed 1009 response; reconnects and re-raises on failure."""
        if self._sock is None:
            self._connect()
        try:
            return self._request(MSG_LASER, {"return_beams3D": beams_3d})
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None


def beams_to_base(laser: dict) -> list[tuple[float, float]]:
    """Transform one laser device's valid beams into robot base_link XY (meters).

    Applies the device's ``install_info`` (x, y, yaw degrees, and the ``upside``
    roll-pi mount flip) so multiple scanners fuse into one consistent frame.
    """
    install = laser.get("install_info", {}) or {}
    ix = install.get("x", 0.0)
    iy = install.get("y", 0.0)
    iyaw = math.radians(install.get("yaw", 0.0))
    upside = bool(install.get("upside", False))
    cos_y, sin_y = math.cos(iyaw), math.sin(iyaw)

    points: list[tuple[float, float]] = []
    for beam in laser.get("beams", []):
        if not beam.get("valid", False):
            continue
        dist = beam.get("dist")
        if not dist or dist <= 0.0:
            continue
        ang = math.radians(beam.get("angle", 0.0))
        lx = dist * math.cos(ang)
        ly = dist * math.sin(ang)
        if upside:
            ly = -ly
        points.append((ix + lx * cos_y - ly * sin_y,
                       iy + lx * sin_y + ly * cos_y))
    return points
