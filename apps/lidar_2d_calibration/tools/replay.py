#!/usr/bin/env python3
"""루프백 UDP 송신기 — 실센서 흉내 (하드웨어 없이 파이프라인 검증용).

사용법:
    python tools/replay.py [옵션]

옵션:
    --config    sensors.yaml 경로 (기본: config/sensors.yaml)
    --rate-hz   송신 주파수 Hz (기본: 20)
    --scene     synth | <파일경로.bin> (기본: synth)
    --count     송신 횟수 (0 = 무한, 기본: 0)
    --target-host 송신 대상 호스트 (기본: 127.0.0.1)

동작:
    - config 에서 front/rear 포트를 읽어 두 포트로 각각 송신한다.
    - front 장면: 합성 장면 원본 또는 지정 .bin 파일.
    - rear 장면: front 에 알려진 오프셋 변환 적용 (ICP 검증용).
    - KeyboardInterrupt 로 정지. 타임아웃/블로킹 최소화.

concurrency: 단일 스레드 — 두 소켓을 순차 송신 (rate 가 낮아 타임슬립만 사용).
"""

from __future__ import annotations

import argparse
import math
import socket
import struct
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

# 프로젝트 루트를 sys.path 에 추가 (tools/ 에서 직접 실행 시)
_TOOLS_DIR = Path(__file__).resolve().parent
_ROOT = _TOOLS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sensor_io.config_loader import load_sensor_config
from tools.synth_packets import (
    SENSOR_RESOLUTION_DEG,
    SENSOR_START_ANGLE_DEG,
    build_scan_packet,
    make_synthetic_scene,
)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

# rear 장면 생성 시 front 장면에 적용할 오프셋 (ICP 가 의미있게 동작하도록)
# numeric-coding §1: 단위 명시
_REAR_OFFSET_X_M: float = 0.05    # X 방향 오프셋 (m)
_REAR_OFFSET_ANGLE_DEG: float = 2.0  # 각도 오프셋 (도°)

# 송신 소켓 전송 타임아웃 (초)
_SEND_TIMEOUT_S: float = 1.0


# ---------------------------------------------------------------------------
# 장면 변환 (rear 흉내)
# ---------------------------------------------------------------------------


def _make_rear_scene(
    front_scene: List[Tuple[float, float, int]],
    offset_angle_deg: float = _REAR_OFFSET_ANGLE_DEG,
    offset_dist_m: float = _REAR_OFFSET_X_M,
) -> List[Tuple[float, float, int]]:
    """front 장면에 알려진 오프셋 변환을 적용하여 rear 장면을 생성한다.

    변환: 각 유효 빔의 각도에 offset_angle_deg 를 더하고,
          거리에 offset_dist_m 를 더한다 (단순 평행 이동 근사).
          무효 빔(status=0x00)은 그대로 유지.

    Args:
        front_scene:      front 장면 [(angle_deg, distance_m, status), ...].
        offset_angle_deg: 각도 오프셋 (도°).
        offset_dist_m:    거리 오프셋 (m).

    Returns:
        rear 장면 리스트 (동일 길이).
    """
    rear: List[Tuple[float, float, int]] = []
    for angle_deg, dist_m, status in front_scene:
        if status & 0x01:  # valid 빔만 변환
            new_angle = angle_deg + offset_angle_deg
            new_dist = max(0.0, dist_m + offset_dist_m)
            rear.append((new_angle, new_dist, status))
        else:
            rear.append((angle_deg, dist_m, status))
    return rear


# ---------------------------------------------------------------------------
# 송신 함수
# ---------------------------------------------------------------------------


def send_packet(
    sock: socket.socket,
    packet: bytes,
    host: str,
    port: int,
) -> None:
    """단일 패킷을 지정 호스트:포트로 UDP 전송한다.

    Args:
        sock:   열린 UDP 소켓.
        packet: 전송할 바이트열.
        host:   대상 호스트.
        port:   대상 포트.
    """
    sock.sendto(packet, (host, port))


