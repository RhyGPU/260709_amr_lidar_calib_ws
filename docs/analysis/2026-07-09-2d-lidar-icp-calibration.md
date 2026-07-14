# 2D LiDAR ICP 외부 캘리브레이션 분석 (Foil_A082, front↔rear)

작성: 2026-07-09 (KST). 대상: `apps/lidar_2d_calibration` 로 front/rear TiM320 을 merged_lidar 프레임에 정렬.

## 1. 목적
front(고정 기준)에 rear 를 ICP 로 정렬하여 두 2D LiDAR 를 하나의 스캔으로 합치기 위한 외부 파라미터(merged→rear TF) 산출. 합쳐진 스캔은 매핑/측위/장애물 감지에 사용되므로 **cm 단위 오차가 곧 벽 ghosting → 품질 저하**.

## 2. 결과 요약 (run 별, merged→rear)

| Run | 수렴 region | correspondences | mean_dist | rear after ICP (tx, ty, yaw) | ICP 보정(dx,dy,dyaw) |
|-----|------------|-----------------|-----------|------------------------------|----------------------|
| 1 | 1/2 | 45 | 0.0376 m | (~,~,~) | 0.009, -0.013, 0.223° |
| 2 | 1/3 | 30 | 0.0467 m | -0.8465, 0.5058, 135.59° | 0.036, -0.064, 0.593° |
| 3 | 1/3 | 30 | 0.0552 m | -0.8673, 0.5351, 135.56° | (별건, 아래) |
| 3' | 1/1 | **64** | 0.0552 m | -0.8673, 0.5351, 135.56° | -0.019, 0.037, -0.070° |

- **yaw 수렴**: 135.56~135.59° 로 안정 → 회전 자유도는 잡힘.
- **translation 미수렴**: ty 가 run 마다 0.506→0.535 로 흔들림. cm 단위 잔차.

## 3. 품질 평가 — cm 는 큰 오차
- **mean_dist(잔차) 3.8~5.5 cm**: 정렬 후에도 두 스캔 점군이 평균 수 cm 벌어짐. TiM320 노이즈(~1-3 cm) 를 크게 상회 → **아직 정렬 부족**. 목표는 **≤ ~2 cm**.
- **비대칭(rear vs 이상적 대칭)**: Run 3' 기준 Δtx=1.4 cm, **Δty=4.4 cm**, Δyaw=0.56°. 장착이 대칭이라는 가정 하 heuristic 경고("NOT SYMMETRIC"). Δty 4.4 cm 가 지배적.

## 4. 근본 원인
1. **단일 벽(선형) region**: ICP 가 벽을 따라가는 방향(≈Y)으로 미끄러져도 벌점이 없음 → along-wall 방향(=ty) 제약 부재 → ty 가 run 마다 흔들리고 cm 잔차. (가장 큰 원인)
2. **Max Corr Dist = 0.30 m (헐거움)**: 30 cm 떨어진 점끼리 매칭 허용 → 느슨한 해를 "수렴"으로 통과, 5 cm 잔차 방치.
3. **미수렴 region 은 오정렬이 아니라 개수 미달**: correspondences 20/23 < Min 30 → 형식 거부. 해당 region 자체는 화면상 정렬됨.

## 5. 개선 방법 (cm → mm)
1. **코너(두 벽 교차) region 필수** 1개 이상 — 서로 다른 방향의 면이 x·y·yaw 를 전부 잠가 along-wall 미끄러짐 제거.
2. **region 2~3개**, 방향 다양하게. 단일 벽으로는 원리상 sub-cm 불가.
3. **1차 정렬 후 Max Corr Dist 0.30 → 0.05~0.10 m** 로 낮춰 재실행 → outlier 제거, 잔차 조임.
4. **목표 mean_dist ≤ ~2 cm** + Δty 동반 감소. 그러면 실제 정렬. Δty 가 안 줄면 실제 장착 비대칭(그땐 확정 후 사용).

## 6. 값 적용/저장 워크플로 (확인 결과)
- **ICP 결과는 자동으로 Jog 스핀박스에 반영됨** (`_on_calibration_complete` → `_write_jog_to_spinboxes(jog_front, jog_rear_corrected)`, `calibration_window.py:777`). 즉 현재 Rear Jog = after-ICP 값. **손으로 타이핑 불필요.**
- **저장은 수동 버튼 필요**: `Save Results`(파일 선택 저장) 또는 `Apply & Save`(=Apply Broadcast → `config/calibration_result.yaml` 저장, `calibration_window.py:846`). 누르기 전엔 앱 메모리에만 존재(닫으면 소실).
- **로봇 실반영은 별개**: 앱이 로봇에 TF 를 push 하지 않음("TF broadcast removed", `:822`). 저장된 YAML 을 로봇 TF/설정으로 반영하는 것은 외부 단계.

## 7. 결론
회전은 수렴했으나 **translation(특히 ty 4.4 cm) 과 잔차 5.5 cm 는 이 용도에서 큰 오차**. 원인은 단일 벽 region + 헐거운 gate. **코너 region 추가 + Max Corr Dist 축소로 mean_dist 2 cm 미만** 달성이 목표. 현재 값은 Jog 에 자동 반영돼 있으나 저장/로봇반영은 수동.

## 관련
- [worklog 2026-07-09](../worklog/2026/07/2026-07-09.md)
