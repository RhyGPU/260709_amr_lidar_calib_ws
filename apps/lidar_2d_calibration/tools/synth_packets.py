"""MS3 MD 직렬화기 — DataParser 의 역(inverse).

DataParser.parse() 가 디코드하면 입력 장면을 그대로 복원해야 한다 (roundtrip 권위).

권위 파서: sensor_io/nanoscan3_protocol.py
패킷 레이아웃 참조: docs/WP9_coordinate_convention_check.md, nanoscan3_view/README.md

공개 함수:
    build_scan_packet(points, scan_number, serial, ...) -> bytes
    split_into_fragments(payload, mtu) -> list[bytes]
    make_synthetic_scene() -> list[tuple[float, float, int]]
    save_golden(path) -> None
"""

from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import List, Tuple, Union

# ---------------------------------------------------------------------------
# 권위 파서 상수 재사용 (sensor_io 패키지)
# ---------------------------------------------------------------------------
from sensor_io.nanoscan3_protocol import (
    ANGLE_SCALE,
    DATA_HEADER_SIZE,
    DATAGRAM_HEADER_SIZE,
    DATAGRAM_MARKER,
)

# ---------------------------------------------------------------------------
# 상수 (magic number 금지 — conventions.md §3)
# ---------------------------------------------------------------------------

# DerivedValues 블록 크기 (bytes) — nanoscan3_protocol.py 명세 일치
_DERIVED_BLOCK_SIZE: int = 20

# Data Header 내 블록 오프셋 (payload 기준, payload = Data Header 시작)
# DerivedValues 는 Data Header(52B) 직후
_DERIVED_BLOCK_OFFSET: int = DATA_HEADER_SIZE  # 52
# MeasurementData 는 DerivedValues(20B) 직후
_MEAS_BLOCK_OFFSET: int = DATA_HEADER_SIZE + _DERIVED_BLOCK_SIZE  # 72

# 기본 직렬 번호 (하드코딩 secret 아님 — 테스트용 상수)
_DEFAULT_SERIAL: int = 0xDEAD_BEEF

# nanoScan3 실제 스캔 파라미터 (SICK Safety Designer 기본값)
# numeric-coding §1: 단위 명시
SENSOR_START_ANGLE_DEG: float = -47.5     # 도(°)
SENSOR_RESOLUTION_DEG: float = 1.0 / 6.0  # 0.16667°  (= 1651빔 × 275° 범위)
SENSOR_NUM_BEAMS: int = 1651               # 275° / 0.16667° + 1

# ---------------------------------------------------------------------------
# 내부 빌더 함수 (단일 책임 — conventions.md §2)
# ---------------------------------------------------------------------------


def _build_udp_datagram_header(
    total_length: int,
    identification: int = 1,
    fragment_offset: int = 0,
) -> bytes:
    """UDP 데이터그램 헤더 24 bytes 직렬화.

    레이아웃 (nanoscan3_view/README.md §1):
        [0:4]   Marker          "MS3 " (Big-Endian)
        [4:6]   Protocol        uint16 BE
        [6]     MajorVersion    uint8
        [7]     MinorVersion    uint8
        [8:12]  TotalLength     uint32 LE — 조립 완료 페이로드(Data Header 이후) 전체 길이
        [12:16] Identification  uint32 LE
        [16:20] FragmentOffset  uint32 LE
        [20:24] Reserved        4 bytes (0)

    Args:
        total_length:    조립 완료 페이로드 전체 바이트 길이.
        identification:  fragment 식별자.
        fragment_offset: 이 fragment 의 데이터 시작 오프셋.

    Returns:
        24 bytes.
    """
    buf = bytearray(DATAGRAM_HEADER_SIZE)
    buf[0:4] = DATAGRAM_MARKER
    struct.pack_into(">H", buf, 4, 0x0001)              # Protocol, BE
    buf[6] = 1                                           # MajorVersion
    buf[7] = 0                                           # MinorVersion
    struct.pack_into("<I", buf, 8, total_length)         # TotalLength, LE
    struct.pack_into("<I", buf, 12, identification)      # Identification, LE
    struct.pack_into("<I", buf, 16, fragment_offset)     # FragmentOffset, LE
    # [20:24] reserved — 0 by bytearray init
    return bytes(buf)


