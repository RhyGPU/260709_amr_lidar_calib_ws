# ISSUE-006: 캘리브레이션 .bat 더블클릭 시 실행 안 됨 (창만 깜빡)

## 증상
- `scripts/run_calibration_app.bat` 더블클릭 시 앱이 안 뜸. 창이 잠깐 떴다 닫힘(끝의 `pause`에도 도달 못 함).
- bash에서 `python app.py` 직접 실행은 정상 → 코드/환경(파이썬·PySide6)은 문제 없음.

## 원인
- Write 도구로 생성한 모든 `.bat`가 **LF(Unix) 개행**이었음. cmd.exe는 **CRLF**를 기대하며, LF-only 배치파일은 파싱이 어긋나 명령이 실행되지 않거나 창이 즉시 닫힘.
- 부가: REM 주석에 non-ASCII(em-dash 등) 포함. ✓(head -c / od: `... off 0a`, `file`: "Unicode text, UTF-8"; CRLF 없음)
- 참고: 더블클릭 시 `python`은 시스템 PATH로 해석되나 본 PC는 C:\Python314\python(PySide6 보유)가 우선이라 파이썬 자체는 무관.

## 해결
- `scripts/*.bat` 6개 전부 **CRLF로 변환 + non-ASCII → ASCII 치환**(—→-, →→->, 곡선따옴표 등). ascii-only 확인.

## 검증
- [x] SIL — 6개 .bat 모두 CRLF 포함 & ascii-only 확인
- [x] HIL — `cmd /c run_calibration_app.bat`(더블클릭 등가)로 앱 기동 확인: 6060/6061 바인드 + "ScanSource started" + "Scan #N: 520/520 pts" 수신

## 관련 작업
- [worklog 2026-07-09](../worklog/2026/07/2026-07-09.md)
