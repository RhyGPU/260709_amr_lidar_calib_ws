#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SICK nanoScan3 Network Discovery Tool  - Windows 이식판 (WP9)

네트워크에서 nanoScan3 LiDAR 를 자동으로 찾아 IP·포트·시리얼·채널 정보를 출력합니다.

사용법:
    python tools/discover.py

기능:
    - COMMON_PORTS(6060, 6061, 2111, 2112, 2115) 순차 스캔
    - 발견된 각 센서의 IP·port·serial·channel 출력
    - 2-센서 환경(front/rear) 구분 안내(source IP 기반)
    - netifaces 설치 시 인터페이스 나열 / 미설치 시 socket fallback + 안내
    - Windows netsh 명령어로 IP 설정 안내(Linux ip/nmcli 출력 없음)
    - 타임아웃 내 미발견 시 안내 메시지 출력 후 정상 종료

패키지 의존:
    필수: (표준 라이브러리 전용 - 추가 설치 불필요)
    권장: pip install netifaces  (인터페이스 상세 정보)

좌표 규약 메모 (numeric-coding.md):
    nanoScan3 각도: start -47.5 deg, CCW+, 해상도 0.1667 deg/beam
    내부는 라디안 미사용 - 각도는 파싱 즉시 deg 보관, rad 변환은 캔버스 담당(WP7)
