# ISSUE-005: 캘리브레이션 앱 "Find" 버튼 크래시 (ModuleNotFoundError: tools.discover)

## 증상
- 앱 Network(UDP) 패널의 Find 클릭 시 워커 스레드가 크래시:
  `ModuleNotFoundError: No module named 'tools.discover'` (`ui/calibration_window.py:73` DiscoveryWorker.run).

## 원인
- 앱의 `tools/` 폴더에 `__init__.py`가 없어 **namespace 패키지**였고, PATH의 다른 정규 `tools` 패키지가 이를 shadow.
- 확인: `import tools` → `C:\...\Python314\site-packages\tools\__init__.py` (pip로 설치된 무관한 `tools` 패키지)로 해석됨. namespace 부분(앱 tools/)은 정규 패키지가 있으면 밀려남. ✓(import 경로 출력)

## 해결
- `apps/lidar_2d_calibration/tools/__init__.py` 추가 → 앱 tools/가 **정규 패키지**가 되어 sys.path[0](앱 루트)에서 우선 해석. (1 파일 추가)

## 검증
- [x] SIL — 앱 루트에서 `from tools.discover import scan_port` import OK (이전엔 ModuleNotFoundError)
- [ ] HIL — 실제 Find 클릭 육안(참고: 우리 셋업은 에미터 피드라 discovery보다 고정 포트 dock 권장)

## 관련 작업
- [worklog 2026-07-09](../worklog/2026/07/2026-07-09.md)
