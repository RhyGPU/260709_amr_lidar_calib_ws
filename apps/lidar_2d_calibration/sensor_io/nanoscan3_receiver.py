"""SICK nanoScan3 UDP 수신기 — WP3 산출물.

FragmentAssembler: UDP 분편 조립 (다중 identification 동시 추적).
NanoScan3Receiver: 소켓 수신 루프 + 조립 + 파싱 + 스냅샷 보관.

의존 (WP2 산출물):
    from sensor_io.nanoscan3_protocol import DataParser, ScanData

WP2 파일이 없을 때는 해당 클래스가 존재하지 않으므로 NanoScan3Receiver 인스턴스화
시점에 ImportError 가 발생한다. 이는 의도된 동작이며, WP2 완료 전에는 mock 을 주입
하여 테스트해야 한다 (tests/test_receiver.py 의 MockParser 패턴 참조).

동시성 원칙 (concurrency-coding.md §1~§2):
    - latest_scan 은 단일 writer(수신 스레드)만 갱신한다.
    - 독자(UI 폴링, get_latest_scan)는 scan_lock 을 획득 후 읽는다.
    - lock 보유 중 blocking 호출(소켓 수신, 파싱, logging)은 절대 하지 않는다.
    - FragmentAssembler 내부 lock 은 어셈블러 전용 자원만 보호하며,
      scan_lock 과 동시에 획득하지 않으므로 deadlock 위험이 없다.
"""

import logging
import socket
import struct
import threading
import time
from collections import defaultdict
from typing import Dict, Optional

# ---------------------------------------------------------------------------
# WP2 의존 — 파일이 없을 때는 ImportError 를 caller 에게 전파한다.
# 테스트에서는 MockParser + mock ScanData 로 대체하여 WP2 없이 동작 가능.
# ---------------------------------------------------------------------------
try:
    from sensor_io.nanoscan3_protocol import DataParser, ScanData  # WP2 산출물
except ImportError:  # pragma: no cover
    DataParser = None  # type: ignore[assignment,misc]
    ScanData = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 프로토콜 상수 (ADR-002 / nanoscan3_view.py 원본 일치)
# ---------------------------------------------------------------------------
_DATAGRAM_MARKER: bytes = b"MS3 "  # 0x4D533320, Big-Endian 4 bytes
_DATAGRAM_HEADER_SIZE: int = 24  # UDP datagram header 크기 (bytes)

# DerivedValues 빔 수 sanity 상한 (SICK 라이브러리 기준)
_MAX_BEAM_COUNT: int = 2751


class FragmentAssembler:
    """UDP 분편(fragment) 조립기.

    nanoScan3 는 하나의 scan 데이터를 여러 UDP 패킷으로 나눠 전송한다.
    각 패킷은 identification(4 bytes LE)으로 같은 scan 묶음을 공유하고,
    fragment_offset 으로 조각의 위치를 알린다.

    동시성 주의:
        - self.fragments / self.total_lengths / self.timestamps 는
          self._lock 으로 보호된다 (단일 writer: 수신 스레드).
        - add_fragment() 내부에서 lock 을 보유하는 동안 blocking 호출을
          하지 않는다 (_cleanup_expired 는 순수 메모리 연산).
    """

    def __init__(self, timeout_s: float = 1.0) -> None:
        """
        Args:
            timeout_s: 불완전한 identification 을 폐기하는 경과 시간 (초).
                       패킷 유실로 조립이 완료되지 않는 경우를 정리한다.
        """
        # 단일 writer(수신 스레드) 원칙 — 그럼에도 lock 보호(방어적 설계)
        self._lock: threading.Lock = threading.Lock()
        self._fragments: Dict[int, Dict[int, bytes]] = defaultdict(dict)
        self._total_lengths: Dict[int, int] = {}
        self._timestamps: Dict[int, float] = {}
        self.timeout_s: float = timeout_s

    def add_fragment(
        self,
        identification: int,
        fragment_offset: int,
        total_length: int,
        payload: bytes,
    ) -> Optional[bytes]:
        """분편을 추가하고, scan 이 완성되면 조립된 bytes 를 반환한다.

        Args:
            identification: UDP 헤더 Identification 필드 (4 bytes LE).
            fragment_offset: 이 분편의 데이터 시작 오프셋 (bytes).
            total_length: 완성된 scan 의 전체 바이트 길이.
            payload: 이 분편의 데이터 (UDP datagram header 이후 부분).

        Returns:
            완성된 scan bytes (total_length 로 trim). 미완성이면 None.

        Note:
            lock 보유 구간은 메모리 연산만 수행한다 (blocking 없음).
        """
        with self._lock:
            self._cleanup_expired()

            self._fragments[identification][fragment_offset] = payload
            self._total_lengths[identification] = total_length
            self._timestamps[identification] = time.monotonic()

            current_len = sum(len(p) for p in self._fragments[identification].values())

            if current_len >= total_length:
                sorted_offsets = sorted(self._fragments[identification].keys())
                assembled = b"".join(
                    self._fragments[identification][off] for off in sorted_offsets
                )[:total_length]

                # 완성 즉시 메모리 정리
                del self._fragments[identification]
                del self._total_lengths[identification]
                del self._timestamps[identification]

                return assembled

        return None

    def _cleanup_expired(self) -> None:
        """timeout 이 지난 미완성 identification 을 폐기한다.

        호출 전제: self._lock 이 이미 획득된 상태여야 한다.
        """
        now = time.monotonic()
        expired = [
            ident
            for ident, ts in self._timestamps.items()
            if now - ts > self.timeout_s
        ]
        for ident in expired:
            self._fragments.pop(ident, None)
            self._total_lengths.pop(ident, None)
            self._timestamps.pop(ident, None)
            logger.debug("FragmentAssembler: identification=%d 타임아웃 폐기", ident)