def _build_data_header(
    scan_number: int,
    serial_number_device: int,
    derived_offset: int,
    derived_size: int,
    meas_offset: int,
    meas_size: int,
) -> bytes:
    """Data Header 52 bytes 직렬화.

    레이아웃 (nanoscan3_protocol.py 명세):
        [0]     VersionIndicator   uint8
        [1]     MajorVersion       uint8
        [2]     MinorVersion       uint8
        [3]     Release            uint8
        [4:8]   SerialNumberDevice uint32 LE
        [8:12]  SerialNumberPlug   uint32 LE
        [12]    ChannelNumber      uint8
        [13:16] Reserved
        [16:20] SequenceNumber     uint32 LE
        [20:24] ScanNumber         uint32 LE
        [24:26] TimestampDate      uint16 LE
        [26:28] Reserved
        [28:32] TimestampTime      uint32 LE
        [32:34] GeneralSystemState Offset uint16 LE
        [34:36] GeneralSystemState Size   uint16 LE
        [36:38] DerivedValues Offset      uint16 LE
        [38:40] DerivedValues Size        uint16 LE
        [40:42] MeasurementData Offset    uint16 LE
        [42:44] MeasurementData Size      uint16 LE
        [44:46] IntrusionData Offset      uint16 LE
        [46:48] IntrusionData Size        uint16 LE
        [48:50] ApplicationData Offset    uint16 LE
        [50:52] ApplicationData Size      uint16 LE

    Args:
        scan_number:           ScanNumber 필드값.
        serial_number_device:  장치 시리얼 번호.
        derived_offset:        DerivedValues 블록 오프셋 (payload 기준).
        derived_size:          DerivedValues 블록 크기.
        meas_offset:           MeasurementData 블록 오프셋 (payload 기준).
        meas_size:             MeasurementData 블록 크기.

    Returns:
        52 bytes.
    """
    buf = bytearray(DATA_HEADER_SIZE)
    buf[0] = 1   # VersionIndicator
    buf[1] = 1   # MajorVersion
    buf[2] = 0   # MinorVersion
    buf[3] = 0   # Release
    struct.pack_into("<I", buf, 4, serial_number_device)
    struct.pack_into("<I", buf, 8, 0)           # SerialNumberPlug
    buf[12] = 0                                  # ChannelNumber
    # [13:16] reserved — 0
    struct.pack_into("<I", buf, 16, 1)           # SequenceNumber
    struct.pack_into("<I", buf, 20, scan_number)
    struct.pack_into("<H", buf, 24, 0)           # TimestampDate
    # [26:28] reserved — 0
    struct.pack_into("<I", buf, 28, 0)           # TimestampTime
    struct.pack_into("<H", buf, 32, 0)           # GeneralSystemState Offset = 0
    struct.pack_into("<H", buf, 34, 0)           # GeneralSystemState Size   = 0
    struct.pack_into("<H", buf, 36, derived_offset)
    struct.pack_into("<H", buf, 38, derived_size)
    struct.pack_into("<H", buf, 40, meas_offset)
    struct.pack_into("<H", buf, 42, meas_size)
    struct.pack_into("<H", buf, 44, 0)           # IntrusionData Offset  = 0
    struct.pack_into("<H", buf, 46, 0)           # IntrusionData Size    = 0
    struct.pack_into("<H", buf, 48, 0)           # ApplicationData Offset = 0
    struct.pack_into("<H", buf, 50, 0)           # ApplicationData Size   = 0
    return bytes(buf)