"""

import socket
import struct
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# 상수 (명명 상수 - 매직 넘버 금지, conventions.md SS3)
# ---------------------------------------------------------------------------
DATAGRAM_MARKER: bytes = b"MS3 "
DATAGRAM_HEADER_SIZE: int = 24  # bytes
DATA_HEADER_SIZE: int = 52  # bytes

# SICK nanoScan3 기본 송신 대상 포트 목록
COMMON_PORTS: List[int] = [6060, 6061, 2111, 2112, 2115]

# 포트당 수신 대기 시간 (초) - 짧게 유지하여 무한 대기 방지
DISCOVER_TIMEOUT_SEC: float = 4.0

# 2-센서 환경 예시 IP (front/rear 구분 안내용)
EXAMPLE_FRONT_IP: str = "192.168.192.100"
EXAMPLE_REAR_IP: str = "192.168.192.101"


# ---------------------------------------------------------------------------
# 데이터 클래스
# ---------------------------------------------------------------------------
@dataclass
class LiDARInfo:
    """발견된 LiDAR 한 대의 정보."""

    ip: str
    port: int
    serial_number: int = 0
    system_plug_serial: int = 0
    firmware_version: str = ""
    channel: int = 0
    first_seen: float = field(default_factory=time.time)
    packet_count: int = 1


@dataclass
class InterfaceInfo:
    """PC 네트워크 인터페이스 한 항목."""

    name: str
    ip: str
    netmask: str = "255.255.255.0"


# ---------------------------------------------------------------------------
# 인터페이스 열거 - netifaces 있으면 사용, 없으면 socket fallback
# ---------------------------------------------------------------------------
def get_local_interfaces() -> List[InterfaceInfo]:
    """PC 의 로컬 네트워크 인터페이스 목록 반환.

    netifaces 가 설치되어 있으면 상세 정보를 가져오고,
    없으면 socket.gethostbyname_ex() fallback 을 사용한다.
    루프백(127.x)은 제외한다.

    Returns:
        InterfaceInfo 목록 (비어 있을 수 있음).
    """
    try:
        import netifaces  # 선택적 의존성

        result: List[InterfaceInfo] = []
        for iface_name in netifaces.interfaces():
            addrs = netifaces.ifaddresses(iface_name)
            if netifaces.AF_INET not in addrs:
                continue
            for addr in addrs[netifaces.AF_INET]:
                ip = addr.get("addr", "")
                if not ip or ip.startswith("127."):
                    continue
                result.append(
                    InterfaceInfo(
                        name=iface_name,
                        ip=ip,
                        netmask=addr.get("netmask", "255.255.255.0"),
                    )
                )
        return result

    except ImportError:
        print(
            "  [안내] netifaces 미설치 - socket fallback 사용.\n"
            "         더 정확한 인터페이스 정보를 원하면: pip install netifaces\n"
        )
        return _get_interfaces_via_socket()


def _get_interfaces_via_socket() -> List[InterfaceInfo]:
    """socket.gethostbyname_ex() 로 IP 목록을 가져온다 (네티페이스 없을 때 fallback).

    Returns:
        InterfaceInfo 목록. 실패 시 빈 리스트.
    """
    try:
        hostname = socket.gethostname()
        _, _, ip_list = socket.gethostbyname_ex(hostname)
        return [
            InterfaceInfo(name=f"({hostname})", ip=ip)
            for ip in ip_list
            if not ip.startswith("127.")
        ]
    except OSError as exc:
        print(f"  [경고] 인터페이스 조회 실패: {exc}")
        return []


# ---------------------------------------------------------------------------
# 패킷 파싱
# ---------------------------------------------------------------------------
def parse_lidar_packet(data: bytes, addr: tuple) -> Optional[LiDARInfo]:
    """UDP 패킷에서 LiDARInfo 를 파싱한다.

    Args:
        data: 수신된 UDP 페이로드.
        addr: (source_ip, source_port) 튜플.

    Returns:
        파싱 성공 시 LiDARInfo, 마커 불일치·길이 부족 시 None.
    """
    if len(data) < DATAGRAM_HEADER_SIZE + DATA_HEADER_SIZE:
        return None
    if data[:4] != DATAGRAM_MARKER:
        return None

    offset = DATAGRAM_HEADER_SIZE
    try:
        major_version = data[offset + 1]
        minor_version = data[offset + 2]
        release = data[offset + 3]
        serial_number = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        system_plug_serial = struct.unpack("<I", data[offset + 8 : offset + 12])[0]
        channel = data[offset + 12]

        return LiDARInfo(
            ip=addr[0],
            port=addr[1],
            serial_number=serial_number,
            system_plug_serial=system_plug_serial,
            firmware_version=f"{major_version}.{minor_version}.{release}",
            channel=channel,
        )
    except (struct.error, IndexError):
        # 헤더 파싱 실패 - IP/포트만 보존
        return LiDARInfo(ip=addr[0], port=addr[1])


# ---------------------------------------------------------------------------
# 포트 단일 스캔
# ---------------------------------------------------------------------------
def scan_port(port: int, timeout_sec: float = DISCOVER_TIMEOUT_SEC) -> Optional[LiDARInfo]:
    """단일 포트에서 LiDAR 패킷 수신을 시도한다.

    Args:
        port: 바인딩할 UDP 포트 번호.
        timeout_sec: 수신 대기 최대 시간(초).

    Returns:
        발견된 LiDARInfo, 타임아웃 또는 바인딩 실패 시 None.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError as exc:
        print(f"  [오류] 소켓 생성 실패: {exc}")
        return None

    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
    sock.settimeout(1.0)  # 폴링 간격 1 초

    try:
        sock.bind(("0.0.0.0", port))
    except OSError as exc:
        print(f"  [경고] 포트 {port} 바인딩 실패: {exc}")
        sock.close()
        return None

    print(f"  포트 {port} 대기 중 (최대 {timeout_sec:.0f}초)...", end="", flush=True)

    deadline = time.monotonic() + timeout_sec
    found: Optional[LiDARInfo] = None

    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        print(f"\r  포트 {port} 대기 중 (남은 {remaining:.0f}초)...   ", end="", flush=True)
        try:
            data, addr = sock.recvfrom(65535)
            if data[:4] == DATAGRAM_MARKER:
                found = parse_lidar_packet(data, addr)
                if found:
                    break
        except socket.timeout:
            continue
        except OSError as exc:
            print(f"\n  [오류] 수신 실패: {exc}")
            break

    print()  # 진행률 줄 마무리
    sock.close()
    return found


# ---------------------------------------------------------------------------
# 출력 헬퍼
# ---------------------------------------------------------------------------
def _separator(char: str = "-", width: int = 60) -> None:
    print(char * width)


def print_banner() -> None:
    _separator("=")
    print("  SICK nanoScan3 Network Discovery Tool  [WP9 / Windows]")
    _separator("=")
    print()


