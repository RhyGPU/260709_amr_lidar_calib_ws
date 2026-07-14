"""SICK nanoScan3 MS3 MD 프로토콜 파서 (순수 파서 전용 모듈).

수신/socket/threading/FragmentAssembler/시각화는 포함하지 않는다 (WP3·WP7 담당).

데이터 구조 출처: SICK sick_safetyscanners_base 공개 라이브러리
  https://github.com/SICKAG/sick_safetyscanners_base

Data Header (52 bytes, fragment 조립 후):
  Offset 0:  VersionIndicator (1 byte)
  Offset 1:  MajorVersion (1 byte)
  Offset 2:  MinorVersion (1 byte)
  Offset 3:  Release (1 byte)
  Offset 4:  SerialNumberOfDevice (4 bytes, LE)
  Offset 8:  SerialNumberOfSystemPlug (4 bytes, LE)
  Offset 12: ChannelNumber (1 byte)
  Offset 16: SequenceNumber (4 bytes, LE)
  Offset 20: ScanNumber (4 bytes, LE)
  Offset 24: TimestampDate (2 bytes, LE)
  Offset 28: TimestampTime (4 bytes, LE)
  Offset 32: GeneralSystemStateBlockOffset/Size (각 2 bytes, LE)
  Offset 36: DerivedValuesBlockOffset/Size (각 2 bytes, LE)
  Offset 40: MeasurementDataBlockOffset/Size (각 2 bytes, LE)
  Offset 44: IntrusionDataBlockOffset/Size (각 2 bytes, LE)
  Offset 48: ApplicationDataBlockOffset/Size (각 2 bytes, LE)

DerivedValues Block (20 bytes 이상):
  Offset 0:  MultiplicationFactor (2 bytes, LE)
  Offset 2:  NumberOfBeams (2 bytes, LE)
  Offset 4:  ScanTime (2 bytes, LE)
  Offset 8:  StartAngle (4 bytes, LE, signed int32) — raw / 4_194_304 = 도(°)
  Offset 12: AngularBeamResolution (4 bytes, LE, signed int32) — raw / 4_194_304 = 도(°)
  Offset 16: InterbeamPeriod (4 bytes, LE)

MeasurementData Block:
  Offset 0:  NumberOfBeams (4 bytes, LE)
  Offset 4+: ScanPoint 배열 (각 4 bytes)
    bytes 0-1: Distance (uint16, LE) — mm
    byte  2:   Reflectivity (uint8)
    byte  3:   Status (uint8) — bit flags
      bit 0: valid
      bit 1: infinite
      bit 2: glare
      bit 3: reflector
      bit 4: contamination
"""

from __future__ import annotations

import logging
import math
import struct
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 상수 (magic number 금지 — conventions.md §3)
# ---------------------------------------------------------------------------

# UDP 데이터그램 마커 ("MS3 " = 0x4D533320, Big Endian)
DATAGRAM_MARKER: bytes = b"MS3 "

# UDP 데이터그램 헤더 크기 (bytes)
DATAGRAM_HEADER_SIZE: int = 24

# 조립 완료 데이터의 Data Header 크기 (bytes)
DATA_HEADER_SIZE: int = 52

# 각도 스케일: raw_int32 / ANGLE_SCALE = 도(°)
# numeric-coding §1: 내부 표현은 도(°), 변수명에 _deg 명시
ANGLE_SCALE: float = 4_194_304.0

# nanoScan3 최대 유효 빔 수 (SICK 라이브러리 sanity 기준)
_MAX_BEAM_COUNT: int = 2751


# ---------------------------------------------------------------------------
# 데이터클래스 (원본 nanoscan3_view.py 필드 유지)
# ---------------------------------------------------------------------------


@dataclass
class DataHeader:
    """조립 완료 데이터에서 파싱한 52-byte Data Header."""

    version_indicator: int = 0
    major_version: int = 0
    minor_version: int = 0
    release: int = 0
    serial_number_device: int = 0
    serial_number_plug: int = 0
    channel_number: int = 0
    sequence_number: int = 0
    scan_number: int = 0
    timestamp_date: int = 0
    timestamp_time: int = 0
    general_system_state_offset: int = 0
    general_system_state_size: int = 0
    derived_values_offset: int = 0
    derived_values_size: int = 0
    measurement_data_offset: int = 0
    measurement_data_size: int = 0
    intrusion_data_offset: int = 0
    intrusion_data_size: int = 0
    application_data_offset: int = 0
    application_data_size: int = 0


@dataclass
class DerivedValues:
    """DerivedValues 블록에서 파싱한 스캔 파라미터.

    각도 단위: 도(°) — numeric-coding §1 경계 변환 준수.
    """

    multiplication_factor: int = 1
    number_of_beams: int = 0
    scan_time: int = 0
    start_angle_deg: float = 0.0   # 도(°); raw / ANGLE_SCALE
    angular_resolution_deg: float = 0.0  # 도(°); raw / ANGLE_SCALE
    interbeam_period: int = 0