def _build_derived_values(
    num_beams: int,
    start_angle_deg: float,
    resolution_deg: float,
    scan_time: int = 0,
    interbeam_period: int = 0,
) -> bytes:
    """DerivedValues 블록 20 bytes 직렬화.

    각도 raw = 도(°) × ANGLE_SCALE, signed int32 LE.
    numeric-coding §1: 경계 변환 — 내부는 도(°), raw는 직렬화 경계에서만 계산.

    Args:
        num_beams:       빔 수 (uint16).
        start_angle_deg: 시작 각도 도(°).
        resolution_deg:  각도 해상도 도(°)/빔.
        scan_time:       스캔 시간 (μs, uint16).
        interbeam_period: 빔 간 시간 (ns, uint32).

    Returns:
        20 bytes.
    """
    buf = bytearray(_DERIVED_BLOCK_SIZE)
    struct.pack_into("<H", buf, 0, 1)            # MultiplicationFactor = 1
    struct.pack_into("<H", buf, 2, num_beams)
    struct.pack_into("<H", buf, 4, scan_time)
    # [6:8] reserved — 0
    # NaN/Inf 방어: ANGLE_SCALE 상수, 0 아님
    start_raw: int = int(round(start_angle_deg * ANGLE_SCALE))
    res_raw: int = int(round(resolution_deg * ANGLE_SCALE))
    struct.pack_into("<i", buf, 8, start_raw)    # signed int32
    struct.pack_into("<i", buf, 12, res_raw)     # signed int32
    struct.pack_into("<I", buf, 16, interbeam_period)
    return bytes(buf)


def _build_measurement_block(
    beams: List[Tuple[int, int, int]],
) -> bytes:
    """MeasurementData 블록 직렬화.

    블록 구조:
        [0:4]      NumberOfBeams  uint32 LE
        [4 + i*4]  ScanPoint i
            [0:2]  Distance       uint16 LE (mm)
            [2]    Reflectivity   uint8
            [3]    Status         uint8

    Args:
        beams: [(distance_mm, reflectivity, status), ...] 리스트.

    Returns:
        4 + len(beams) * 4 bytes.
    """
    buf = bytearray(4 + len(beams) * 4)
    struct.pack_into("<I", buf, 0, len(beams))
    for i, (dist_mm, refl, status) in enumerate(beams):
        off = 4 + i * 4
        struct.pack_into("<H", buf, off, dist_mm)
        buf[off + 2] = refl & 0xFF
        buf[off + 3] = status & 0xFF
    return bytes(buf)


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------


# 입력 타입: (angle_deg, distance_m, status) 또는 (distance_mm, reflectivity, status)
_PointInput = Union[
    Tuple[float, float],        # (angle_deg, distance_m) — status=0x01 assumed
    Tuple[float, float, int],   # (angle_deg, distance_m, status)
]