def print_interfaces(interfaces: List[InterfaceInfo]) -> None:
    """현재 PC 의 네트워크 인터페이스를 출력한다."""
    print("[현재 PC 네트워크 인터페이스]")
    _separator()
    if not interfaces:
        print("  (인터페이스 정보 없음 - netifaces 설치 권장: pip install netifaces)")
    for iface in interfaces:
        print(f"  {iface.name}: {iface.ip}  (mask: {iface.netmask})")
    print()


def suggest_pc_ip(lidar_ip: str) -> str:
    """LiDAR IP 기반으로 같은 서브넷 PC IP 를 추천한다.

    Args:
        lidar_ip: LiDAR 의 IPv4 주소 문자열.

    Returns:
        추천 PC IP 문자열. 파싱 실패 시 '192.168.1.5'.
    """
    parts = lidar_ip.split(".")
    if len(parts) != 4:
        return "192.168.1.5"
    last = int(parts[3])
    suggested_last = 5 if last != 5 else 10
    return f"{parts[0]}.{parts[1]}.{parts[2]}.{suggested_last}"


def print_lidar_result(lidar: LiDARInfo, interfaces: List[InterfaceInfo]) -> None:
    """발견된 LiDAR 정보와 PC 설정 가이드를 출력한다."""
    print()
    _separator("=")
    print("  nanoScan3 LiDAR 발견!")
    _separator("=")
    print()

    print("[LiDAR 정보]")
    _separator()
    print(f"  IP 주소        : {lidar.ip}")
    print(f"  송신 포트      : {lidar.port}")
    print(f"  시리얼 번호    : {lidar.serial_number}")
    print(f"  시스템 플러그  : {lidar.system_plug_serial}")
    print(f"  펌웨어 버전    : {lidar.firmware_version}")
    print(f"  채널           : {lidar.channel}")
    print()

    lidar_subnet = ".".join(lidar.ip.split(".")[:3])
    matching = [ifc for ifc in interfaces if ".".join(ifc.ip.split(".")[:3]) == lidar_subnet]
    suggested_ip = suggest_pc_ip(lidar.ip)

    print("[권장 PC 네트워크 설정]")
    _separator()
    if matching:
        print(f"  PC 가 이미 같은 서브넷에 있습니다: {matching[0].ip}")
    else:
        print("  PC IP 를 아래와 같이 설정하세요 (Windows netsh):")
        print(f"    IP 주소       : {suggested_ip}")
        print("    서브넷 마스크 : 255.255.255.0")
        print(f"    게이트웨이    : {lidar_subnet}.1  (없으면 비워둠)")
        print()
        print("  [Windows 임시 IP 설정 - 관리자 PowerShell/명령 프롬프트]")
        print(
            f'    netsh interface ip set address "이더넷" static'
            f" {suggested_ip} 255.255.255.0 {lidar_subnet}.1"
        )
        print()
        print("  [영구 설정은 제어판 > 네트워크 어댑터 속성 > IPv4 에서 수행]")
    print()

    print("[수신기 실행 방법]")
    _separator()
    print(f"  python app.py   (기본 수신 포트: 6061)")
    print()


def print_dual_sensor_guide(sensors: List[LiDARInfo]) -> None:
    """2-센서(front/rear) 환경 구분 안내를 출력한다.

    nanoScan3 는 UDP 패킷 source IP 로 어느 센서인지 구분한다.
    LiDAR IP 는 SICK Safety Designer 에서 정적 할당하며, 아래는 프로젝트 예시이다.

    Args:
        sensors: 발견된 LiDARInfo 목록.
    """
    print("[2-센서 front / rear 구분 방법]")
    _separator()
    print(
        "  nanoScan3 UDP 패킷의 source IP 로 front / rear 를 판별합니다.\n"
        "  SICK Safety Designer 에서 각 센서에 고정 IP 를 할당하면 됩니다.\n"
    )
    print("  예시 (프로젝트 기본값 - Safety Designer 설정과 일치시킬 것):")
    print(f"    front LiDAR : {EXAMPLE_FRONT_IP}")
    print(f"    rear  LiDAR : {EXAMPLE_REAR_IP}")
    print()
    print("  sensor_io/config_loader.py 의 YAML 에서 ip 필드로 매핑합니다.")
    print("    sensors:")
    print(f"      front: {{ ip: \"{EXAMPLE_FRONT_IP}\", port: 6061 }}")
    print(f"      rear:  {{ ip: \"{EXAMPLE_REAR_IP}\",  port: 6061 }}")
    print()

    if len(sensors) >= 2:
        print("  [이번 탐색에서 발견된 센서 → 역할 추정]")
        for s in sensors:
            role = (
                "front (예시)"
                if s.ip == EXAMPLE_FRONT_IP
                else "rear (예시)"
                if s.ip == EXAMPLE_REAR_IP
                else "미지정 (Safety Designer 에서 IP 확인 필요)"
            )
            print(f"    {s.ip}:{s.port}  →  {role}")
        print()