def load_scene_from_file(path: str) -> bytes:
    """지정 경로의 .bin 파일에서 골든 패킷을 로드한다.

    Args:
        path: 파일 경로.

    Returns:
        파일 내용 바이트열.

    Raises:
        FileNotFoundError: 파일이 없을 때.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"장면 파일을 찾을 수 없습니다: {p}")
    return p.read_bytes()


# ---------------------------------------------------------------------------
# 메인 루프
# ---------------------------------------------------------------------------


def run_replay(
    front_port: int,
    rear_port: int,
    target_host: str,
    rate_hz: float,
    scene_arg: str,
    count: int,
) -> None:
    """replay 루프 본체.

    Args:
        front_port:  front 센서 UDP 포트.
        rear_port:   rear 센서 UDP 포트.
        target_host: 송신 대상 호스트 (루프백).
        rate_hz:     초당 송신 횟수.
        scene_arg:   "synth" 또는 .bin 파일 경로.
        count:       총 송신 횟수 (0 = 무한).
    """
    # 장면 로드
    if scene_arg == "synth":
        front_scene = make_synthetic_scene()
        front_bytes: Optional[bytes] = None  # 매 회 scan_number 갱신하여 빌드
    else:
        # .bin 파일: 고정 패킷 반복 송신
        front_bytes = load_scene_from_file(scene_arg)
        front_scene = []

    interval_s = 1.0 / max(rate_hz, 0.001)  # 0으로 나누기 방어
    scan_number = 1
    sent = 0

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(_SEND_TIMEOUT_S)

        print(
            f"replay 시작: front={target_host}:{front_port}  "
            f"rear={target_host}:{rear_port}  "
            f"rate={rate_hz} Hz  count={'∞' if count == 0 else count}"
        )

        try:
            while True:
                if count > 0 and sent >= count:
                    break

                # front 패킷 생성
                if front_bytes is not None:
                    pkt_front = front_bytes
                    pkt_rear = front_bytes  # 파일 모드: 동일 패킷 사용
                else:
                    pkt_front = build_scan_packet(
                        points=front_scene,
                        scan_number=scan_number,
                        start_angle_deg=SENSOR_START_ANGLE_DEG,
                        resolution_deg=SENSOR_RESOLUTION_DEG,
                    )
                    rear_scene = _make_rear_scene(front_scene)
                    pkt_rear = build_scan_packet(
                        points=rear_scene,
                        scan_number=scan_number,
                        start_angle_deg=SENSOR_START_ANGLE_DEG,
                        resolution_deg=SENSOR_RESOLUTION_DEG,
                        identification=2,
                    )

                send_packet(sock, pkt_front, target_host, front_port)
                send_packet(sock, pkt_rear, target_host, rear_port)

                sent += 1
                scan_number += 1

                if sent % 20 == 0 or sent == 1:
                    print(
                        f"  송신 {sent}: front={len(pkt_front)}B → :{front_port}  "
                        f"rear={len(pkt_rear)}B → :{rear_port}"
                    )

                # 무한 대기 금지: count > 0 이고 마지막 회이면 sleep 생략
                if count > 0 and sent >= count:
                    break

                time.sleep(interval_s)

        except KeyboardInterrupt:
            print(f"\nreplay 중단 (KeyboardInterrupt) — 총 {sent} 회 송신")

    print(f"replay 완료: {sent} 회 송신")


# ---------------------------------------------------------------------------
# CLI 진입점
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """CLI 인수 파서를 구성한다."""
    p = argparse.ArgumentParser(
        description="SICK nanoScan3 UDP 루프백 재생기 (하드웨어 없이 파이프라인 검증)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--config",
        default=str(_ROOT / "config" / "sensors.yaml"),
        help="sensors.yaml 경로",
    )
    p.add_argument(
        "--rate-hz",
        type=float,
        default=20.0,
        help="송신 주파수 (Hz)",
    )
    p.add_argument(
        "--scene",
        default="synth",
        help="장면 소스: 'synth' 또는 .bin 파일 경로",
    )
    p.add_argument(
        "--count",
        type=int,
        default=0,
        help="총 송신 횟수 (0 = 무한)",
    )
    p.add_argument(
        "--target-host",
        default="127.0.0.1",
        help="송신 대상 호스트",
    )
    return p


def main() -> None:
    """CLI 진입점."""
    args = _build_parser().parse_args()

    # sensors.yaml 로드 (신뢰경계: config_loader 가 검증)
    try:
        cfg = load_sensor_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"설정 로드 실패: {exc}", file=sys.stderr)
        sys.exit(1)

    front_port: int = cfg["network"]["front"]["port"]
    rear_port: int = cfg["network"]["rear"]["port"]

    run_replay(
        front_port=front_port,
        rear_port=rear_port,
        target_host=args.target_host,
        rate_hz=args.rate_hz,
        scene_arg=args.scene,
        count=args.count,
    )


if __name__ == "__main__":
    main()
