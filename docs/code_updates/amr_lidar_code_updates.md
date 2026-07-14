# amr_lidar — Code Updates

파일 단위 변경 이력. (이 워크스페이스는 아직 git 미초기화 — hash 생략)

## 2026-07-09 — LiDAR 깜빡임: 영속 버퍼 시도 → REVERTED
- [관찰] SEER front 가 ~3~4프레임마다 축소 FOV(339빔, -39.5°)를 전체(520빔, -130°)와 번갈아 반환.
- [시도→되돌림] `ms3_emitter.py`에 각도 bin 영속 버퍼(`merged()`) 추가 → emit은 520빔 고정됐으나 **앱 깜빡임 여전** → 사용자 요청으로 revert(원 raw-beam emit 복귀). 깜빡임 근본 원인은 emit 내용이 아님(전송/렌더 쪽 의심: MS3 datagram 2180B > MTU → IP 2분할, broadcast/WiFi 상 fragment 손실 시 프레임 드롭). 미해결 — 재현 환경(앱 위치/유니캐스트 vs 브로드캐스트) 확인 후 MS3 레벨 fragmentation(<MTU)로 정공법 예정.

## 2026-07-09 — flicker 완전 수정 (단일 인스턴스 + 부분 스캔 드롭)
- [수정] `amr_lidar/ms3_emitter.py` **단일 인스턴스 강제**: 새 에미터가 이전 에미터(temp PID 락파일)를 종료 → 항상 정확히 1개. 2개 이상이면 fragment 충돌로 338pt 손상. `run_lidar_bridge.bat`의 배치 자동재시작 loop 제거(두 창이 서로 싸우는 원인).
- [수정] `ms3_emitter.py` **부분 스캔 드롭**: SEER가 ~10% 확률로 338/339 beams(정상 520) 반환 → 화면 축소/flicker. 디바이스별 max beams의 90% 미만이면 그 프레임 스킵(consumer는 마지막 full scan 유지). 검증: broadcast 8s 전부 520pt, flicker 없음.
- [진단] 근본원인 3중: (1) MTU 초과 단일 datagram(→프래그먼트화), (2) 중복 에미터 충돌(→단일 인스턴스), (3) SEER 부분 스캔(→드롭). WiFi DHCP가 .21→.3로 변경됐지만 broadcast(.255)라 무관.

## 2026-07-09 — MS3 flicker/teleport 수정 (MTU 초과 → 프래그먼트화)
- [수정] `amr_lidar/ms3_emitter.py`: `build_ms3` → `build_ms3_datagrams` — 스캔(≈2180B)이 MTU(1500) 초과 단일 datagram이라 broadcast에서 IP 프래그먼트 유실 → flicker. MS3 프래그먼트(동일 identification, fragment_offset 증가, total_length 전체)로 분할(각 <1472B). 실 SICK 센서 동작과 동일, 앱 FragmentAssembler가 재조립. 검증: 2프래그(1424+780B), broadcast 재조립 20/20 안정, 520 pts.

## 2026-07-09 — 영구 LiDAR 도크 + Find 크래시 수정
- [수정] 앱 "Find"(DiscoveryWorker) `ModuleNotFoundError: tools.discover` — site-packages의 `tools` 패키지가 앱의 namespace `tools/`를 shadow. `apps/lidar_2d_calibration/tools/__init__.py` 추가로 정규 패키지화(sys.path[0] 우선). 검증: import OK.
- [추가] emitter 브로드캐스트 지원: `SO_BROADCAST` 소켓 옵션 (`amr_lidar/ms3_emitter.py`) — .255 목적지 허용.
- [추가] 영구 도크 런처 `scripts/run_lidar_bridge.bat` — SEER→MS3를 WiFi 서브넷(192.168.44.255:6060/6061)으로 브로드캐스트 + 자동 재시작. 어느 머신이든 0.0.0.0:port 바인드로 도크. 검증: 0.0.0.0 수신기가 520 pts/scan 수신.

## 2026-07-09 — 캘리브레이션 앱 사본 수정 (ISSUE-003)
- [수정] **paintEvent 크래시 fix**: `drawPolygon(QPointF,QPointF,QPointF)` → `drawPolygon(QPolygonF([...]))` + `QPolygonF` import (`Lidarr_2d_Calibration_Window/ui/scan_canvas.py`) — 진짜 근본 원인
- [수정] `max_range_m` 5.0 → 40.0 (`Lidarr_2d_Calibration_Window/config/sensors.yaml`) — 부가
- [추가] canvas robust auto-fit(중앙값·90퍼센타일): `_maybe_autofit`/`_fit_to_points`, wheel·pan 시 해제, reset_view 재활성 (`Lidarr_2d_Calibration_Window/ui/scan_canvas.py`) — 부가
- [추가] 앱 런처 (`scripts/run_calibration_app.bat`)

## 2026-07-09 — 워크스페이스 패키지화
- [추가] 공유 SEER 클라이언트 + 빔 변환 (`amr_lidar/seer_client.py`)
- [추가] 실시간 뷰어 (`amr_lidar/viewer.py`)
- [추가] SICK MS3 UDP 에미터 (`amr_lidar/ms3_emitter.py`)
- [추가] UDP 발행 릴레이 서버 (`amr_lidar/relay_server.py`)
- [추가] UDP 릴레이 클라이언트 (`amr_lidar/relay_client.py`)
- [추가] 패키지 초기화 (`amr_lidar/__init__.py`)
- [추가] 런처 4종 (`scripts/run_viewer.bat`, `run_ms3_emitter.bat`, `run_relay_server.bat`, `run_relay_client.bat`)
- [추가] 프로젝트 메타/문서 (`pyproject.toml`, `.gitignore`, `README.md`, `requirements.txt`, `docs/PROTOCOL.md`)

## 2026-07-09 — 릴레이 Windows 버그 수정 (ISSUE-002)
- [수정] `SIO_UDP_CONNRESET` 비활성화 + control loop ConnectionResetError/OSError 처리 (`amr_lidar/relay_server.py`)

## 2026-07-08 — 초기 도구 / 아티팩트
- [추가] SEER API 프로버, nanoScan3 UDP 프로버, CoLa2 프로버, SSH recon 등 (`tools/`)
- [추가] RViz 스타일 스냅샷 뷰 (`artifacts/amr_scan_view.html`)
- [추가] Seer-API.pdf 스펙 보존 (`docs/seer-api.pdf`)