@dataclass
class ScanPoint:
    """단일 스캔 포인트.

    거리 단위: mm(raw) + m(변환) 병기 — numeric-coding §1.
    각도 단위: 도(°).
    """

    angle_deg: float = 0.0         # 도(°)
    distance_mm: int = 0           # mm (raw)
    distance_m: float = 0.0        # 미터 (mm / 1000.0) — numeric-coding §1 경계 변환
    reflectivity: int = 0
    # Status 비트 플래그
    is_valid: bool = True
    is_infinite: bool = False
    is_glare: bool = False
    is_reflector: bool = False
    is_contamination: bool = False


@dataclass
class ScanData:
    """완성된 1회 스캔 데이터 (파서 출력 단위)."""

    scan_number: int = 0
    derived_values: DerivedValues = field(default_factory=DerivedValues)
    points: List[ScanPoint] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 파서
# ---------------------------------------------------------------------------


class DataParser:
    """MS3 MD 조립 완료 바이트열 → ScanData 변환기.

    신뢰경계 입력 방어 (ADR-002 §신뢰경계, coding.md §3):
      - 최소 길이 검증
      - 마커('MS3 ') 검증
      - 빔 수 sanity (≤ 2751)
      - 모든 예외를 삼키고 None 반환 (부분 패킷 안전)

    수신/socket/threading 코드를 포함하지 않는다 (WP3 담당).
    """

    def parse(self, data: bytes) -> Optional[ScanData]:
        """바이트열을 파싱하여 ScanData를 반환한다.

        두 입력 형태를 모두 허용한다(seam 호환):
          1. **완전한 UDP 데이터그램** — 앞 24 bytes가 DATAGRAM_MARKER('MS3 ')로
             시작하는 헤더이고 그 뒤가 Data Header. (test/직접 호출 경로)
          2. **조립 완료 페이로드** — 데이터그램 헤더가 이미 제거되어 Data Header부터
             시작. NanoScan3Receiver가 24 bytes를 떼고 넘기는 **런타임 경로**.
        마커는 런타임 경로에서 수신기가 strip 전에 이미 검증하므로, 여기서는
        마커 유무로 strip 여부만 판단한다(마커 없는 페이로드를 거부하지 않는다).

        Args:
            data: 완전한 데이터그램 또는 Data Header부터 시작하는 조립 페이로드.

        Returns:
            성공 시 ScanData, 실패(길이 부족·빔수 이상) 시 None.
        """
        # --- 마커 유무로 데이터그램 헤더 strip 여부 결정 ---
        if len(data) >= 4 and data[:4] == DATAGRAM_MARKER:
            payload = data[DATAGRAM_HEADER_SIZE:]  # full datagram → strip 24B header
        else:
            payload = data  # already-assembled payload (receiver runtime path)

        # --- 신뢰경계 방어: Data Header 최소 길이 ---
        if len(payload) < DATA_HEADER_SIZE:
            logger.debug(
                "parse: payload too short (%d bytes, min %d)", len(payload), DATA_HEADER_SIZE
            )
            return None

        try:
            header = self._parse_data_header(payload)
            derived = self._parse_derived_values(payload, header)
            scan = ScanData(
                scan_number=header.scan_number,
                derived_values=derived,
            )
            self._parse_measurement_data(payload, header, derived, scan)
            return scan

        except Exception as exc:  # 신뢰경계 예외 삼킴
            logger.warning("parse: 파싱 실패 — %s", exc)
            return None

    # ------------------------------------------------------------------
    # 내부 파싱 메서드
    # ------------------------------------------------------------------

    def _parse_data_header(self, payload: bytes) -> DataHeader:
        """payload[0..51] → DataHeader (52 bytes).

        Args:
            payload: UDP 데이터그램 헤더(24 bytes) 이후의 바이트열.

        Returns:
            DataHeader 인스턴스.

        Raises:
            struct.error: 길이 부족 시.
        """
        hdr = DataHeader()
        hdr.version_indicator = payload[0]
        hdr.major_version = payload[1]
        hdr.minor_version = payload[2]
        hdr.release = payload[3]
        hdr.serial_number_device = struct.unpack_from("<I", payload, 4)[0]
        hdr.serial_number_plug = struct.unpack_from("<I", payload, 8)[0]
        hdr.channel_number = payload[12]
        # offset 13-15: reserved (1 byte + padding)
        hdr.sequence_number = struct.unpack_from("<I", payload, 16)[0]
        hdr.scan_number = struct.unpack_from("<I", payload, 20)[0]
        hdr.timestamp_date = struct.unpack_from("<H", payload, 24)[0]
        # offset 26-27: reserved
        hdr.timestamp_time = struct.unpack_from("<I", payload, 28)[0]
        hdr.general_system_state_offset = struct.unpack_from("<H", payload, 32)[0]
        hdr.general_system_state_size = struct.unpack_from("<H", payload, 34)[0]
        hdr.derived_values_offset = struct.unpack_from("<H", payload, 36)[0]
        hdr.derived_values_size = struct.unpack_from("<H", payload, 38)[0]
        hdr.measurement_data_offset = struct.unpack_from("<H", payload, 40)[0]
        hdr.measurement_data_size = struct.unpack_from("<H", payload, 42)[0]
        hdr.intrusion_data_offset = struct.unpack_from("<H", payload, 44)[0]
        hdr.intrusion_data_size = struct.unpack_from("<H", payload, 46)[0]
        hdr.application_data_offset = struct.unpack_from("<H", payload, 48)[0]
        hdr.application_data_size = struct.unpack_from("<H", payload, 50)[0]
        return hdr

    def _parse_derived_values(
        self, payload: bytes, header: DataHeader
    ) -> DerivedValues:
        """DerivedValues 블록 파싱 (20 bytes).

        블록 오프셋·크기가 0이면 기본값 DerivedValues를 반환한다.
        각도 변환: raw_int32 / ANGLE_SCALE = 도(°) (numeric-coding §1).

        Args:
            payload: Data Header 이후 바이트열 (Data Header 포함 원점 기준).
            header:  파싱 완료된 DataHeader.

        Returns:
            DerivedValues 인스턴스.
        """
        dv = DerivedValues()

        if header.derived_values_offset == 0 and header.derived_values_size == 0:
            return dv

        off = header.derived_values_offset
        # 최소 20 bytes 필요
        if off + 20 > len(payload):
            logger.debug(
                "_parse_derived_values: block out of range (offset=%d, payload_len=%d)",
                off,
                len(payload),
            )
            return dv

        dv.multiplication_factor = struct.unpack_from("<H", payload, off)[0]
        dv.number_of_beams = struct.unpack_from("<H", payload, off + 2)[0]
        dv.scan_time = struct.unpack_from("<H", payload, off + 4)[0]
        # offset+6, +7: reserved (2 bytes)
        start_angle_raw: int = struct.unpack_from("<i", payload, off + 8)[0]
        resolution_raw: int = struct.unpack_from("<i", payload, off + 12)[0]

        # NaN/Inf 방어: ANGLE_SCALE은 상수·0 아님 — 나눗셈 안전
        dv.start_angle_deg = start_angle_raw / ANGLE_SCALE
        dv.angular_resolution_deg = resolution_raw / ANGLE_SCALE

        dv.interbeam_period = struct.unpack_from("<I", payload, off + 16)[0]
        return dv

    def _parse_measurement_data(
        self,
        payload: bytes,
        header: DataHeader,
        derived: DerivedValues,
        scan: ScanData,
    ) -> None:
        """MeasurementData 블록 파싱 → scan.points에 ScanPoint를 추가한다.

        거리 변환: mm → m (distance_mm / 1000.0), numeric-coding §1.
        각도 누적: start_angle_deg + i * angular_resolution_deg (도(°)).

        신뢰경계 방어: 빔 수 > _MAX_BEAM_COUNT 이면 조기 반환.

        Args:
            payload:  Data Header 이후 바이트열.
            header:   DataHeader.
            derived:  DerivedValues.
            scan:     결과를 채울 ScanData (in-out).
        """
        if header.measurement_data_offset == 0 and header.measurement_data_size == 0:
            return

        off = header.measurement_data_offset
        if off + 4 > len(payload):
            return

        num_beams: int = struct.unpack_from("<I", payload, off)[0]

        # 신뢰경계 방어 3: 빔 수 sanity
        if num_beams > _MAX_BEAM_COUNT:
            logger.warning(
                "_parse_measurement_data: invalid beam count %d (max %d)",
                num_beams,
                _MAX_BEAM_COUNT,
            )
            return

        angle_deg: float = derived.start_angle_deg
        resolution_deg: float = derived.angular_resolution_deg

        for i in range(num_beams):
            point_off = off + 4 + i * 4
            if point_off + 4 > len(payload):
                # 페이로드 잘림 — 이후 빔 무시
                break

            distance_mm: int = struct.unpack_from("<H", payload, point_off)[0]
            reflectivity: int = payload[point_off + 2]
            status: int = payload[point_off + 3]

            # 거리 변환: mm → m (numeric-coding §1 경계 변환)
            # NaN/Inf 방어: distance_mm 은 uint16 (0..65535) — 나눗셈 안전
            distance_m: float = distance_mm / 1000.0

            point = ScanPoint(
                angle_deg=angle_deg,
                distance_mm=distance_mm,
                distance_m=distance_m,
                reflectivity=reflectivity,
                is_valid=bool(status & 0x01),
                is_infinite=bool(status & 0x02),
                is_glare=bool(status & 0x04),
                is_reflector=bool(status & 0x08),
                is_contamination=bool(status & 0x10),
            )
            scan.points.append(point)

            angle_deg += resolution_deg
