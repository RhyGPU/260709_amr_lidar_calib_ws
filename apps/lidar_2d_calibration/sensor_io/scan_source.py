#!/usr/bin/env python3
"""
ScanSource — frozen public contract (ADR-002) replacing ros_scan_bridge.py.

Bridges nanoScan3 UDP receivers to the UI/engine via Qt signals. Signal/method
SIGNATURES ARE FROZEN — changing them requires an ADR supersede.

Coordinate contract (numeric-coding §1):
  emitted points are (N,2) float32, METERS, sensor-LOCAL frame, X forward, CCW+.
  deg→rad conversion happens once here (_scan_to_points); flip is NOT applied here
  (transform_points_2d handles flip at the merged stage).

Concurrency contract (concurrency-coding §1, ADR-002):
  - NanoScan3Receiver runs a daemon recv thread (single writer of latest_scan).
  - QTimer fires on the Qt main thread (UI thread) and polls get_latest_scan().
  - Qt Signal.emit() is called only from the QTimer slot (main thread). Never from
    the recv thread directly.
"""

import logging
import math
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from core.tf_calculator import TFTransform2D, compose_tf, invert_tf
from sensor_io.nanoscan3_receiver import NanoScan3Receiver

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 폴링 주기 (ms) — 25 Hz ≈ 40 ms (concurrency-coding §1: QTimer 폴링)
# ---------------------------------------------------------------------------
_POLL_INTERVAL_MS: int = 40

# ---------------------------------------------------------------------------
# 이동 평균 필터 윈도 크기 (포인트 개수)
# ---------------------------------------------------------------------------
_AVG_FILTER_WINDOW: int = 3


