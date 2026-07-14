# ISSUE-001: 2번째 PC(노트북)에 2D LiDAR 데이터가 안 들어옴

## 증상
- USB-C 이더넷은 물리적으로 연결됐는데 LiDAR/로봇 데이터가 전혀 수신되지 않음.
- 캘리브레이션 뷰어(`nanoscan3_view.py`, `Lidarr_2d_Calibration_Window`)를 켜도 0 패킷.

## 원인
1. **서브넷 불일치**: USB-C 어댑터가 DHCP 부재로 link-local `169.254.98.86`을 자가할당. 로봇측 네트워크는 `192.168.192.0/24` (pktmon 캡처로 로봇이 `192.168.192.13`을 ARP 요청하는 것 확인). ✓(pktmon `amr_cap.etl`)
2. **스트림 대상 문제**: SICK 2D LiDAR의 `MS3 ` 측정 UDP는 설정된 목적지(=AMR 온보드 PC `192.168.192.5`)로만 unicast. 스위치드 LAN이라 `.13`으로는 flooding되지 않음. 뷰어들은 수동 리스너라 스스로 데이터를 요청하지 않음. ✓(discover.py 타임아웃 + 6060/6061 0패킷 + 과거 로그는 대상 머신에서만 정상 수신)

## 해결
- 어댑터에 정적 IP 부여: `netsh interface ipv4 add address name=38 address=192.168.192.13 mask=255.255.255.0`.
- LiDAR 데이터 획득 경로를 **SEER API(TCP 19204, msg 1009)** 로 확정 — 로봇이 이미 취합해 제공하며 개방 포트/무인증. WiFi(`192.168.44.82`) / 유선(`192.168.192.5`) 양쪽에서 동일 로봇 접근 가능.

## 검증
- [x] HIL — `192.168.192.5`/`192.168.44.82` ping + SEER 1000/1004/1009 응답 (model `Foil_A082`, ret_code 0)
- [x] LiDAR beams 수신: Front 520/~460 valid, Rear 520/~330 valid

## 관련 작업
- [worklog 2026-07-09](../worklog/2026/07/2026-07-09.md)