class NanoScan3Receiver:
    """SICK nanoScan3 단일 센서 UDP 수신기.

    다중 인스턴스 생성이 가능하다 (센서별 포트 또는 source_ip 구분).

    사용 예::

        receiver = NanoScan3Receiver(
            local_ip="0.0.0.0",
            local_port=6060,
            source_ip_filter="192.168.192.100",
        )
        receiver.start()
        ...
        scan = receiver.get_latest_scan()
        connected, age_s = receiver.get_health()
        receiver.stop()

    동시성 (ADR-002 / concurrency-coding.md):
        - latest_scan 은 수신 스레드만 갱신 (단일 writer).
        - 독자는 scan_lock 획득 후 참조를 복사한다.
        - scan_lock 보유 중 소켓 I/O, 파싱, logging 을 수행하지 않는다.
        - FragmentAssembler 의 내부 lock 과 scan_lock 은 중첩 획득하지 않는다.

    WP2 의존:
        DataParser, ScanData 는 sensor_io.nanoscan3_protocol 에서 import 한다.
        WP2 파일이 없으면 start() 호출 전까지는 에러가 발생하지 않으나,
        _process_packet() 에서 DataParser 인스턴스가 없어 파싱이 스킵된다.
        (parser 주입 인터페이스로 테스트에서 MockParser 를 사용한다.)
    """

    # 워치독 connected 판정 기준 (초): 마지막 수신 후 이 시간 초과 시 disconnected
    _WATCHDOG_TIMEOUT_S: float = 3.0

    def __init__(
        self,
        local_ip: str = "0.0.0.0",
        local_port: int = 6061,
        source_ip_filter: Optional[str] = None,
        *,
        fragment_timeout_s: float = 1.0,
        recv_buf_bytes: int = 4 * 1024 * 1024,
        watchdog_timeout_s: float = 3.0,
        _parser=None,  # 테스트 주입용 (MockParser); None 이면 DataParser() 사용
    ) -> None:
        """
        Args:
            local_ip: 바인딩할 로컬 IP. 기본 "0.0.0.0" (모든 인터페이스).
            local_port: 바인딩할 UDP 포트.
            source_ip_filter: 지정 시 이 IP 에서 온 패킷만 수락
                              (discriminate_by='source_ip' 지원).
                              None 이면 모든 source 허용.
            fragment_timeout_s: FragmentAssembler 미완성 폐기 타임아웃 (초).
            recv_buf_bytes: 소켓 수신 버퍼 크기.
            watchdog_timeout_s: get_health() connected=True 판정 기준 (초).
            _parser: 테스트 전용 parser 주입 (Mock 사용 시). None 이면 DataParser().
        """
        self._local_ip: str = local_ip
        self._local_port: int = local_port
        self._source_ip_filter: Optional[str] = source_ip_filter
        self._recv_buf_bytes: int = recv_buf_bytes
        self._watchdog_timeout_s: float = watchdog_timeout_s

        self._assembler: FragmentAssembler = FragmentAssembler(
            timeout_s=fragment_timeout_s
        )

        # WP2 DataParser 주입 (테스트용 mock 또는 실제 구현)
        if _parser is not None:
            self._parser = _parser
        elif DataParser is not None:
            self._parser = DataParser()
        else:
            # WP2 미설치 — 파싱 스킵 (수신 루프는 동작하지만 scan 은 None 유지)
            logger.warning(
                "sensor_io.nanoscan3_protocol 을 찾을 수 없습니다 (WP2 미완료). "
                "패킷 수신은 동작하나 파싱이 비활성화됩니다."
            )
            self._parser = None

        # 공유 가변 상태 — 단일 writer: 수신 스레드
        self._latest_scan: Optional[object] = None  # ScanData | None
        self._scan_lock: threading.Lock = threading.Lock()
        self._last_recv_time: Optional[float] = None  # monotonic, lock 불필요(float 원자적)

        # 수신 루프 제어
        self._running: bool = False
        self._recv_thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None

        # 통계 (단일 writer: 수신 스레드 — lock 없이 접근, 정밀도 불필요)
        self._packet_count: int = 0
        self._scan_count: int = 0

    # ------------------------------------------------------------------
    # 공개 인터페이스
    # ------------------------------------------------------------------

    def start(self) -> None:
        """소켓을 바인딩하고 수신 스레드를 시작한다.

        이미 start() 가 호출된 상태면 경고만 기록하고 무시한다.

        Raises:
            OSError: 포트 바인딩 실패 시 (이미 사용 중 등).
        """
        if self._running:
            logger.warning(
                "NanoScan3Receiver(%s:%d) 이미 실행 중입니다.",
                self._local_ip,
                self._local_port,
            )
            return

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self._recv_buf_bytes)
        self._sock.settimeout(1.0)  # recvfrom 블로킹 상한 — stop() 응답성 확보
        self._sock.bind((self._local_ip, self._local_port))

        logger.info(
            "NanoScan3Receiver 시작: %s:%d  source_filter=%s",
            self._local_ip,
            self._local_port,
            self._source_ip_filter or "any",
        )

        self._running = True
        self._recv_thread = threading.Thread(
            target=self._receive_loop,
            name=f"nanoscan3-recv-{self._local_port}",
            daemon=True,
        )
        self._recv_thread.start()

    def stop(self) -> None:
        """수신 루프를 종료하고 소켓을 닫는다."""
        self._running = False
        if self._recv_thread is not None:
            self._recv_thread.join(timeout=3.0)
            self._recv_thread = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None

        logger.info(
            "NanoScan3Receiver 종료: port=%d  packets=%d  scans=%d",
            self._local_port,
            self._packet_count,
            self._scan_count,
        )

    def get_latest_scan(self) -> Optional[object]:
        """가장 최근에 수신·조립된 ScanData 를 반환한다.

        Returns:
            ScanData 인스턴스 또는 수신 전이면 None.

        Note:
            scan_lock 을 획득하여 참조를 읽는다. ScanData 는 immutable 로
            취급되므로 참조 복사만으로 충분하다 (deep-copy 불필요).
        """
        with self._scan_lock:
            return self._latest_scan

    def get_health(self) -> tuple[bool, float]:
        """워치독 상태를 반환한다.

        Returns:
            (connected, age_s) 튜플:
                - connected (bool): age_s < watchdog_timeout_s 이면 True.
                - age_s (float): 마지막 scan 수신 이후 경과 시간 (초).
                  수신 이력이 없으면 inf.

        Note:
            _last_recv_time 은 float 단일 대입이므로 GIL 하에서
            lock 없이 읽어도 안전하다. (CPython 구현 가정 — 이식성 우려 시
            scan_lock 으로 감쌀 수 있다.)
        """
        last = self._last_recv_time
        if last is None:
            return False, float("inf")
        age_s = time.monotonic() - last
        connected = age_s < self._watchdog_timeout_s
        return connected, age_s

    # ------------------------------------------------------------------
    # 내부 구현
    # ------------------------------------------------------------------

    def _receive_loop(self) -> None:
        """소켓에서 UDP 패킷을 읽어 _process_packet 으로 전달하는 루프.

        수신 스레드에서만 실행된다 (단일 writer 보장).
        예외는 로그를 남기고 루프를 유지한다.
        """
        assert self._sock is not None  # start() 선행 보장
        while self._running:
            try:
                data, addr = self._sock.recvfrom(65535)
                self._packet_count += 1
                source_ip: str = addr[0]

                # source_ip_filter: 지정된 IP 가 아니면 무시
                if self._source_ip_filter is not None and source_ip != self._source_ip_filter:
                    logger.debug(
                        "source_ip_filter: %s 로부터의 패킷 무시 (허용=%s)",
                        source_ip,
                        self._source_ip_filter,
                    )
                    continue

                self._process_packet(data)

            except socket.timeout:
                continue  # stop() 플래그 재확인
            except Exception as exc:  # noqa: BLE001
                if self._running:
                    logger.error("수신 루프 오류: %s", exc)

    def _process_packet(self, data: bytes) -> None:
        """단일 UDP 패킷을 파싱·조립하고, scan 완성 시 latest_scan 을 갱신한다.

        신뢰경계 입력 방어 (ADR-002):
            - 길이 sanity: DATAGRAM_HEADER_SIZE 미만이면 폐기.
            - 마커 sanity: 'MS3 ' 불일치이면 폐기.
            - total_length sanity: 0 이면 폐기.

        수신 스레드에서만 호출되므로 latest_scan 갱신이 단일 writer 원칙을
        준수한다. scan_lock 은 최소 범위(대입 1줄)만 보호한다.

        Args:
            data: recvfrom 으로 받은 raw UDP payload.
        """
        # --- 신뢰경계 방어 ---
        if len(data) < _DATAGRAM_HEADER_SIZE:
            logger.debug("패킷 길이 부족: %d bytes — 폐기", len(data))
            return

        if data[:4] != _DATAGRAM_MARKER:
            logger.debug("잘못된 datagram marker — 폐기")
            return

        # UDP datagram header 파싱 (nanoscan3_view.py 원본 동일)
        total_length: int = struct.unpack("<I", data[8:12])[0]
        identification: int = struct.unpack("<I", data[12:16])[0]
        fragment_offset: int = struct.unpack("<I", data[16:20])[0]

        if total_length == 0:
            logger.debug("total_length=0 — 폐기")
            return

        payload: bytes = data[_DATAGRAM_HEADER_SIZE:]

        # --- 분편 조립 ---
        complete_data = self._assembler.add_fragment(
            identification, fragment_offset, total_length, payload
        )

        if complete_data is None:
            return  # 아직 조립 미완성

        # --- 파싱 ---
        if self._parser is None:
            return  # WP2 미설치

        try:
            scan = self._parser.parse(complete_data)
        except Exception as exc:  # noqa: BLE001
            logger.error("파싱 오류: %s", exc)
            return

        if scan is None:
            return

        # 빔 수 sanity (DataParser 가 이미 검사하지만 방어적 이중 확인)
        points = getattr(scan, "points", None)
        if not points:
            return
        if len(points) > _MAX_BEAM_COUNT:
            logger.warning("빔 수 초과: %d > %d — 폐기", len(points), _MAX_BEAM_COUNT)
            return

        # --- latest_scan 갱신 (단일 writer: 수신 스레드 / lock 최소 범위) ---
        with self._scan_lock:
            self._latest_scan = scan

        # lock 밖에서 비원자적 연산 수행 (통계·시간 갱신)
        self._scan_count += 1
        self._last_recv_time = time.monotonic()

        if self._scan_count % 20 == 0:
            valid = sum(1 for p in points if getattr(p, "valid", True))
            logger.info(
                "Scan #%d: %d/%d pts, port=%d",
                self._scan_count,
                valid,
                len(points),
                self._local_port,
            )