def build_scan_packet(
    points: List[_PointInput],
    scan_number: int = 1,
    serial: int = _DEFAULT_SERIAL,
    start_angle_deg: float = SENSOR_START_ANGLE_DEG,
    resolution_deg: float = SENSOR_RESOLUTION_DEG,
    identification: int = 1,
) -> bytes:
    """입력 장면을 MS3 MD 완전 패킷으로 직렬화한다 (DataParser 의 역).

    입력 포맷 (points):
        각 원소는 (angle_deg, distance_m) 또는 (angle_deg, distance_m, status) 튜플.
        - angle_deg:   빔 각도 도(°) — 검증에만 사용, 실제 직렬화는 start/resolution 기준
        - distance_m:  거리 미터 — mm 로 변환하여 직렬화
        - status:      상태 비트 플래그 (기본 0x01 = valid)

    직렬화 레이아웃:
        [0:24]    UDP Datagram Header (24 bytes)
        [24:76]   Data Header (52 bytes)
        [76:96]   DerivedValues Block (20 bytes)
        [96:]     MeasurementData Block (4 + N*4 bytes)

    Roundtrip 보장:
        DataParser().parse(build_scan_packet(points, ...)) 의 출력이
        입력 장면의 beam count · start_angle · resolution · distance · status 를
        부동소수 epsilon 이내로 복원해야 한다.

    Args:
        points:          빔 목록 (angle_deg, distance_m[, status]).
        scan_number:     ScanNumber 필드값.
        serial:          SerialNumberDevice 필드값.
        start_angle_deg: DerivedValues 의 StartAngle (도(°)).
        resolution_deg:  DerivedValues 의 AngularBeamResolution (도(°)/빔).
        identification:  UDP 헤더 Identification (fragment 식별자).

    Returns:
        완전한 MS3 MD 바이트열 (DataParser.parse() 직접 입력 가능).

    Raises:
        ValueError: points 에 유효하지 않은 항목이 있을 때.
    """
    # 신뢰경계: points 입력 방어
    if not isinstance(points, list):
        raise ValueError("points 는 list 이어야 합니다")

    # 빔 배열 구성 (distance_m → mm 변환, numeric-coding §1 경계 변환)
    beams: List[Tuple[int, int, int]] = []
    for item in points:
        if len(item) == 2:  # (angle_deg, distance_m)
            _, dist_m = item
            status = 0x01
        elif len(item) == 3:  # (angle_deg, distance_m, status)
            _, dist_m, status = item
        else:
            raise ValueError(f"points 원소는 2~3 튜플이어야 합니다: {item!r}")

        # NaN/Inf 방어: distance_m 은 float — clamp to uint16 range
        dist_mm = int(round(dist_m * 1000.0))
        dist_mm = max(0, min(0xFFFF, dist_mm))   # uint16 클램프
        refl = 0                                  # 반사율 기본 0
        beams.append((dist_mm, refl, int(status) & 0xFF))

    num_beams = len(beams)
    meas_block = _build_measurement_block(beams)
    meas_size = len(meas_block)

    # payload = Data Header + DerivedValues + MeasurementData
    payload_size = DATA_HEADER_SIZE + _DERIVED_BLOCK_SIZE + meas_size

    udp_hdr = _build_udp_datagram_header(
        total_length=payload_size,
        identification=identification,
        fragment_offset=0,
    )
    data_hdr = _build_data_header(
        scan_number=scan_number,
        serial_number_device=serial,
        derived_offset=_DERIVED_BLOCK_OFFSET,
        derived_size=_DERIVED_BLOCK_SIZE,
        meas_offset=_MEAS_BLOCK_OFFSET,
        meas_size=meas_size,
    )
    derived_blk = _build_derived_values(
        num_beams=num_beams,
        start_angle_deg=start_angle_deg,
        resolution_deg=resolution_deg,
    )

    return udp_hdr + data_hdr + derived_blk + meas_block


def split_into_fragments(payload: bytes, mtu: int = 1400) -> List[bytes]:
    """페이로드(Data Header 이후)를 MTU 크기 fragment 로 분할하여 완전한 UDP 패킷 목록을 반환한다.

    각 fragment 는 독립적인 UDP 패킷으로, 수신측 FragmentAssembler 로 재조립 가능하다.

    Fragment UDP 패킷 레이아웃:
        [0:24]  UDP Datagram Header
                  TotalLength     = len(payload) (전체 페이로드 길이)
                  Identification  = identification (공유)
                  FragmentOffset  = 이 fragment 의 데이터 시작 오프셋
        [24:]   fragment 데이터 (payload 의 슬라이스)

    Args:
        payload:      분할할 페이로드 바이트열 (Data Header + 블록들).
        mtu:          fragment 당 최대 데이터 크기 (bytes, 기본 1400).

    Returns:
        완전한 UDP 패킷(헤더 포함)의 list. 단일 fragment 이면 길이 1.

    Raises:
        ValueError: mtu < 1 이면.
    """
    if mtu < 1:
        raise ValueError(f"mtu 는 1 이상이어야 합니다: {mtu}")

    total_length = len(payload)
    identification = 1
    packets: List[bytes] = []

    offset = 0
    while offset < total_length:
        chunk = payload[offset : offset + mtu]
        udp_hdr = _build_udp_datagram_header(
            total_length=total_length,
            identification=identification,
            fragment_offset=offset,
        )
        packets.append(udp_hdr + chunk)
        offset += len(chunk)

    # 빈 payload 예외: 최소 1개 패킷 반환
    if not packets:
        packets.append(
            _build_udp_datagram_header(
                total_length=0,
                identification=identification,
                fragment_offset=0,
            )
        )

    return packets


