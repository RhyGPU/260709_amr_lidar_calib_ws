#!/usr/bin/env python3
"""
Main UI Window for 2D LiDAR Calibration (merged_lidar-centric).

Workflow:
  1. Load initial TF from config parameters → populate jog spinboxes
  2. User adjusts jog (merged→front, merged→rear) for coarse alignment
  3. Both scans displayed in merged_lidar frame (raw × jog transform)
  4. User draws ROI regions, runs ICP for precise alignment
  5. ICP corrects jog_rear → display updated overlay

WP7: PySide6 port — ROS removed, ScanSource injected, QUiLoader for .ui.
"""

import logging
import math
import os

import numpy as np
from PySide6.QtCore import QFile, QIODevice, Qt, QThread, Signal, Slot
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QFileDialog, QMainWindow, QVBoxLayout, QWidget

logger = logging.getLogger(__name__)

from core.calibration_engine import CalibrationEngine
from core.icp_algorithm import ICPConfig
from core.region_manager import RegionManager
from core.tf_calculator import (
    CalibrationOutput,
    TFTransform2D,
    apply_symmetric_correction,
    compute_symmetry_info,
    mirror_front_to_rear,
    save_calibration_yaml,
)
from sensor_io.scan_source import ScanSource
from ui.scan_canvas import InteractionMode, ScanCanvas

# Default save path for "Apply & Save" (config\calibration_result.yaml, project-relative)
_DEFAULT_RESULT_YAML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "calibration_result.yaml",
)


class DiscoveryWorker(QThread):
    """백그라운드 QThread: 단일 target 포트를 scan_port로 스캔하여 결과를 시그널로 반환한다.

    동시성 계약 (concurrency-coding §1):
        - run()은 워커 스레드에서 실행된다.
        - Qt 위젯·ScanSource를 워커 스레드에서 직접 건드리지 않는다.
        - 결과는 discovery_finished 시그널로 메인 스레드에 전달한다.

    Args:
        target:    스캔 대상 식별자 ('front' 또는 'rear').
        port:      스캔할 UDP 포트.
        timeout_s: 수신 대기 시간(초).
    """

    # {'target': str, 'info': LiDARInfo|None}
    discovery_finished = Signal(object)

    def __init__(self, target: str, port: int, timeout_s: float = 3.0):
        super().__init__()
        self._target = target
        self._port = port
        self._timeout_s = timeout_s

    def run(self) -> None:
        """워커 스레드 진입점: 단일 포트 스캔 후 시그널 emit."""
        from tools.discover import scan_port  # 지역 import — 워커 스레드 내 사용

        info = None
        try:
            info = scan_port(self._port, self._timeout_s)
        except Exception as exc:
            logger.warning("Discovery %s port %d failed: %s", self._target, self._port, exc)

        self.discovery_finished.emit({"target": self._target, "info": info})


class CalibrationWorker(QThread):
    """Run ICP calibration in a background thread to avoid UI freeze."""

    finished = Signal()
    error = Signal(str)

    def __init__(self, engine, raw_front, raw_rear, jog_front, jog_rear, regions, config):
        super().__init__()
        self._engine = engine
        self._raw_front = raw_front
        self._raw_rear = raw_rear
        self._jog_front = jog_front
        self._jog_rear = jog_rear
        self._regions = regions
        self._config = config

    def run(self):
        try:
            self._engine.run_calibration(
                self._raw_front,
                self._raw_rear,
                self._jog_front,
                self._jog_rear,
                self._regions,
                self._config,
            )
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