class ScanSource(QObject):
    """ROS-free scan provider. Public surface mirrors ros_scan_bridge.RosScanBridge.

    동시성:
        - 수신: NanoScan3Receiver 데몬 스레드(WP3). latest_scan 은 수신 스레드만 갱신.
        - UI emit: QTimer(_POLL_INTERVAL_MS)가 Qt 메인 스레드에서 발화.
          _poll_scans() 슬롯에서 get_latest_scan() 스냅샷 획득 → Signal emit.
        - 수신 스레드에서 Qt Signal 직접 emit 금지.
    """

    # --- FROZEN signals (ADR-002) ---
    front_scan_updated = Signal(object)  # (N,2) float32, sensor-local m
    rear_scan_updated = Signal(object)  # (M,2) float32, sensor-local m
    connection_status_changed = Signal(bool, bool)  # front_ok, rear_ok
    scan_info_updated = Signal(int, int)  # front_n, rear_n

    def __init__(self, config: dict, parent=None):
        """
        Args:
            config: parsed sensors.yaml dict (see sensor_io.config_loader). Provides
                network (ip/port/discriminate_by) and mounting (tx,ty,yaw,flipped).
        """
        super().__init__(parent)
        self._config = config

        net = config["network"]
        bind_ip: str = net["bind_ip"]
        discriminate_by: str = net["discriminate_by"]

        pre = config["preprocessing"]
        self._min_range_m: float = float(pre["min_range_m"])
        self._max_range_m: float = float(pre["max_range_m"])
        self._enable_average_filter: bool = bool(pre["enable_average_filter"])

        # --- NanoScan3Receiver 생성 (discriminate_by 전략 분기) ---
        # 'port'   : 각 센서를 다른 포트로 바인드, source_ip_filter=None
        # 'source_ip': 같은 포트로 바인드, source_ip_filter 로 센서 구분
        if discriminate_by == "port":
            self._front_rx = NanoScan3Receiver(
                local_ip=bind_ip,
                local_port=net["front"]["port"],
                source_ip_filter=None,
            )
            self._rear_rx = NanoScan3Receiver(
                local_ip=bind_ip,
                local_port=net["rear"]["port"],
                source_ip_filter=None,
            )
        else:  # 'source_ip'
            # 두 수신기가 같은 포트를 바인드하는 것은 OS 수준에서 허용되지 않으므로
            # 관례상 front port 로 단일 바인드 후 source_ip 로 구분한다.
            # 실제 운용에서는 단일 포트에 두 센서가 들어오는 환경(포트 포워딩 등)을 전제.
            self._front_rx = NanoScan3Receiver(
                local_ip=bind_ip,
                local_port=net["front"]["port"],
                source_ip_filter=net["front"]["ip"],
            )
            self._rear_rx = NanoScan3Receiver(
                local_ip=bind_ip,
                local_port=net["rear"]["port"],
                source_ip_filter=net["rear"]["ip"],
            )

        # --- 연결 상태 추적 (변화 시만 emit) ---
        self._prev_front_ok: bool = False
        self._prev_rear_ok: bool = False

        # --- QTimer: Qt 메인 스레드에서 폴링 (concurrency-coding §1) ---
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_scans)

    # --- FROZEN lifecycle ---

    def start(self) -> None:
        """Start UDP receivers and the polling timer."""
        self._front_rx.start()
        self._rear_rx.start()
        self._poll_timer.start()
        logger.info("ScanSource started (poll=%d ms)", _POLL_INTERVAL_MS)

    def stop(self) -> None:
        """Stop receivers and release sockets."""
        self._poll_timer.stop()
        self._front_rx.stop()
        self._rear_rx.stop()
        logger.info("ScanSource stopped")

    # --- 폴링 슬롯 (Qt 메인 스레드 전용 — QTimer.timeout 에 연결됨) ---

    def _poll_scans(self) -> None:
        """QTimer 슬롯: 각 수신기 스냅샷 획득 → 변환 → Signal emit.

        수신 스레드에서는 절대 호출되지 않는다 (QTimer 는 Qt 메인 스레드에서 발화).
        """
        # --- front ---
        front_scan = self._front_rx.get_latest_scan()
        if front_scan is not None:
            front_pts = _scan_to_points(
                front_scan,
                self._min_range_m,
                self._max_range_m,
                self._enable_average_filter,
            )
            self.front_scan_updated.emit(front_pts)
        else:
            front_pts = np.empty((0, 2), dtype=np.float32)

        # --- rear ---
        rear_scan = self._rear_rx.get_latest_scan()
        if rear_scan is not None:
            rear_pts = _scan_to_points(
                rear_scan,
                self._min_range_m,
                self._max_range_m,
                self._enable_average_filter,
            )
            self.rear_scan_updated.emit(rear_pts)
        else:
            rear_pts = np.empty((0, 2), dtype=np.float32)

        # --- 연결 상태 변화 시만 emit ---
        front_ok, _ = self._front_rx.get_health()
        rear_ok, _ = self._rear_rx.get_health()
        if front_ok != self._prev_front_ok or rear_ok != self._prev_rear_ok:
            self._prev_front_ok = front_ok
            self._prev_rear_ok = rear_ok
            self.connection_status_changed.emit(front_ok, rear_ok)

        # --- 점 개수 emit ---
        self.scan_info_updated.emit(len(front_pts), len(rear_pts))

    # --- Network endpoint 접근자 / 재연결 ---

    def endpoints(self) -> dict:
        """현재 수신기 ip:port 설정을 반환한다 (UI 프리필용).

        Returns:
            {
                'front': (ip: str, port: int),
                'rear':  (ip: str, port: int),
                'discriminate_by': str,
            }
        """
        net = self._config["network"]
        return {
            "front": (net["front"]["ip"], net["front"]["port"]),
            "rear": (net["rear"]["ip"], net["rear"]["port"]),
            "discriminate_by": net["discriminate_by"],
        }

    def reconnect(
        self,
        front_ip: str,
        front_port: int,
        rear_ip: str,
        rear_port: int,
    ) -> None:
        """수신기를 새 ip/port로 재바인드한다.

        기존 수신 스레드를 완전히 join한 뒤 새 NanoScan3Receiver를 생성하고
        start()를 호출한다. QTimer는 유지한다(불필요한 재시작 없음).
        discriminate_by 모드는 기존 설정을 그대로 유지한다.

        concurrency: stop()이 recv 스레드 join(timeout=3s)까지 보장하므로
        새 수신기 생성 전 구 소켓이 완전히 해제된다.

        Args:
            front_ip:   Front 수신기 바인드 IP.
            front_port: Front 수신기 바인드 포트.
            rear_ip:    Rear 수신기 바인드 IP.
            rear_port:  Rear 수신기 바인드 포트.

        Raises:
            OSError: 새 포트 바인딩 실패 시. 실패 시 기존 수신기가 stop된
                     상태이므로 호출자가 재시도 또는 에러 처리를 책임진다.
        """
        net = self._config["network"]
        bind_ip: str = net["bind_ip"]
        discriminate_by: str = net["discriminate_by"]

        # 1) 기존 수신기 정지 (recv 스레드 join 보장)
        self._front_rx.stop()
        self._rear_rx.stop()

        # 2) 새 NanoScan3Receiver 생성
        if discriminate_by == "port":
            new_front_rx = NanoScan3Receiver(
                local_ip=bind_ip,
                local_port=front_port,
                source_ip_filter=None,
            )
            new_rear_rx = NanoScan3Receiver(
                local_ip=bind_ip,
                local_port=rear_port,
                source_ip_filter=None,
            )
        else:  # 'source_ip'
            new_front_rx = NanoScan3Receiver(
                local_ip=bind_ip,
                local_port=front_port,
                source_ip_filter=front_ip,
            )
            new_rear_rx = NanoScan3Receiver(
                local_ip=bind_ip,
                local_port=rear_port,
                source_ip_filter=rear_ip,
            )

        # 3) 바인딩 시도 (OSError 시 caller에 전파 — 상태는 stop된 상태로 보존)
        new_front_rx.start()
        try:
            new_rear_rx.start()
        except OSError:
            new_front_rx.stop()
            raise

        # 4) 인스턴스 교체
        self._front_rx = new_front_rx
        self._rear_rx = new_rear_rx

        # 5) _config 동기화 (endpoints() / 저장 일관성)
        self._config["network"]["front"]["ip"] = front_ip
        self._config["network"]["front"]["port"] = front_port
        self._config["network"]["rear"]["ip"] = rear_ip
        self._config["network"]["rear"]["port"] = rear_port

        # 6) 연결 상태 추적 초기화
        self._prev_front_ok = False
        self._prev_rear_ok = False

        logger.info(
            "ScanSource reconnected: front=%s:%d  rear=%s:%d  discriminate_by=%s",
            bind_ip, front_port, bind_ip, rear_port, discriminate_by,
        )

    # --- FROZEN config → TF ---

    def get_initial_tfs(self) -> Optional[dict]:
        """
        Build initial jog transforms from config mounting params.

        Returns dict with keys:
          'merged_to_front', 'merged_to_rear', 'tf_base_front', 'tf_base_rear',
          'tf_front_rear'  (all TFTransform2D), or None on failure.
        Mirrors ros_scan_bridge.get_initial_tfs but reads YAML instead of ROS params.
        """
        try:
            m = self._config["mounting"]
            tf_base_front = TFTransform2D(
                tx=float(m["front"]["tx"]),
                ty=float(m["front"]["ty"]),
                yaw=math.radians(float(m["front"]["yaw_deg"])),
                flipped=bool(m["front"].get("flipped", False)),
            )
            tf_base_rear = TFTransform2D(
                tx=float(m["rear"]["tx"]),
                ty=float(m["rear"]["ty"]),
                yaw=math.radians(float(m["rear"]["yaw_deg"])),
                flipped=bool(m["rear"].get("flipped", False)),
            )
            tf_front_rear = compose_tf(invert_tf(tf_base_front), tf_base_rear)
            return {
                "merged_to_front": tf_base_front,
                "merged_to_rear": tf_base_rear,
                "tf_base_front": tf_base_front,
                "tf_base_rear": tf_base_rear,
                "tf_front_rear": tf_front_rear,
            }
        except (KeyError, TypeError, ValueError):
            return None

    # --- FROZEN point transform (contract math; used by engine injection) ---

    @staticmethod
    def transform_points_2d(points: np.ndarray, tf: TFTransform2D) -> np.ndarray:
        """
        Transform (N,2) sensor-local points by tf. flipped (roll=pi) → negate Y first.
          p' = R(yaw) * [x, ±y]^T + [tx, ty]
        """
        if points is None or len(points) == 0:
            return points
        px = points[:, 0]
        py = -points[:, 1] if tf.flipped else points[:, 1]
        cos_y, sin_y = math.cos(tf.yaw), math.sin(tf.yaw)
        return np.column_stack(
            [
                px * cos_y - py * sin_y + tf.tx,
                px * sin_y + py * cos_y + tf.ty,
            ]
        )