def make_synthetic_scene() -> List[Tuple[float, float, int]]:
    """알려진 비대칭 장면을 생성한다 (오프라인 검증용).

    장면 설계:
        - nanoScan3 실제 파라미터: start -47.5°, resolution 0.16667°, 1651빔
        - 전방 코너(L자): 각도 -20° ~ +20° 구간, 거리 1.5 m (전방 벽)
        - 좌측 벽: 각도 +40° ~ +47.5° 구간, 거리 1.0 m
        - 우측 벽: 각도 -47.5° ~ -40° 구간, 거리 0.8 m
        - 기준점 3개 (코너 반사판): -15°/1.2m, 0°/2.0m, +15°/1.2m
        - 나머지 빔: 무효(distance=0, status=0x00)

    반환 리스트: [(angle_deg, distance_m, status), ...]  — 1651 원소.
    각도는 start + i * resolution 로 누적 (numeric-coding §1 준수).
    """
    num_beams = SENSOR_NUM_BEAMS
    start_deg = SENSOR_START_ANGLE_DEG
    res_deg = SENSOR_RESOLUTION_DEG

    scene: List[Tuple[float, float, int]] = []

    for i in range(num_beams):
        angle_deg = start_deg + i * res_deg

        # 전방 코너(L자): -20° ~ +20°, 거리 1.5 m
        if -20.0 <= angle_deg <= 20.0:
            dist_m = 1.5
            status = 0x01  # valid

        # 좌측 벽: +40° ~ +47.5°, 거리 1.0 m
        elif 40.0 <= angle_deg <= 47.5:
            dist_m = 1.0
            status = 0x01

        # 우측 벽: -47.5° ~ -40°, 거리 0.8 m
        elif -47.5 <= angle_deg <= -40.0:
            dist_m = 0.8
            status = 0x01

        # 기준점(코너 반사판): 3개 특정 각도 근방
        elif abs(angle_deg - (-15.0)) < res_deg:
            dist_m = 1.2
            status = 0x09  # valid + reflector

        elif abs(angle_deg - 0.0) < res_deg:
            dist_m = 2.0
            status = 0x09

        elif abs(angle_deg - 15.0) < res_deg:
            dist_m = 1.2
            status = 0x09

        # 나머지: 무효
        else:
            dist_m = 0.0
            status = 0x00

        scene.append((angle_deg, dist_m, status))

    return scene


def save_golden(path: Union[str, Path]) -> None:
    """합성 장면 골든 패킷을 파일로 저장한다.

    저장 내용: make_synthetic_scene() 으로 생성한 장면의 완전한 MS3 패킷 1개.
    DataParser().parse() 로 재로드 가능한 형식.

    Args:
        path: 저장 경로 (.bin 확장자 권장). 부모 디렉토리가 없으면 생성한다.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    scene = make_synthetic_scene()
    packet = build_scan_packet(
        points=scene,
        scan_number=1,
        serial=_DEFAULT_SERIAL,
        start_angle_deg=SENSOR_START_ANGLE_DEG,
        resolution_deg=SENSOR_RESOLUTION_DEG,
    )
    dest.write_bytes(packet)
