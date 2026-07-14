#!/usr/bin/env python3
"""
Scan Canvas — QPainter-based LiDAR scan visualization widget.
Displays front/rear LiDAR points, ROI regions, and ICP calibration results.
"""
import math
from enum import IntEnum

import numpy as np
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPointF, Signal
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QPolygonF

# Color palette
C_BG = QColor(0x1A, 0x1A, 0x2E)
C_GRID = QColor(0x2A, 0x2A, 0x3E, 80)
C_GRID_MAJOR = QColor(0x3A, 0x3A, 0x4E, 120)
C_ORIGIN = QColor(0xFF, 0xFF, 0xFF, 100)
C_BODY = QColor(0x47, 0x55, 0x69)
C_FRONT = QColor(0xFF, 0xD7, 0x00)  # yellow
C_REAR = QColor(0x00, 0xC8, 0x53)  # green
C_PREVIEW = QColor(0xFF, 0xFF, 0xFF, 150)
C_INFO = QColor(0xCB, 0xD5, 0xE1)


class InteractionMode(IntEnum):
    PAN = 0
    DRAW_REGION = 1


class DrawState(IntEnum):
    IDLE = 0
    WAIT_CORNER2 = 1


class ScanCanvas(QWidget):
    """QPainter-based LiDAR scan visualization canvas."""

    rectangle_completed = Signal(float, float, float, float)  # x1, y1, x2, y2 in world coords
    mouse_world_pos = Signal(float, float)  # cursor position in world coords

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 400)

        # View control
        self._scale = 150.0  # pixels per meter
        self._ox = 0.0  # pan offset x (screen pixels)
        self._oy = 0.0  # pan offset y (screen pixels)
        self._drag = False
        self._dp = QPointF()
        # Auto-fit: reframe the view when most points fall outside it (e.g. after a
        # jog change). Disabled the moment the user pans/zooms; re-enabled by reset_view.
        self._auto_fit = True

        # Data storage
        self._front_points = None  # (N, 2) numpy array or None
        self._rear_points = None  # (M, 2) numpy array or None
        self._regions = []  # list of Region objects
        self._icp_results = {}  # {region_index: CalibrationResult}

        # Interaction state
        self._mode = InteractionMode.PAN
        self._draw_state = DrawState.IDLE
        self._corner1 = None  # QPointF in screen coords
        self._corner1_world = None  # tuple (wx, wy) in world coords
        self._current_mouse = QPointF()

        # Sensor positions in merged_lidar frame (tx, ty, yaw)
        self._sensor_front_pos = None  # (tx, ty, yaw) or None
        self._sensor_rear_pos = None  # (tx, ty, yaw) or None

        self.setMouseTracking(True)

    # ── Public API ──
    def set_front_points(self, points):
        """Update front scan data."""
        self._front_points = points
        self._maybe_autofit()
        self.update()

    def set_rear_points(self, points):
        """Update rear scan data."""
        self._rear_points = points
        self._maybe_autofit()
        self.update()

    def set_regions(self, regions):
        """Update region overlays."""
        self._regions = regions if regions else []
        self.update()

    def set_icp_results(self, results):
        """Update per-region ICP results display."""
        self._icp_results = results if results else {}
        self.update()

    def set_sensor_positions(self, front_pos, rear_pos):
        """Update sensor positions for crosshair display.

        Args:
            front_pos: (tx, ty, yaw) tuple or None
            rear_pos: (tx, ty, yaw) tuple or None
        """
        self._sensor_front_pos = front_pos
        self._sensor_rear_pos = rear_pos
        self.update()

    def set_interaction_mode(self, mode):
        """Switch interaction mode."""
        self._mode = mode
        if mode == InteractionMode.PAN:
            # Cancel any in-progress drawing
            self._draw_state = DrawState.IDLE
            self._corner1 = None
            self._corner1_world = None
        self.update()

    def reset_view(self):
        """Re-enable auto-fit and reframe to the current points (or defaults)."""
        self._auto_fit = True
        self._scale = 150.0
        self._ox = 0.0
        self._oy = 0.0
        self._fit_to_points()
        self.update()

    def _collect_points(self):
        """Return an (N,2) array of all current front+rear points, or None."""
        arrays = [a for a in (self._front_points, self._rear_points)
                  if a is not None and len(a) > 0]
        if not arrays:
            return None
        return np.concatenate(arrays, axis=0)

    def _maybe_autofit(self):
        """Reframe only when auto-fit is on and most points are off-screen.

        This keeps a steady view frame-to-frame but automatically recovers when a
        jog/flip change (or the initial scan) pushes the data outside the viewport.
        """
        if not self._auto_fit:
            return
        pts = self._collect_points()
        if pts is None:
            return
        w, h = max(self.width(), 1), max(self.height(), 1)
        # world -> screen (same mapping as _w2s), vectorized
        sx = w / 2 + self._ox - pts[:, 1] * self._scale
        sy = h / 2 + self._oy - pts[:, 0] * self._scale
        visible = np.mean((sx >= 0) & (sx < w) & (sy >= 0) & (sy < h))
        if visible < 0.6:
            self._fit_to_points()

    def _fit_to_points(self, margin=0.85):
        """Scale/center the view to frame the DENSE bulk of the points.

        Uses a robust (median-centered, 90th-percentile) extent so a few far or
        stray returns don't zoom the whole scan down to specks. Guards against
        non-finite values so the view can never get stuck.
        """
        pts = self._collect_points()
        if pts is None:
            return
        x = pts[:, 0]
        y = pts[:, 1]
        finite = np.isfinite(x) & np.isfinite(y)
        if not np.any(finite):
            return
        x, y = x[finite], y[finite]
        cx, cy = float(np.median(x)), float(np.median(y))
        # 90th-percentile distance from center on each axis → ignores outliers
        half_x = max(float(np.percentile(np.abs(x - cx), 90)), 0.75)  # world X → height
        half_y = max(float(np.percentile(np.abs(y - cy), 90)), 0.75)  # world Y → width
        w, h = max(self.width(), 1), max(self.height(), 1)
        scale = min(h * margin / (2 * half_x), w * margin / (2 * half_y))
        if not math.isfinite(scale) or scale <= 0:
            return
        self._scale = max(30.0, min(2000.0, scale))
        self._ox = cy * self._scale
        self._oy = cx * self._scale

    # ── Coordinate transforms ──
    def _w2s(self, wx, wy):
        """World coords → Screen coords (top-down robot view: X+=up, Y+=left)."""
        return QPointF(
            self.width() / 2 + self._ox - wy * self._scale,
            self.height() / 2 + self._oy - wx * self._scale,
        )

    def _s2w(self, sx, sy):
        """Screen coords → World coords (top-down robot view: X+=up, Y+=left)."""
        wx = -(sy - self.height() / 2 - self._oy) / self._scale
        wy = -(sx - self.width() / 2 - self._ox) / self._scale
        return wx, wy

    # ── Mouse events ──
    def wheelEvent(self, e):
        """Zoom in/out (both modes). Manual zoom turns off auto-fit."""
        self._auto_fit = False
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self._scale = max(30, min(2000, self._scale * f))
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self._mode == InteractionMode.PAN:
                self._drag = True
                self._dp = e.pos()
            elif self._mode == InteractionMode.DRAW_REGION:
                if self._draw_state == DrawState.IDLE:
                    # First corner
                    self._corner1 = e.pos()
                    self._corner1_world = self._s2w(e.pos().x(), e.pos().y())
                    self._draw_state = DrawState.WAIT_CORNER2
                    self.update()
                elif self._draw_state == DrawState.WAIT_CORNER2:
                    # Second corner — complete rectangle
                    corner2_world = self._s2w(e.pos().x(), e.pos().y())
                    self.rectangle_completed.emit(
                        self._corner1_world[0],
                        self._corner1_world[1],
                        corner2_world[0],
                        corner2_world[1],
                    )
                    # Reset state
                    self._draw_state = DrawState.IDLE
                    self._corner1 = None
                    self._corner1_world = None
                    self.update()
        elif e.button() == Qt.RightButton:
            # Cancel drawing
            if self._mode == InteractionMode.DRAW_REGION and self._draw_state == DrawState.WAIT_CORNER2:
                self._draw_state = DrawState.IDLE
                self._corner1 = None
                self._corner1_world = None
                self.update()

    def mouseMoveEvent(self, e):
        # Emit world coordinates for status bar
        wx, wy = self._s2w(e.pos().x(), e.pos().y())
        self.mouse_world_pos.emit(wx, wy)

        if self._mode == InteractionMode.PAN and self._drag:
            self._auto_fit = False  # manual pan turns off auto-fit
            d = e.pos() - self._dp
            self._ox += d.x()
            self._oy += d.y()
            self._dp = e.pos()
            self.update()
        elif self._mode == InteractionMode.DRAW_REGION and self._draw_state == DrawState.WAIT_CORNER2:
            # Update preview rectangle
            self._current_mouse = e.pos()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = False

    # ── Paint layers ──
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Layer 1: Background
        p.fillRect(self.rect(), C_BG)

        # Layer 2: Grid
        self._draw_grid(p)

        # Layer 3: Origin crosshair
        self._draw_origin(p)

        # Layer 4: Sensor position crosshairs (+)
        self._draw_sensor_crosshairs(p)

        # Layer 5: Front scan points
        self._draw_points(p, self._front_points, C_FRONT, 3)

        # Layer 6: Rear scan points
        self._draw_points(p, self._rear_points, C_REAR, 3)

        # Layer 7: ROI rectangles
        self._draw_regions(p)

        # Layer 8: In-progress rectangle
        self._draw_preview_rectangle(p)

        # Layer 9: Info overlay
        self._draw_info_overlay(p)

        p.end()

    def _draw_grid(self, p):
        """Layer 2: Grid with 1m spacing and 5m major grid."""
        w, h = self.width(), self.height()
        cx, cy = w / 2 + self._ox, h / 2 + self._oy

        # 1m grid
        gp = 1.0 * self._scale  # 1 meter spacing
        p.setPen(QPen(C_GRID, 1))
        x = cx % gp
        while x < w:
            p.drawLine(int(x), 0, int(x), h)
            x += gp
        y = cy % gp
        while y < h:
            p.drawLine(0, int(y), w, int(y))
            y += gp

        # 5m major grid
        gp_major = 5.0 * self._scale
        p.setPen(QPen(C_GRID_MAJOR, 1))
        x = cx % gp_major
        while x < w:
            p.drawLine(int(x), 0, int(x), h)
            x += gp_major
        y = cy % gp_major
        while y < h:
            p.drawLine(0, int(y), w, int(y))
            y += gp_major

    def _draw_origin(self, p):
        """Layer 3: Origin crosshair — merged_scan center with ROS2 axis colors."""
        center = self._w2s(0.0, 0.0)
        cx, cy = int(center.x()), int(center.y())
        w, h = self.width(), self.height()
        arm = 25

        C_X_AXIS = QColor(0xFF, 0x44, 0x44)  # red — X axis (ROS2)
        C_Y_AXIS = QColor(0x00, 0xC8, 0x53)  # green — Y axis (ROS2)

        # Full-view axis lines (X=vertical=red, Y=horizontal=green)
        p.setPen(QPen(C_X_AXIS, 1, Qt.DashDotLine))
        p.drawLine(cx, 0, cx, h)  # X axis — vertical
        p.setPen(QPen(C_Y_AXIS, 1, Qt.DashDotLine))
        p.drawLine(0, cy, w, cy)  # Y axis — horizontal

        # Crosshair arms (X=vertical=red, Y=horizontal=green)
        p.setPen(QPen(C_X_AXIS, 3))
        p.drawLine(cx, cy - arm, cx, cy + arm)  # X axis arm (vertical)
        p.setPen(QPen(C_Y_AXIS, 3))
        p.drawLine(cx - arm, cy, cx + arm, cy)  # Y axis arm (horizontal)

        # Circle around center (white/neutral)
        p.setPen(QPen(C_ORIGIN, 2, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(center, arm, arm)

        # Axis labels
        p.setFont(QFont("monospace", 10, QFont.Bold))
        p.setPen(QPen(C_X_AXIS, 1))
        p.drawText(cx + 4, cy - arm - 4, "X")  # X label at top of vertical arm
        p.setPen(QPen(C_Y_AXIS, 1))
        p.drawText(cx - arm - 14, cy - 4, "Y")  # Y label at left of horizontal arm

        # Origin label
        p.setPen(QPen(C_ORIGIN, 1))
        p.setFont(QFont("monospace", 11, QFont.Bold))
        p.drawText(cx + arm + 4, cy + arm + 14, "M")

    def _draw_sensor_crosshairs(self, p):
        """Layer 4: Sensor position crosshairs (+) with X-axis arrow."""
        arm = 15  # crosshair arm length in pixels
        arrow_len = 40  # X-axis arrow length in pixels
        head_len = 8  # arrowhead length in pixels
        head_angle = math.radians(25)  # arrowhead half-angle

        for pos, color, label in [
            (self._sensor_front_pos, C_FRONT, "F"),
            (self._sensor_rear_pos, C_REAR, "R"),
        ]:
            if pos is None:
                continue
            tx, ty, yaw = pos
            center = self._w2s(tx, ty)
            cx, cy = int(center.x()), int(center.y())

            # Draw + crosshair
            p.setPen(QPen(color, 2))
            p.drawLine(cx - arm, cy, cx + arm, cy)
            p.drawLine(cx, cy - arm, cx, cy + arm)

            # Draw X-axis arrow (solid line + arrowhead)
            # Top-down view: X+=up, Y+=left on screen
            dx = -arrow_len * math.sin(yaw)
            dy = -arrow_len * math.cos(yaw)
            ex, ey = cx + dx, cy + dy  # arrow tip

            p.setPen(QPen(color, 2, Qt.SolidLine))
            p.drawLine(cx, cy, int(ex), int(ey))

            # Arrowhead
            angle = math.atan2(dy, dx)
            lx = ex - head_len * math.cos(angle - head_angle)
            ly = ey - head_len * math.sin(angle - head_angle)
            rx = ex - head_len * math.cos(angle + head_angle)
            ry = ey - head_len * math.sin(angle + head_angle)
            p.setBrush(QBrush(color))
            p.drawPolygon(QPolygonF([QPointF(ex, ey), QPointF(lx, ly), QPointF(rx, ry)]))
            p.setBrush(Qt.NoBrush)

            # "X" label at arrow tip
            p.setPen(QPen(color, 1))
            p.setFont(QFont("monospace", 9, QFont.Bold))
            p.drawText(int(ex + 4), int(ey - 4), "X")

            # Sensor label
            p.setFont(QFont("monospace", 10, QFont.Bold))
            p.drawText(cx + arm + 3, cy - 3, label)

    def _draw_points(self, painter, points, color, size=3):
        """Layer 5/6: Draw point cloud."""
        if points is None or len(points) == 0:
            return

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color))

        painter.setPen(QPen(color, size))
        for pt in points:
            sp = self._w2s(pt[0], pt[1])
            painter.drawEllipse(sp, size / 2, size / 2)

    def _draw_regions(self, p):
        """Layer 7: ROI rectangles with labels."""
        for idx, region in enumerate(self._regions):
            # Get region color with alpha for fill
            color = QColor(region.color)
            fill_color = QColor(color.red(), color.green(), color.blue(), 60)

            # Convert corners to screen coords
            p1 = self._w2s(region.x_min, region.y_min)
            p2 = self._w2s(region.x_max, region.y_max)

            # Draw filled rectangle
            p.setPen(QPen(color, 2, Qt.SolidLine))
            p.setBrush(QBrush(fill_color))
            p.drawRect(
                int(min(p1.x(), p2.x())),
                int(min(p1.y(), p2.y())),
                int(abs(p2.x() - p1.x())),
                int(abs(p2.y() - p1.y())),
            )

            # Draw label at top-left corner
            label_pos = QPointF(min(p1.x(), p2.x()) + 5, min(p1.y(), p2.y()) + 15)
            p.setPen(QPen(C_INFO, 1))
            p.setFont(QFont("monospace", 9, QFont.Bold))
            p.drawText(label_pos, region.label)

            # Draw ICP result if available
            if idx in self._icp_results:
                result = self._icp_results[idx]
                info_text = (
                    f"ΔX:{result.dx:.3f} ΔY:{result.dy:.3f} "
                    f"Δθ:{math.degrees(result.dyaw):.2f}°"
                )
                info_pos = QPointF(min(p1.x(), p2.x()) + 5, min(p1.y(), p2.y()) + 30)
                p.setFont(QFont("monospace", 8))
                p.drawText(info_pos, info_text)

    def _draw_preview_rectangle(self, p):
        """Layer 8: In-progress rectangle (dotted white)."""
        if self._mode == InteractionMode.DRAW_REGION and self._draw_state == DrawState.WAIT_CORNER2:
            if self._corner1 is not None:
                p.setPen(QPen(C_PREVIEW, 2, Qt.DotLine))
                p.setBrush(Qt.NoBrush)

                x1, y1 = self._corner1.x(), self._corner1.y()
                x2, y2 = self._current_mouse.x(), self._current_mouse.y()

                p.drawRect(
                    int(min(x1, x2)),
                    int(min(y1, y2)),
                    int(abs(x2 - x1)),
                    int(abs(y2 - y1)),
                )

    def _draw_info_overlay(self, p):
        """Layer 9: Info overlay (top-left)."""
        p.setPen(QPen(C_INFO, 1))
        p.setFont(QFont("monospace", 9))

        # Line 1: Zoom level
        y_pos = 20
        p.drawText(12, y_pos, f"Zoom: {self._scale:.0f} px/m")

        # Line 2: Point counts
        y_pos += 18
        front_count = len(self._front_points) if self._front_points is not None else 0
        rear_count = len(self._rear_points) if self._rear_points is not None else 0
        p.drawText(12, y_pos, f"Points: Front={front_count}  Rear={rear_count}")

        # Line 3: Mode indicator
        y_pos += 18
        mode_text = "Mode: DRAW REGION" if self._mode == InteractionMode.DRAW_REGION else "Mode: PAN"
        p.drawText(12, y_pos, mode_text)

        if self._mode == InteractionMode.DRAW_REGION and self._draw_state == DrawState.WAIT_CORNER2:
            y_pos += 18
            p.drawText(12, y_pos, "Click second corner (Right-click to cancel)")
