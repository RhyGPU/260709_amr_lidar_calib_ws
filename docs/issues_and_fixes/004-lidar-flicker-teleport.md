# ISSUE-004: LiDAR 화면이 flicker/teleport (점이 사라졌다 나타났다, 점 수가 튐)

## 증상
- 캘리브레이션 앱(및 뷰어)에서 스캔이 순간순간 튀고 깜빡임. 점 수가 520 ↔ 338/339 로 급변.
- broadcast 브리지로 바꾼 뒤 특히 심함. unicast일 때는 상대적으로 덜함.

## 원인 (3중 — 패킷 레벨 추적으로 확정)
1. **MTU 초과 단일 datagram**: 520빔 스캔 ≈ 2180B > Ethernet MTU 1500. 단일 UDP datagram이 IP 프래그먼트됨. unicast는 OS가 재조립하지만 **broadcast는 IP 프래그먼트 유실**이 잦아 스캔 통째 손실 → 깜빡임. ✓(size 계산 + broadcast 재조립 실패 관측)
2. **중복 에미터 충돌**: `run_lidar_bridge.bat`가 배치 자동재시작 loop를 가져 창을 2개 열면 에미터 2개가 같은 포트로 broadcast. 각자 seq 카운터라 `identification` 충돌 → 앱 FragmentAssembler가 서로 다른 스캔의 프래그먼트를 섞어 조립 → 338pt 손상 + 순서 뒤섞임. ✓(raw 캡처: 두 seq 시퀀스 interleave)
3. **SEER 부분 스캔**: SEER API가 ~10% 확률로 338/339 beams 반환(정상 520). 연속 80회 폴링 = {520:72, 339:7, 338:1}. 에미터가 그대로 중계 → 화면 축소 = flicker. ✓(live 폴링 분포)

부수 관측: WiFi DHCP가 192.168.44.21 → .3 로 변경됨(broadcast .255 사용이라 동작엔 무관).

## 해결 (`amr_lidar/ms3_emitter.py`, `scripts/run_lidar_bridge.bat`)
1. **프래그먼트화**: `build_ms3` → `build_ms3_datagrams` — 스캔을 <MTU MS3 프래그먼트(동일 identification, fragment_offset 증가, total_length 전체)로 분할. 실 SICK 센서 동작과 동일, 앱이 재조립. 각 datagram <1472B.
2. **단일 인스턴스 강제**: 에미터 시작 시 이전 에미터(temp PID 락파일)를 SIGTERM으로 종료 → 항상 정확히 1개. 브리지 .bat의 자동재시작 loop 제거(두 창이 싸우는 원인).
3. **부분 스캔 드롭**: 디바이스별 관측 최대 빔의 90% 미만 프레임은 스킵(consumer는 마지막 full scan 유지).

## 검증
- [x] SIL — unicast localhost 단일 에미터: 전부 520pt (프래그먼트화 정합)
- [x] SIL — 단일 인스턴스: A 실행 후 B 실행 → B가 A 종료, python 1개만 잔존
- [x] HIL — broadcast 8초: 앱 재조립 결과 **전부 520pt, 0 flicker** (partial dropped 카운트 증가 로그 확인)
- [x] HIL — .bat 실행 앱이 "Scan #N: 520/520 pts" 수신

## 관련 작업
- [worklog 2026-07-09](../worklog/2026/07/2026-07-09.md)