class CalibrationUIWindow(QMainWindow):
    """Main window for LiDAR calibration UI.

    Args:
        scan_source: ScanSource instance providing live UDP scan signals.
        parent: Optional Qt parent widget.
    """

    def __init__(self, scan_source: ScanSource, parent=None):
        super().__init__(parent)

        self._scan_source = scan_source

        # Load .ui file via QUiLoader — loader.load() returns a widget tree,
        # which we attach as the central widget.  Widget access is via findChild.
        self._ui = self._load_ui()
        self.setCentralWidget(self._ui)
        self.setWindowTitle(self._ui.windowTitle())
        self.resize(self._ui.size())

        # Bind frequently accessed widgets as attributes for readability
        self._bind_widgets()

        self._region_manager = RegionManager()
        self._engine = CalibrationEngine(transform_fn=ScanSource.transform_points_2d)

        self._setup_canvas()

        # Raw scan data (sensor-local frames)
        self._raw_front = None
        self._raw_rear = None

        # Current jog transforms (merged_lidar → sensor)
        self._jog_front = TFTransform2D()
        self._jog_rear = TFTransform2D()

        self._calibration_worker = None  # keep reference to avoid GC
        self._discovery_worker = None   # keep reference to avoid GC

        self._connect_signals()
        self._prefill_endpoints()
        self.statusBar().showMessage("Ready — click 'Load Initial TF' to start")

    # ── shutdown ──
    def closeEvent(self, event):
        """Guarantee a full shutdown on window close (X button / quit).

        Stops the ScanSource so its receiver threads and UDP sockets are torn
        down and ports 6060/6061 are released — otherwise the process can linger
        in the background holding the ports (an orphaned instance the next
        launch can't bind over). Idempotent with app.aboutToQuit → stop().
        """
        try:
            self._scan_source.stop()
        except Exception:  # never block the close on a teardown error
            pass
        super().closeEvent(event)

    # ── UI loading ──

    @staticmethod
    def _get_ui_path() -> str:
        """Return absolute path to calibration_main.ui (project ui/ directory)."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(root, "ui", "calibration_main.ui")

    def _load_ui(self) -> QWidget:
        """Load .ui with QUiLoader and return the root widget."""
        ui_path = self._get_ui_path()
        ui_file = QFile(ui_path)
        if not ui_file.open(QIODevice.ReadOnly):
            raise RuntimeError(f"Cannot open UI file: {ui_path}")
        loader = QUiLoader()
        widget = loader.load(ui_file)
        ui_file.close()
        if widget is None:
            raise RuntimeError(f"QUiLoader failed to parse: {ui_path}")
        return widget

    def _bind_widgets(self):
        """Bind .ui objectNames to self attributes via findChild."""
        w = self._ui
        # Network (UDP) settings
        self.editFrontEndpoint = w.findChild(QWidget, "editFrontEndpoint")
        self.editRearEndpoint = w.findChild(QWidget, "editRearEndpoint")
        self.btnReconnect = w.findChild(QWidget, "btnReconnect")
        self.btnDiscoverFront = w.findChild(QWidget, "btnDiscoverFront")
        self.btnDiscoverRear = w.findChild(QWidget, "btnDiscoverRear")
        # Flip checkboxes
        self.chkFlipFront = w.findChild(QWidget, "chkFlipFront")
        self.chkFlipRear = w.findChild(QWidget, "chkFlipRear")
        # Jog spinboxes — front
        self.spinJogFrontX = w.findChild(QWidget, "spinJogFrontX")
        self.spinJogFrontY = w.findChild(QWidget, "spinJogFrontY")
        self.spinJogFrontYaw = w.findChild(QWidget, "spinJogFrontYaw")
        # Jog spinboxes — rear
        self.spinJogRearX = w.findChild(QWidget, "spinJogRearX")
        self.spinJogRearY = w.findChild(QWidget, "spinJogRearY")
        self.spinJogRearYaw = w.findChild(QWidget, "spinJogRearYaw")
        # Buttons
        self.btnLoadURDF = w.findChild(QWidget, "btnLoadURDF")
        self.listRegions = w.findChild(QWidget, "listRegions")
        self.btnAddRegion = w.findChild(QWidget, "btnAddRegion")
        self.btnRemoveRegion = w.findChild(QWidget, "btnRemoveRegion")
        self.btnClearRegions = w.findChild(QWidget, "btnClearRegions")
        self.spinMaxIter = w.findChild(QWidget, "spinMaxIter")
        self.spinMaxCorrDist = w.findChild(QWidget, "spinMaxCorrDist")
        self.spinMinCorr = w.findChild(QWidget, "spinMinCorr")
        self.spinDownsample = w.findChild(QWidget, "spinDownsample")
        self.btnRunCalibration = w.findChild(QWidget, "btnRunCalibration")
        self.textResults = w.findChild(QWidget, "textResults")
        self.textSymmetry = w.findChild(QWidget, "textSymmetry")
        self.btnSaveResults = w.findChild(QWidget, "btnSaveResults")
        self.btnSaveCurrentJog = w.findChild(QWidget, "btnSaveCurrentJog")
        self.btnApplyBroadcast = w.findChild(QWidget, "btnApplyBroadcast")
        self.btnCheckSymmetry = w.findChild(QWidget, "btnCheckSymmetry")
        self.btnMirrorFrontToRear = w.findChild(QWidget, "btnMirrorFrontToRear")
        self.btnSymmetricCorrection = w.findChild(QWidget, "btnSymmetricCorrection")
        # Canvas placeholder — replaced in _setup_canvas
        self._canvas_placeholder = w.findChild(QWidget, "canvasPlaceholder")

    def _setup_canvas(self):
        """Replace canvasPlaceholder with a live ScanCanvas."""
        self._canvas = ScanCanvas()
        placeholder = self._canvas_placeholder
        parent_layout = placeholder.parent().layout()
        index = parent_layout.indexOf(placeholder)
        parent_layout.removeWidget(placeholder)
        placeholder.deleteLater()
        parent_layout.insertWidget(index, self._canvas)

    def _connect_signals(self):
        # ScanSource → raw scan storage (QueuedConnection for cross-thread safety)
        self._scan_source.front_scan_updated.connect(
            self._on_front_scan, Qt.QueuedConnection
        )
        self._scan_source.rear_scan_updated.connect(
            self._on_rear_scan, Qt.QueuedConnection
        )
        self._scan_source.connection_status_changed.connect(
            self._on_connection_status, Qt.QueuedConnection
        )
        self._scan_source.scan_info_updated.connect(
            self._on_scan_info, Qt.QueuedConnection
        )

        # Canvas signals
        self._canvas.rectangle_completed.connect(self._on_rectangle_completed)
        self._canvas.mouse_world_pos.connect(self._on_mouse_world_pos)

        # Region manager
        self._region_manager.regions_changed.connect(self._update_region_list)

        # UI buttons
        self.btnLoadURDF.clicked.connect(self._on_load_tf)
        self.btnAddRegion.clicked.connect(self._on_add_region_clicked)
        self.btnRemoveRegion.clicked.connect(self._on_remove_region)
        self.btnClearRegions.clicked.connect(self._on_clear_regions)
        self.btnReconnect.clicked.connect(self._on_reconnect)
        self.btnDiscoverFront.clicked.connect(self._on_discover_front)
        self.btnDiscoverRear.clicked.connect(self._on_discover_rear)
        self.btnRunCalibration.clicked.connect(self._on_run_calibration)
        self.btnSaveResults.clicked.connect(self._on_save_results)
        self.btnSaveCurrentJog.clicked.connect(self._on_save_current_jog)
        self.btnApplyBroadcast.clicked.connect(self._on_apply_broadcast)
        self.btnCheckSymmetry.clicked.connect(self._on_check_symmetry)
        self.btnMirrorFrontToRear.clicked.connect(self._on_mirror_front_to_rear)
        self.btnSymmetricCorrection.clicked.connect(self._on_symmetric_correction)

        # Sensor flip (upside-down mounting)
        self.chkFlipFront.stateChanged.connect(self._on_flip_front_changed)
        self.chkFlipRear.stateChanged.connect(self._on_flip_rear_changed)

        # Jog spinbox → live update
        self.spinJogFrontX.valueChanged.connect(self._on_jog_changed)
        self.spinJogFrontY.valueChanged.connect(self._on_jog_changed)
        self.spinJogFrontYaw.valueChanged.connect(self._on_jog_changed)
        self.spinJogRearX.valueChanged.connect(self._on_jog_changed)
        self.spinJogRearY.valueChanged.connect(self._on_jog_changed)
        self.spinJogRearYaw.valueChanged.connect(self._on_jog_changed)

        # Calibration engine
        self._engine.region_result_ready.connect(self._on_region_result)
        self._engine.calibration_complete.connect(self._on_calibration_complete)
        self._engine.calibration_error.connect(self._on_calibration_error)
        self._engine.progress_updated.connect(self._on_progress_update)

    # ── Sensor flip (upside-down mounting) ──

    @Slot(int)
    def _on_flip_front_changed(self, state):
        """Toggle front sensor flip (roll=π, Y-negate in 2D)."""
        self._jog_front.flipped = state == Qt.Checked
        self._update_canvas_points()

    @Slot(int)
    def _on_flip_rear_changed(self, state):
        """Toggle rear sensor flip (roll=π, Y-negate in 2D)."""
        self._jog_rear.flipped = state == Qt.Checked
        self._update_canvas_points()

    # ── Jog handling ──

    def _read_jog_from_spinboxes(self):
        """Read current jog values from UI spinboxes (preserves flipped state)."""
        self._jog_front = TFTransform2D(
            tx=self.spinJogFrontX.value(),
            ty=self.spinJogFrontY.value(),
            yaw=math.radians(self.spinJogFrontYaw.value()),
            flipped=self._jog_front.flipped,
        )
        self._jog_rear = TFTransform2D(
            tx=self.spinJogRearX.value(),
            ty=self.spinJogRearY.value(),
            yaw=math.radians(self.spinJogRearYaw.value()),
            flipped=self._jog_rear.flipped,
        )

    def _write_jog_to_spinboxes(self, jog_front: TFTransform2D, jog_rear: TFTransform2D):
        """Write jog values to UI spinboxes (blocks signals to avoid feedback loop)."""
        for spin in [
            self.spinJogFrontX,
            self.spinJogFrontY,
            self.spinJogFrontYaw,
            self.spinJogRearX,
            self.spinJogRearY,
            self.spinJogRearYaw,
        ]:
            spin.blockSignals(True)

        self.spinJogFrontX.setValue(jog_front.tx)
        self.spinJogFrontY.setValue(jog_front.ty)
        self.spinJogFrontYaw.setValue(math.degrees(jog_front.yaw))
        self.spinJogRearX.setValue(jog_rear.tx)
        self.spinJogRearY.setValue(jog_rear.ty)
        self.spinJogRearYaw.setValue(math.degrees(jog_rear.yaw))

        for spin in [
            self.spinJogFrontX,
            self.spinJogFrontY,
            self.spinJogFrontYaw,
            self.spinJogRearX,
            self.spinJogRearY,
            self.spinJogRearYaw,
        ]:
            spin.blockSignals(False)

        self._jog_front = jog_front
        self._jog_rear = jog_rear

    @Slot()
    def _on_jog_changed(self):
        """User changed a jog spinbox → update display."""
        self._read_jog_from_spinboxes()
        self._update_canvas_points()

    def _update_canvas_points(self):
        """Transform raw scans to merged_lidar frame and send to canvas."""
        if self._raw_front is not None:
            front_merged = ScanSource.transform_points_2d(self._raw_front, self._jog_front)
            self._canvas.set_front_points(front_merged)

        if self._raw_rear is not None:
            rear_merged = ScanSource.transform_points_2d(self._raw_rear, self._jog_rear)
            self._canvas.set_rear_points(rear_merged)

        # Update sensor crosshair positions
        self._canvas.set_sensor_positions(
            (self._jog_front.tx, self._jog_front.ty, self._jog_front.yaw),
            (self._jog_rear.tx, self._jog_rear.ty, self._jog_rear.yaw),
        )

    # ── Scan callbacks ──

    @Slot(object)
    def _on_front_scan(self, points):
        self._raw_front = points
        if self._raw_front is not None:
            front_merged = ScanSource.transform_points_2d(self._raw_front, self._jog_front)
            self._canvas.set_front_points(front_merged)

    @Slot(object)
    def _on_rear_scan(self, points):
        self._raw_rear = points
        if self._raw_rear is not None:
            rear_merged = ScanSource.transform_points_2d(self._raw_rear, self._jog_rear)
            self._canvas.set_rear_points(rear_merged)

    @Slot(bool, bool)
    def _on_connection_status(self, front_connected, rear_connected):
        parts = []
        parts.append("Front: Connected" if front_connected else "Front: Disconnected")
        parts.append("Rear: Connected" if rear_connected else "Rear: Disconnected")
        self.statusBar().showMessage(" | ".join(parts))

    @Slot(int, int)
    def _on_scan_info(self, front_count, rear_count):
        self.statusBar().showMessage(f"Front: {front_count} pts | Rear: {rear_count} pts")

    @Slot(float, float)
    def _on_mouse_world_pos(self, x, y):
        self.statusBar().showMessage(f"Cursor: ({x:.3f}, {y:.3f}) m", 2000)

    # ── Load TF from config ──

    @Slot()
    def _on_load_tf(self):
        """Load initial TF from config parameters, populate jog spinboxes."""
        initial = self._scan_source.get_initial_tfs()
        if initial is None:
            self.statusBar().showMessage("Failed to load TF from config parameters", 5000)
            return

        jog_front = initial["merged_to_front"]
        jog_rear = initial["merged_to_rear"]
        tf_base_front = initial["tf_base_front"]
        tf_base_rear = initial["tf_base_rear"]

        self._write_jog_to_spinboxes(jog_front, jog_rear)

        # Sync flip checkboxes with config values
        self.chkFlipFront.blockSignals(True)
        self.chkFlipRear.blockSignals(True)
        self.chkFlipFront.setChecked(jog_front.flipped)
        self.chkFlipRear.setChecked(jog_rear.flipped)
        self.chkFlipFront.blockSignals(False)
        self.chkFlipRear.blockSignals(False)

        self._update_canvas_points()

        text = "Config TF Loaded\n"
        text += "=" * 50 + "\n\n"
        text += "1) base_link frame:\n"
        text += "  base_link -> scan_front:\n"
        text += (
            f"    tx={tf_base_front.tx:.4f} ty={tf_base_front.ty:.4f} "
            f"yaw={tf_base_front.yaw:.4f} rad ({math.degrees(tf_base_front.yaw):.2f}°) "
            f"flipped={tf_base_front.flipped}\n"
        )
        text += "  base_link -> scan_rear:\n"
        text += (
            f"    tx={tf_base_rear.tx:.4f} ty={tf_base_rear.ty:.4f} "
            f"yaw={tf_base_rear.yaw:.4f} rad ({math.degrees(tf_base_rear.yaw):.2f}°) "
            f"flipped={tf_base_rear.flipped}\n\n"
        )
        text += "2) Merged_lidar frame (jog values):\n"
        text += "  merged -> scan_front:\n"
        text += (
            f"    tx={jog_front.tx:.4f} ty={jog_front.ty:.4f} "
            f"yaw={jog_front.yaw:.4f} rad ({math.degrees(jog_front.yaw):.2f}°)\n"
        )
        text += "  merged -> scan_rear:\n"
        text += (
            f"    tx={jog_rear.tx:.4f} ty={jog_rear.ty:.4f} "
            f"yaw={jog_rear.yaw:.4f} rad ({math.degrees(jog_rear.yaw):.2f}°)\n\n"
        )
        text += "(Jog spinboxes show merged_lidar-relative values)\n"
        self.textResults.setPlainText(text)

        self.statusBar().showMessage(
            f"Config loaded: base->front yaw={math.degrees(tf_base_front.yaw):.1f}°, "
            f"base->rear yaw={math.degrees(tf_base_rear.yaw):.1f}° | "
            f"merged->front yaw={math.degrees(jog_front.yaw):.1f}°, "
            f"merged->rear yaw={math.degrees(jog_rear.yaw):.1f}°",
            10000,
        )

    # ── Region management ──

    @Slot(float, float, float, float)
    def _on_rectangle_completed(self, x1, y1, x2, y2):
        region_idx = self._region_manager.add_region(x1, y1, x2, y2)
        self.statusBar().showMessage(
            f"Region {region_idx} added: ({x1:.2f}, {y1:.2f}) to ({x2:.2f}, {y2:.2f})", 3000
        )
        self._canvas.set_interaction_mode(InteractionMode.PAN)

    @Slot()
    def _on_add_region_clicked(self):
        self._canvas.set_interaction_mode(InteractionMode.DRAW_REGION)
        self.statusBar().showMessage("Draw region: Click two corners", 5000)

    @Slot()
    def _on_remove_region(self):
        current_row = self.listRegions.currentRow()
        if current_row >= 0:
            self._region_manager.remove_region(current_row)

    @Slot()
    def _on_clear_regions(self):
        self._region_manager.clear_all()

    @Slot()
    def _update_region_list(self):
        self.listRegions.clear()
        regions = self._region_manager.get_regions()
        for idx, region in enumerate(regions):
            label = region.label if region.label else f"Region {idx}"
            bounds = (
                f"({region.x_min:.2f}, {region.y_min:.2f}) "
                f"to ({region.x_max:.2f}, {region.y_max:.2f})"
            )
            self.listRegions.addItem(f"{label}: {bounds}")
        self._canvas.set_regions(regions)

    def _prefill_endpoints(self) -> None:
        """scan_source.endpoints()로 Network (UDP) 필드를 프리필한다."""
        ep = self._scan_source.endpoints()
        front_ip, front_port = ep["front"]
        rear_ip, rear_port = ep["rear"]
        self.editFrontEndpoint.setText(f"{front_ip}:{front_port}")
        self.editRearEndpoint.setText(f"{rear_ip}:{rear_port}")

    @staticmethod
    def _parse_endpoint(text: str) -> tuple[str, int] | None:
        """'ip:port' 문자열을 (ip, port) 튜플로 파싱한다.

        Args:
            text: 'ip:port' 형식 문자열.

        Returns:
            (ip: str, port: int) 또는 형식/범위 오류 시 None.
        """
        parts = text.strip().rsplit(":", 1)
        if len(parts) != 2:
            return None
        ip, port_str = parts[0].strip(), parts[1].strip()
        if not ip:
            return None
        try:
            port = int(port_str)
        except ValueError:
            return None
        if not (1 <= port <= 65535):
            return None
        return ip, port

    @Slot()
    def _on_reconnect(self):
        """Network (UDP) 필드의 ip:port를 파싱하여 수신기를 재바인드한다.

        잘못된 형식 또는 포트 범위 오류 시 상태바에 에러 메시지를 표시하고
        재바인드를 수행하지 않는다.
        """
        front_text = self.editFrontEndpoint.text()
        rear_text = self.editRearEndpoint.text()

        front_parsed = self._parse_endpoint(front_text)
        if front_parsed is None:
            self.statusBar().showMessage(
                f"Error: Front endpoint '{front_text}' — 형식은 ip:port (포트 1~65535)", 5000
            )
            return

        rear_parsed = self._parse_endpoint(rear_text)
        if rear_parsed is None:
            self.statusBar().showMessage(
                f"Error: Rear endpoint '{rear_text}' — 형식은 ip:port (포트 1~65535)", 5000
            )
            return

        front_ip, front_port = front_parsed
        rear_ip, rear_port = rear_parsed

        try:
            self._scan_source.reconnect(front_ip, front_port, rear_ip, rear_port)
        except OSError as exc:
            self.statusBar().showMessage(f"Reconnect failed: {exc}", 8000)
            return

        self.statusBar().showMessage(
            f"Reconnected: front={front_ip}:{front_port}  rear={rear_ip}:{rear_port}", 8000
        )

    # ── Sensor Discovery ──

    def _run_discovery(self, target: str, port: int) -> None:
        """센서별 디스커버리 공통 헬퍼 (메인 스레드).

        동시성 순서 (concurrency-coding §1):
          1) scan_source.stop() — 수신기가 점유한 포트를 해제한다.
          2) 버튼 전체 비활성화 — 중복 클릭 방지.
          3) DiscoveryWorker(QThread) 시작 — 워커가 scan_port()로 단일 포트 바인드·수신.
          4) 결과는 discovery_finished 시그널 → _on_discovery_finished(메인 스레드).

        Args:
            target: 'front' 또는 'rear'.
            port:   스캔할 UDP 포트.
        """
        self._scan_source.stop()
        self.btnDiscoverFront.setEnabled(False)
        self.btnDiscoverRear.setEnabled(False)
        self.btnReconnect.setEnabled(False)
        self.statusBar().showMessage(f"Scanning {target} port {port}...")

        self._discovery_worker = DiscoveryWorker(target=target, port=port, timeout_s=3.0)
        self._discovery_worker.discovery_finished.connect(
            self._on_discovery_finished, Qt.QueuedConnection
        )
        self._discovery_worker.start()

    @Slot()
    def _on_discover_front(self) -> None:
        """Find (Front) 버튼 핸들러 — front 포트만 스캔한다."""
        ep = self._scan_source.endpoints()
        _, front_port = ep["front"]
        self._run_discovery("front", front_port)

    @Slot()
    def _on_discover_rear(self) -> None:
        """Find (Rear) 버튼 핸들러 — rear 포트만 스캔한다."""
        ep = self._scan_source.endpoints()
        _, rear_port = ep["rear"]
        self._run_discovery("rear", rear_port)

    @Slot(object)
    def _on_discovery_finished(self, result: dict) -> None:
        """DiscoveryWorker 완료 핸들러 (메인 스레드).

        찾은 센서의 IP를 해당 엔드포인트 필드에만 채우고,
        scan_source.reconnect()로 라이브 수신을 자동 재개한다.

        Args:
            result: {'target': 'front'|'rear', 'info': LiDARInfo|None}
        """
        target = result.get("target")
        info = result.get("info")

        ep = self._scan_source.endpoints()

        # 찾은 센서의 필드만 갱신 (상대방 필드는 절대 건드리지 않는다)
        if target == "front" and info is not None:
            _, port = ep["front"]
            self.editFrontEndpoint.setText(f"{info.ip}:{port}")
            status_msg = f"Front found: {info.ip}:{port}"
        elif target == "rear" and info is not None:
            _, port = ep["rear"]
            self.editRearEndpoint.setText(f"{info.ip}:{port}")
            status_msg = f"Rear found: {info.ip}:{port}"
        else:
            status_msg = f"{target} 센서 미발견 (타임아웃) — 필드 값을 확인 후 Reconnect를 누르세요"

        self.statusBar().showMessage(status_msg, 10000)

        # 버튼 재활성화
        self.btnDiscoverFront.setEnabled(True)
        self.btnDiscoverRear.setEnabled(True)
        self.btnReconnect.setEnabled(True)

        # 현재 양쪽 필드 값으로 수신 자동 재개
        front_parsed = self._parse_endpoint(self.editFrontEndpoint.text())
        rear_parsed = self._parse_endpoint(self.editRearEndpoint.text())

        if front_parsed is not None and rear_parsed is not None:
            try:
                self._scan_source.reconnect(
                    front_parsed[0], front_parsed[1],
                    rear_parsed[0], rear_parsed[1],
                )
                logger.info(
                    "Discovery auto-reconnect: front=%s:%d  rear=%s:%d",
                    front_parsed[0], front_parsed[1],
                    rear_parsed[0], rear_parsed[1],
                )
            except OSError as exc:
                logger.warning("Discovery auto-reconnect failed: %s", exc)
                self.statusBar().showMessage(
                    f"Auto-reconnect failed: {exc} — Reconnect 버튼을 눌러 수동으로 연결하세요",
                    8000,
                )

    # ── Calibration ──

    @Slot()
    def _on_run_calibration(self):
        if self._raw_front is None or self._raw_rear is None:
            self.textResults.setPlainText("Error: No scan data available")
            return

        regions = self._region_manager.get_regions()
        if len(regions) == 0:
            self.textResults.setPlainText("Error: No regions defined. Add at least one region.")
            return

        config = ICPConfig(
            max_iterations=self.spinMaxIter.value(),
            max_correspondence_dist=self.spinMaxCorrDist.value(),
            min_correspondences=self.spinMinCorr.value(),
        )

        downsample_stride = self.spinDownsample.value()
        raw_front = self._raw_front
        raw_rear = self._raw_rear

        if downsample_stride > 1:
            raw_front = raw_front[::downsample_stride]
            raw_rear = raw_rear[::downsample_stride]

        self._read_jog_from_spinboxes()

        self.textResults.clear()
        self.btnRunCalibration.setEnabled(False)
        self.btnSaveResults.setEnabled(False)
        self.btnApplyBroadcast.setEnabled(False)

        # Run ICP in background thread to avoid UI freeze
        self._calibration_worker = CalibrationWorker(
            self._engine,
            raw_front,
            raw_rear,
            self._jog_front,
            self._jog_rear,
            regions,
            config,
        )
        self._calibration_worker.error.connect(
            lambda msg: self.textResults.setPlainText(f"Error: {msg}")
        )
        self._calibration_worker.finished.connect(self._on_calibration_worker_finished)
        self._calibration_worker.start()

    def _on_calibration_worker_finished(self):
        """Re-enable button when worker finishes (success or failure)."""
        # Button state is managed by calibration_complete / calibration_error handlers.
        pass

    @Slot(int, object)
    def _on_region_result(self, region_idx, result):
        text = self.textResults.toPlainText()
        status = "CONVERGED" if result.converged else "NOT CONVERGED"
        text += (
            f"Region {region_idx}: [{status}]\n"
            f"  dx={result.dx:.4f} m, dy={result.dy:.4f} m, "
            f"dyaw={math.degrees(result.dyaw):.3f}°\n"
            f"  correspondences={result.num_correspondences}\n"
            f"  mean_dist={result.mean_correspondence_distance:.4f} m\n\n"
        )
        self.textResults.setPlainText(text)

    @Slot(object)
    def _on_calibration_complete(self, output: CalibrationOutput):
        text = self.textResults.toPlainText()
        text += "=" * 50 + "\n"
        text += "CALIBRATION RESULTS (merged_lidar-centric)\n"
        text += "=" * 50 + "\n\n"

        text += "ICP Correction (median):\n"
        text += f"  dx={output.icp_correction.tx:.4f} m\n"
        text += f"  dy={output.icp_correction.ty:.4f} m\n"
        text += f"  dyaw={math.degrees(output.icp_correction.yaw):.3f}°\n\n"

        text += "merged_lidar -> scan_front (unchanged):\n"
        text += (
            f"  tx={output.jog_front.tx:.4f} ty={output.jog_front.ty:.4f} "
            f"yaw={math.degrees(output.jog_front.yaw):.2f}°\n\n"
        )

        text += "merged_lidar -> scan_rear (before ICP):\n"
        text += (
            f"  tx={output.jog_rear_original.tx:.4f} ty={output.jog_rear_original.ty:.4f} "
            f"yaw={math.degrees(output.jog_rear_original.yaw):.2f}°\n\n"
        )

        text += "merged_lidar -> scan_rear (after ICP):\n"
        text += (
            f"  tx={output.jog_rear_corrected.tx:.4f} ty={output.jog_rear_corrected.ty:.4f} "
            f"yaw={math.degrees(output.jog_rear_corrected.yaw):.2f}°\n\n"
        )

        text += "Statistics:\n"
        text += f"  Successful regions: {output.num_successful}\n"
        text += f"  Median corr distance: {output.median_correspondence_distance:.4f} m\n"

        self.textResults.setPlainText(text)

        # Update jog_rear spinboxes with corrected values
        self._write_jog_to_spinboxes(output.jog_front, output.jog_rear_corrected)
        self._update_canvas_points()

        self.btnRunCalibration.setEnabled(True)
        self.btnSaveResults.setEnabled(True)
        self.btnApplyBroadcast.setEnabled(True)
        self.statusBar().showMessage("Calibration complete!", 5000)

    @Slot(str)
    def _on_calibration_error(self, error_msg):
        self.textResults.setPlainText(f"CALIBRATION ERROR:\n{error_msg}")
        self.btnRunCalibration.setEnabled(True)
        self.statusBar().showMessage("Calibration failed", 5000)

    @Slot(str)
    def _on_progress_update(self, status_text):
        self.statusBar().showMessage(status_text)

    # ── Save / Apply ──

    @Slot()
    def _on_save_results(self):
        if self._engine.last_output is None:
            self.statusBar().showMessage("No results to save", 3000)
            return

        try:
            filepath, _ = QFileDialog.getSaveFileName(
                self,
                "Save Calibration Results",
                _DEFAULT_RESULT_YAML,
                "YAML files (*.yaml *.yml);;All files (*)",
                options=QFileDialog.DontUseNativeDialog,
            )

            if not filepath:
                return  # User cancelled

            self._engine.save_results(self._engine.last_output, filepath)
            self.statusBar().showMessage(f"Saved: {filepath}", 5000)
        except Exception as e:
            self.statusBar().showMessage(f"Save failed: {str(e)}", 5000)

    @Slot()
    def _on_apply_broadcast(self):
        """Save current jog TFs to config/calibration_result.yaml (TF broadcast removed)."""
        self._read_jog_from_spinboxes()

        # Build output from current spinbox jog values
        icp_correction = TFTransform2D()  # zero (no ICP correction applied here)
        jog_rear_original = self._jog_rear
        if self._engine.last_output is not None:
            icp_correction = self._engine.last_output.icp_correction
            jog_rear_original = self._engine.last_output.jog_rear_original

        output = CalibrationOutput(
            icp_correction=icp_correction,
            jog_front=self._jog_front,
            jog_rear_original=jog_rear_original,
            jog_rear_corrected=self._jog_rear,
            num_successful=(self._engine.last_output.num_successful if self._engine.last_output else 0),
            median_correspondence_distance=(
                self._engine.last_output.median_correspondence_distance
                if self._engine.last_output
                else 0.0
            ),
        )

        try:
            save_calibration_yaml(output, _DEFAULT_RESULT_YAML)
            self.statusBar().showMessage(
                f"Saved to {_DEFAULT_RESULT_YAML} — "
                f"front:[{self._jog_front.tx:.4f}, {self._jog_front.ty:.4f}, "
                f"{math.degrees(self._jog_front.yaw):.2f}deg]  "
                f"rear:[{self._jog_rear.tx:.4f}, {self._jog_rear.ty:.4f}, "
                f"{math.degrees(self._jog_rear.yaw):.2f}deg]",
                8000,
            )
        except Exception as e:
            self.statusBar().showMessage(f"Apply failed: {str(e)}", 5000)

    # ── Symmetry Review ──

    @Slot()
    def _on_check_symmetry(self):
        """Analyze symmetry between current front/rear jog values."""
        self._read_jog_from_spinboxes()
        info = compute_symmetry_info(self._jog_front, self._jog_rear)

        text = "Symmetry Analysis\n"
        text += "=" * 40 + "\n\n"
        text += "Current values:\n"
        text += (
            f"  Front: tx={self._jog_front.tx:.4f}  "
            f"ty={self._jog_front.ty:.4f}  "
            f"yaw={math.degrees(self._jog_front.yaw):.2f}°\n"
        )
        text += (
            f"  Rear:  tx={self._jog_rear.tx:.4f}  "
            f"ty={self._jog_rear.ty:.4f}  "
            f"yaw={math.degrees(self._jog_rear.yaw):.2f}°\n\n"
        )

        text += "Ideal symmetric rear:\n"
        text += (
            f"  tx={info['ideal_rear_tx']:.4f}  "
            f"ty={info['ideal_rear_ty']:.4f}  "
            f"yaw={math.degrees(info['ideal_rear_yaw']):.2f}°\n\n"
        )

        text += "Asymmetry:\n"
        text += (
            f"  Δtx={info['delta_tx']:.4f} m  "
            f"Δty={info['delta_ty']:.4f} m  "
            f"Δyaw={math.degrees(info['delta_yaw']):.3f}°\n\n"
        )

        if info["is_symmetric"]:
            text += ">> SYMMETRIC (within threshold)"
        else:
            text += ">> NOT SYMMETRIC\n"
            text += "   Use 'Mirror Front->Rear' or manually adjust."

        self.textSymmetry.setPlainText(text)
        self.statusBar().showMessage(
            f"Symmetry: Δtx={info['delta_tx']:.4f} "
            f"Δty={info['delta_ty']:.4f} "
            f"Δyaw={math.degrees(info['delta_yaw']):.3f}°",
            5000,
        )

    @Slot()
    def _on_mirror_front_to_rear(self):
        """Set rear jog to perfect mirror of front jog."""
        self._read_jog_from_spinboxes()
        mirrored_rear = mirror_front_to_rear(self._jog_front, self._jog_rear.flipped)
        self._write_jog_to_spinboxes(self._jog_front, mirrored_rear)
        self._update_canvas_points()

        self.textSymmetry.setPlainText(
            f"Mirror applied:\n"
            f"  Rear tx={mirrored_rear.tx:.4f}  "
            f"ty={mirrored_rear.ty:.4f}  "
            f"yaw={math.degrees(mirrored_rear.yaw):.2f}°\n\n"
            f"Adjust spinboxes if fine-tuning needed,\n"
            f"then Save Current Jog."
        )
        self.statusBar().showMessage("Mirror applied: rear = symmetric of front", 5000)

    @Slot()
    def _on_symmetric_correction(self):
        """Split ICP correction equally between front and rear."""
        if self._engine.last_output is None:
            self.textSymmetry.setPlainText(
                "ICP calibration result required.\n"
                "Run Calibration first, then apply Symmetric Correction."
            )
            self.statusBar().showMessage("No ICP result — run calibration first", 5000)
            return

        output = self._engine.last_output
        before_front = output.jog_front
        before_rear_orig = output.jog_rear_original
        icp_corr = output.icp_correction

        sym_front, sym_rear = apply_symmetric_correction(before_front, before_rear_orig, icp_corr)

        # Update engine's last_output so Save Results also reflects symmetric values
        half_corr = TFTransform2D(
            tx=icp_corr.tx / 2.0,
            ty=icp_corr.ty / 2.0,
            yaw=icp_corr.yaw / 2.0,
        )
        self._engine._last_output = CalibrationOutput(
            icp_correction=half_corr,
            jog_front=sym_front,
            jog_rear_original=before_rear_orig,
            jog_rear_corrected=sym_rear,
            num_successful=output.num_successful,
            median_correspondence_distance=output.median_correspondence_distance,
        )

        self._write_jog_to_spinboxes(sym_front, sym_rear)
        self._update_canvas_points()

        text = "Symmetric Correction Applied\n"
        text += "=" * 40 + "\n\n"
        text += (
            f"ICP correction: dx={icp_corr.tx:.4f}  "
            f"dy={icp_corr.ty:.4f}  "
            f"dyaw={math.degrees(icp_corr.yaw):.3f}°\n\n"
        )
        text += "Before (ICP full to rear only):\n"
        text += (
            f"  Front: tx={before_front.tx:.4f}  "
            f"ty={before_front.ty:.4f}  "
            f"yaw={math.degrees(before_front.yaw):.2f}°\n"
        )
        text += (
            f"  Rear:  tx={output.jog_rear_corrected.tx:.4f}  "
            f"ty={output.jog_rear_corrected.ty:.4f}  "
            f"yaw={math.degrees(output.jog_rear_corrected.yaw):.2f}°\n\n"
        )
        text += "After (correction split equally):\n"
        text += (
            f"  Front: tx={sym_front.tx:.4f}  "
            f"ty={sym_front.ty:.4f}  "
            f"yaw={math.degrees(sym_front.yaw):.2f}°\n"
        )
        text += (
            f"  Rear:  tx={sym_rear.tx:.4f}  "
            f"ty={sym_rear.ty:.4f}  "
            f"yaw={math.degrees(sym_rear.yaw):.2f}°\n\n"
        )
        text += "Front: -correction/2, Rear: +correction/2\n"
        text += "Save Current Jog to persist."
        self.textSymmetry.setPlainText(text)
        self.statusBar().showMessage(
            "Symmetric correction: ICP split equally to both sensors", 5000
        )

    @Slot()
    def _on_save_current_jog(self):
        """Save current spinbox jog values to YAML (independent of ICP result)."""
        self._read_jog_from_spinboxes()

        # Build a CalibrationOutput from current spinbox values
        icp_correction = TFTransform2D()  # zero correction
        jog_rear_original = self._jog_rear
        if self._engine.last_output is not None:
            icp_correction = self._engine.last_output.icp_correction
            jog_rear_original = self._engine.last_output.jog_rear_original

        output = CalibrationOutput(
            icp_correction=icp_correction,
            jog_front=self._jog_front,
            jog_rear_original=jog_rear_original,
            jog_rear_corrected=self._jog_rear,
            num_successful=(
                self._engine.last_output.num_successful if self._engine.last_output else 0
            ),
            median_correspondence_distance=(
                self._engine.last_output.median_correspondence_distance
                if self._engine.last_output
                else 0.0
            ),
        )

        try:
            filepath, _ = QFileDialog.getSaveFileName(
                self,
                "Save Current Jog Values",
                _DEFAULT_RESULT_YAML,
                "YAML files (*.yaml *.yml);;All files (*)",
                options=QFileDialog.DontUseNativeDialog,
            )

            if not filepath:
                return

            save_calibration_yaml(output, filepath)
            self.statusBar().showMessage(f"Current jog saved: {filepath}", 5000)
        except Exception as e:
            self.statusBar().showMessage(f"Save failed: {str(e)}", 5000)
