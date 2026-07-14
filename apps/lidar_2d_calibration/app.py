#!/usr/bin/env python3
"""
app.py — SICK nanoScan3 2D LiDAR 캘리브레이션 UI 진입점 (ROS2-free, PySide6).

원본: _reference/calibration_ui_main.py (ROS2 부트스트랩)
이식: ROS 전면 제거 → UDP/PySide6 단독 실행.

흐름:
    argparse(--config) → load_sensor_config → QApplication
    → ScanSource(config) → CalibrationUIWindow(scan_source)
    → scan_source.start() → window.show() → app.exec()

종료:
    app.aboutToQuit 에서 scan_source.stop() 호출.

경로 해결:
    __file__ 기준 절대경로로 sys.path 및 기본 config 경로를 결정하므로
    어느 디렉토리에서 실행해도 동작한다.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# 프로젝트 루트를 sys.path 최우선에 삽입 — 어느 cwd에서도 패키지 import 가능
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sensor_io.config_loader import load_sensor_config  # noqa: E402
from sensor_io.scan_source import ScanSource  # noqa: E402

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

# 기본 config 경로: 루트 기준 config/sensors.yaml
_DEFAULT_CONFIG = _ROOT / "config" / "sensors.yaml"


# ---------------------------------------------------------------------------
# 공개 헬퍼 — 테스트 및 main()이 공유
# ---------------------------------------------------------------------------


def build_app(config_path: str | Path) -> tuple["QApplication", ScanSource]:
    """config 로드 → QApplication + ScanSource 를 생성하여 반환한다.

    window 생성·show·exec 는 포함하지 않으므로 GUI 블로킹 없이 테스트 가능.

    Args:
        config_path: sensors.yaml 파일 경로 (절대·상대 모두 허용).

    Returns:
        (app, scan_source) 튜플.
        - app: PySide6 QApplication 인스턴스.
        - scan_source: ScanSource 인스턴스 (start() 호출 전).

    Raises:
        FileNotFoundError: config 파일이 없을 때.
        ValueError: config 스키마 오류 (필드명 포함 메시지).
        SystemExit: QApplication import 불가 등 PySide6 초기화 실패.
    """
    from PySide6.QtWidgets import QApplication  # 런타임 import (PySide6 의존 격리)

    config = load_sensor_config(str(config_path))

    # QApplication은 프로세스당 1개 — 이미 존재하면 재사용
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("2D LiDAR Calibration UI")

    scan_source = ScanSource(config)
    return app, scan_source


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI 진입점. argparse → build_app → window → event loop."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="2D LiDAR Calibration UI (PySide6, UDP, ROS-free)"
    )
    parser.add_argument(
        "--config",
        default=str(_DEFAULT_CONFIG),
        help=f"sensors.yaml 경로 (기본값: {_DEFAULT_CONFIG})",
    )
    args = parser.parse_args()

    # --- config 로드 & 앱 생성 ---
    try:
        app, scan_source = build_app(args.config)
    except FileNotFoundError as exc:
        print(f"[ERROR] config 파일을 찾을 수 없습니다: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"[ERROR] config 스키마 오류: {exc}", file=sys.stderr)
        sys.exit(1)

    # --- CalibrationUIWindow: WP7 산출 후 정식 import, 그 전까지는 지연 import ---
    # WP7 미완 시에도 app.py 자체는 import 가능하도록 try/except 로 분리한다.
    try:
        from ui.calibration_window import CalibrationUIWindow  # noqa: PLC0415
    except ImportError as exc:
        print(
            f"[WARNING] ui.calibration_window import 실패 — WP7 미완 상태: {exc}",
            file=sys.stderr,
        )
        print("[WARNING] 창 없이 종료합니다.", file=sys.stderr)
        sys.exit(2)

    window = CalibrationUIWindow(scan_source)

    # --- 종료 시 scan_source.stop() 보장 ---
    # aboutToQuit 은 window closeEvent / signal / app.quit() 어느 경로로 끝나든
    # 반드시 발화하므로, 수신 스레드·소켓이 백그라운드에 남지 않는다.
    app.aboutToQuit.connect(scan_source.stop)

    # --- Ctrl+C / taskkill / 콘솔 종료도 깨끗이 닫히도록 signal 처리 ---
    # GUI 이벤트 루프가 Python signal 전달을 막으므로, 짧은 주기 QTimer 로
    # 인터프리터에 제어를 넘겨 SIGINT/SIGTERM/SIGBREAK 를 받도록 한다.
    import signal
    from PySide6.QtCore import QTimer

    def _graceful(*_args):
        app.quit()  # -> aboutToQuit -> scan_source.stop()

    for _name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        _sig = getattr(signal, _name, None)
        if _sig is not None:
            try:
                signal.signal(_sig, _graceful)
            except (ValueError, OSError):
                pass  # 메인 스레드가 아니거나 미지원 플랫폼

    _sig_pump = QTimer()
    _sig_pump.timeout.connect(lambda: None)  # 이벤트 루프를 주기적으로 깨워 signal 처리
    _sig_pump.start(200)

    # --- 스캔 시작 → 창 표시 → Qt 이벤트 루프 ---
    scan_source.start()
    window.show()
    exit_code = app.exec()  # PySide6: .exec() (PyQt5의 .exec_() 아님)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
