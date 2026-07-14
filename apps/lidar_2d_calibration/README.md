# 2D LiDAR Calibration (Windows, UDP)

SICK nanoScan3 전·후방 2D LiDAR(Light Detection And Ranging)의 외부 파라미터(extrinsic)
캘리브레이션 도구. **Windows 네이티브 Python + PySide6**, ROS2 비의존, **UDP(User Datagram
Protocol)** 직접 수신.

> 원본 ROS2 패키지 `lidar_calibration_2d`의 Windows 이식. 계획: [docs/PORTING_PLAN.md](docs/PORTING_PLAN.md).
> 결정 기록: [docs/adr/](docs/adr/). 함수 인덱스: [docs/FUNCTION_INDEX.md](docs/FUNCTION_INDEX.md).

## ⚠️ 강제력 정직 선언 (coding SOP §0)

이 저장소는 **CI(Continuous Integration) 미구성** 상태다. 코딩 가이드라인의 `⟦CI⟧` 태그는
이 환경에서 **pre-commit advisory 로 강등**되며 `--no-verify` 로 우회 가능 — 즉 **기계 강제력 = 0**.
규칙 텍스트만 생존한다. `✅` 는 "검사 통과"이지 "옳다"가 아니다(green ≠ good). **최종 verdict 는
저자가 못 찍는다**(never-self-approve) — 별도 리뷰 lane(`code_review` 번들/사람 PR)이 렌더한다.

## 구조

```
core/        # ROS-free 계산 코어 (ICP, TF 수학, region, engine) — scipy 제거
sensor_io/   # UDP 입력 (protocol, receiver, scan_source 계약, config_loader)
ui/          # PySide6 캔버스·윈도우
app.py       # Qt 단독 부트스트랩
config/      # sensors.yaml, calibration_result.yaml
tools/       # discover.py (센서 검색)
tests/       # 단위·통합 테스트
docs/        # PORTING_PLAN, adr/, FUNCTION_INDEX
```

## 의존성

```bash
pip install -r requirements.txt   # numpy, PySide6, PyYAML, (netifaces)
```

## 실행 (구현 완료 후)

```bash
python app.py                     # 캘리브레이션 GUI
python tools/discover.py          # 네트워크에서 nanoScan3 검색
```

## 개발 상태

WP(Work Package)별 진행은 [docs/PORTING_PLAN.md](docs/PORTING_PLAN.md) §4 참조.
- ✅ WP1: 스캐폴드·ADR·인터페이스 계약·core 이식(scipy 제거)
- 🔲 WP2~WP10: 진행 중

## 코딩 규칙

`Sensor/docs/claude_guideline/coding/` SOP 준수. 포맷터: black/isort(`pyproject.toml`).
변경 공개함수마다 테스트 ≥ 1, ADR 로 비가역·의존성 변경 기록.
