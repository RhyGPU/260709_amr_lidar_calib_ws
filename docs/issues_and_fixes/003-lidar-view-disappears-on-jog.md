# ISSUE-003: 캘리브레이션 앱에서 jog/각도 변경 시 LiDAR 스캔이 사라짐 (영구)

## 증상
- 스캔이 표시되던 중, jog 각도를 바꾸거나(예: Yaw +0.5) Flip/Load Initial TF를 누르는 순간 **모든 LiDAR 시각이 사라짐**.
- **각도를 0으로 되돌려도 복구되지 않음** (영구적). 원본 앱에서도 재현(내 auto-fit/range 변경과 무관).

## 원인 (진짜 원인 — 정정)
- **paintEvent 크래시**: `ui/scan_canvas.py`의 `_draw_sensor_crosshairs`에서
  `p.drawPolygon(QPointF(ex,ey), QPointF(lx,ly), QPointF(rx,ry))` 호출.
  PySide6의 `QPainter.drawPolygon()`은 **개별 QPointF 인자를 받지 않음** → `TypeError: too many arguments`.
- 이 코드는 `_sensor_front_pos`가 설정된 뒤(=최초 jog/flip/Load TF 이후)에만 실행됨. 그 시점부터 **매 repaint마다 예외** → 이후 레이어(스캔 점)가 전혀 그려지지 않음. 센서 위치는 계속 설정돼 있어 각도를 되돌려도 예외 지속 → 복구 불가. ✓(`scan_canvas.py:_draw_sensor_crosshairs`, 오프스크린 `grab()`로 재현한 traceback)
- 초기 스캔(‑jog 전)에는 `_sensor_front_pos=None`이라 크래시 없음 → "그러다 각도 만지면 죽는다"는 증상과 정확히 일치.

## 해결
- `p.drawPolygon(QPolygonF([QPointF(ex,ey), QPointF(lx,ly), QPointF(rx,ry)]))`로 수정 + `QPolygonF` import 추가. (`ui/scan_canvas.py`)
- (부가 UX 개선, 별개) `config/sensors.yaml` `max_range_m` 5→40, canvas robust auto-fit(중앙값·90퍼센타일 기반, 이상치 무시). — 근본 원인은 아니었음.

## 검증
- [x] SIL — 오프스크린 `ScanCanvas.grab()`(=paintEvent 강제)로 시퀀스 검증:
  initial(OK) → Load TF(이전=PAINT EXCEPTION → 수정후=OK) → yaw+0.5(OK) → revert 0(OK)
- [x] SIL — `py_compile` 통과
- [ ] HIL — 실제 GUI 창 육안 확인(사용자 확인 권장)

## 관련 작업
- [worklog 2026-07-09](../worklog/2026/07/2026-07-09.md)
