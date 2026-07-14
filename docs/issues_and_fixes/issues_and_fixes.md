# Issues & Fixes

가장 최신 항목이 위. 상세는 `NNN-*.md` 참조.

---

## 2026-07-09

### [Fix] .bat 더블클릭 실행 안 됨 → LF 개행 ([ISSUE-006](006-calib-bat-crlf-launch.md))
- **문제**: `run_calibration_app.bat` 더블클릭 시 창만 깜빡이고 앱이 안 뜸(pause도 도달 못 함).
- **원인**: Write 도구 생성 .bat가 모두 LF(Unix) 개행. cmd.exe는 CRLF 기대 → 파싱 어긋남. + non-ASCII(em-dash).
- **해결**: `scripts/*.bat` 6개 CRLF 변환 + ASCII 치환. 검증: `cmd /c`로 앱 기동 + 520/520 pts 수신.
- **파일**: `scripts/*.bat` (6)
- **상태**: 완료

### [Fix] 앱 Find 크래시 → tools.discover shadow ([ISSUE-005](005-calib-find-tools-discover.md))
- **문제**: Find 클릭 시 `ModuleNotFoundError: No module named 'tools.discover'`.
- **원인**: 앱 `tools/`에 `__init__.py` 없어 namespace 패키지 → site-packages의 정규 `tools` 패키지가 shadow.
- **해결**: `apps/lidar_2d_calibration/tools/__init__.py` 추가(정규 패키지화). 검증: import OK.
- **파일**: `apps/lidar_2d_calibration/tools/__init__.py`
- **상태**: 완료(SIL; HIL 육안 대기)

### [Fix] LiDAR flicker/teleport → MTU초과+중복에미터+부분스캔 ([ISSUE-004](004-lidar-flicker-teleport.md))
- **문제**: 스캔이 튀고 깜빡임, 점 수 520↔338/339.
- **원인(3중)**: (1) 2180B>MTU 단일 datagram→broadcast 프래그먼트 유실, (2) 브리지 .bat 2창→에미터 2개 fragment 충돌, (3) SEER ~10% 부분 스캔(338/339 beams).
- **해결**: `ms3_emitter.py` 프래그먼트화 + 단일 인스턴스(이전 종료) + 부분 스캔 드롭; `run_lidar_bridge.bat` 자동재시작 loop 제거. 검증: broadcast 8s 전부 520pt, 0 flicker.
- **파일**: `amr_lidar/ms3_emitter.py`, `scripts/run_lidar_bridge.bat`
- **상태**: 완료

### [Fix] jog/각도 변경 시 LiDAR 스캔 영구 소실 → paintEvent 크래시 ([ISSUE-003](003-lidar-view-disappears-on-jog.md))
- **문제**: jog 각도/Flip/Load TF 순간 모든 스캔이 사라지고, 각도를 되돌려도 복구 안 됨(원본에서도 재현).
- **원인(진짜)**: `ui/scan_canvas.py:_draw_sensor_crosshairs`의 `p.drawPolygon(QPointF, QPointF, QPointF)` — PySide6는 개별 QPointF 인자 미지원 → `TypeError`. `_sensor_front_pos`가 최초 jog 이후 설정되면 매 repaint마다 예외 → 스캔 레이어 미렌더 → 영구.
- **해결**: `drawPolygon(QPolygonF([...]))` + `QPolygonF` import. (부가로 max_range 5→40, robust auto-fit — 근본원인 아님)
- **파일**: `Lidarr_2d_Calibration_Window/ui/scan_canvas.py` (+ `config/sensors.yaml`)
- **상태**: 완료 (SIL: 오프스크린 grab()로 paintEvent 재현·수정 확인; HIL 대기)

### [Fix] Windows UDP 릴레이 control loop 사망 ([ISSUE-002](002-udp-relay-wsaeconnreset.md))
- **문제**: 클라이언트 종료 후 새 auth 무응답, 릴레이 먹통.
- **원인**: 사라진 클라로의 `sendto` → 다음 `recvfrom`이 WSAECONNRESET(10054) → `except OSError: break`로 control 스레드 종료 — `amr_lidar/relay_server.py`.
- **해결**: `SIO_UDP_CONNRESET` 비활성화 + control loop에서 `ConnectionResetError`/`OSError` 무시(continue). (~8줄)
- **파일**: `amr_lidar/relay_server.py`
- **상태**: 완료 (SIL loopback 재현·검증)

### [Fix] 2번째 PC에 LiDAR 데이터 미수신 ([ISSUE-001](001-usb-ethernet-subnet-no-data.md))
- **문제**: USB-C 이더넷 연결됐으나 데이터 0.
- **원인**: 어댑터 link-local 자가할당(서브넷 불일치) + SICK MS3 UDP가 AMR PC(.5)로만 unicast(스위치드 LAN).
- **해결**: 정적 IP `192.168.192.13/24` 부여, LiDAR 획득을 **SEER API(19204/1009)** 경로로 확정(개방·무인증).
- **파일**: (네트워크 설정 / 신규 `amr_lidar` 툴셋)
- **상태**: 완료