# ---------------------------------------------------------------------------
# 순수 변환 함수 (PySide6 의존 없음 — 단위 테스트 직접 가능)
# ---------------------------------------------------------------------------


def _scan_to_points(
    scan,
    min_range_m: float,
    max_range_m: float,
    enable_average_filter: bool,
) -> np.ndarray:
    """ScanData → (N,2) float32 ndarray (센서 로컬 좌표, 미터).

    변환 파이프라인:
        1. is_valid=True + is_infinite=False 인 포인트만 선택
        2. min_range_m ≤ distance_m ≤ max_range_m 범위 필터
        3. NaN/Inf 제거 (numeric-coding §3)
        4. (선택) 3점 이동평균 필터 (distance_m 축)
        5. 극좌표(angle_deg, distance_m) → 직교좌표(x_m, y_m)
           각도 변환: math.radians(angle_deg) — 경계에서 1회 (numeric-coding §1)

    좌표 계약 (불변):
        - X 전방, CCW+, 센서 로컬, 미터
        - flip 은 여기서 적용하지 않는다 (transform_points_2d 담당)

    Args:
        scan: ScanData (sensor_io.nanoscan3_protocol.ScanData).
              scan.points: List[ScanPoint] 각 요소는
                  angle_deg: float (도, CCW+)
                  distance_m: float (미터)
                  is_valid: bool
                  is_infinite: bool
        min_range_m: 유효 거리 최솟값 (미터).
        max_range_m: 유효 거리 최댓값 (미터).
        enable_average_filter: True 이면 3점 이동평균 적용.

    Returns:
        (N,2) float32 ndarray, 열 순서 [x_m, y_m].
        유효 점이 없으면 shape (0,2).
    """
    if scan is None or not scan.points:
        return np.empty((0, 2), dtype=np.float32)

    # --- 1·2단계: valid 필터 + range 필터 ---
    valid_angles: list[float] = []
    valid_dists: list[float] = []
    for pt in scan.points:
        if not pt.is_valid or pt.is_infinite:
            continue
        d = pt.distance_m
        if d < min_range_m or d > max_range_m:
            continue
        valid_angles.append(pt.angle_deg)
        valid_dists.append(d)

    if not valid_dists:
        return np.empty((0, 2), dtype=np.float32)

    angles_deg = np.array(valid_angles, dtype=np.float64)
    dists_m = np.array(valid_dists, dtype=np.float64)

    # --- 3단계: NaN/Inf 제거 (numeric-coding §3) ---
    finite_mask = np.isfinite(angles_deg) & np.isfinite(dists_m)
    angles_deg = angles_deg[finite_mask]
    dists_m = dists_m[finite_mask]

    if len(dists_m) == 0:
        return np.empty((0, 2), dtype=np.float32)

    # --- 4단계: 3점 이동평균 (선택) ---
    if enable_average_filter and len(dists_m) >= _AVG_FILTER_WINDOW:
        kernel = np.ones(_AVG_FILTER_WINDOW, dtype=np.float64) / _AVG_FILTER_WINDOW
        # 'valid' 모드: 경계 제거 (ros_scan_bridge._apply_average_filter 와 동일 의미)
        dists_m = np.convolve(dists_m, kernel, mode="valid")
        # 각도 배열도 동일 크기로 잘라 중앙 정렬 (필터 지연 = (window-1)//2)
        offset = (_AVG_FILTER_WINDOW - 1) // 2
        angles_deg = angles_deg[offset : offset + len(dists_m)]

    if len(dists_m) == 0:
        return np.empty((0, 2), dtype=np.float32)

    # --- 5단계: 극→직교 변환 (deg→rad 경계에서 1회, numeric-coding §1) ---
    angles_rad = np.radians(angles_deg)  # deg→rad: 이 경계에서 1회
    x_m = dists_m * np.cos(angles_rad)
    y_m = dists_m * np.sin(angles_rad)

    pts = np.column_stack([x_m, y_m]).astype(np.float32)
    return pts