def print_not_found_guide() -> None:
    """센서 미발견 시 확인 항목을 출력한다."""
    print()
    _separator("=")
    print("  nanoScan3 를 찾지 못했습니다 (타임아웃)")
    _separator("=")
    print()
    print("[확인 사항]")
    _separator()
    print("  1. LiDAR 전원이 켜져 있는지 확인")
    print("  2. 이더넷 케이블이 연결되어 있는지 확인")
    print("  3. LiDAR 가 UDP 를 전송하도록 설정되어 있는지 확인")
    print("     (SICK Safety Designer → 데이터 출력 설정)")
    print("  4. Windows Defender 방화벽이 UDP 포트를 허용하는지 확인:")
    print("     제어판 > Windows Defender 방화벽 > 고급 설정 > 인바운드 규칙")
    print(f"     허용 포트: {COMMON_PORTS}")
    print()
    print("[Windows 패킷 수신 확인 방법]")
    _separator()
    print("  # PowerShell (관리자) - UDP 포트 수신 대기 상태 확인")
    print("  netstat -an | findstr UDP")
    print()
    print("  # Wireshark 로 UDP 패킷 캡처 후 'MS3 ' 마커 필터:")
    print('  udp && frame[0:4] == 4d:53:33:20')
    print()
    print(
        "  # 포트 방화벽 임시 허용 (관리자 PowerShell):\n"
        "  New-NetFirewallRule -DisplayName 'NanoScan3' -Direction Inbound"
        " -Protocol UDP -LocalPort 6060,6061,2111,2112,2115 -Action Allow"
    )
    print()


# ---------------------------------------------------------------------------
# 복수 포트·복수 센서 탐색
# ---------------------------------------------------------------------------
def discover_all(
    ports: List[int] = COMMON_PORTS,
    timeout_per_port: float = DISCOVER_TIMEOUT_SEC,
) -> List[LiDARInfo]:
    """모든 COMMON_PORTS 를 순차 스캔하여 발견된 센서 목록을 반환한다.

    이미 발견된 IP 는 중복 추가하지 않는다.

    Args:
        ports: 스캔할 UDP 포트 번호 목록.
        timeout_per_port: 포트당 대기 시간(초).

    Returns:
        발견된 LiDARInfo 목록.
    """
    found: Dict[str, LiDARInfo] = {}  # key: "ip:port"

    for port in ports:
        lidar = scan_port(port, timeout_per_port)
        if lidar:
            key = f"{lidar.ip}:{lidar.port}"
            if key not in found:
                found[key] = lidar
                print(f"  -> 발견: {lidar.ip}  포트={lidar.port}  채널={lidar.channel}")
            # 2 센서 모두 발견되면 조기 종료 (선택적 최적화)
            if len(found) >= 2:
                break

    return list(found.values())


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------
def main() -> None:
    print_banner()

    interfaces = get_local_interfaces()
    print_interfaces(interfaces)

    print("[LiDAR 탐색 중...]")
    _separator()
    sensors = discover_all()

    if sensors:
        for sensor in sensors:
            print_lidar_result(sensor, interfaces)
        print_dual_sensor_guide(sensors)
    else:
        print_not_found_guide()


if __name__ == "__main__":
    main()
