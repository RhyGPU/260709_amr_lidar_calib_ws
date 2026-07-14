#!/usr/bin/env python3
"""
ROI (Region Of Interest) management for LiDAR point filtering.

PySide6 port of scripts/region_manager.py (pyqtSignal → Signal). Logic unchanged.
"""

from dataclasses import dataclass, field
from typing import List

import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor


@dataclass
class Region:
    """Rectangle region for LiDAR point filtering (world coords, meters)."""
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    color: QColor = field(default_factory=lambda: QColor(0x4e, 0xc9, 0xb0))
    label: str = ""

    def contains_point(self, x: float, y: float) -> bool:
        return (self.x_min <= x <= self.x_max and
                self.y_min <= y <= self.y_max)

    def width(self) -> float:
        return self.x_max - self.x_min

    def height(self) -> float:
        return self.y_max - self.y_min


class RegionManager(QObject):
    """Manager for multiple ROI regions."""

    regions_changed = Signal()

    # 8 distinct colors for dark background
    _color_palette = [
        QColor(0x4e, 0xc9, 0xb0),  # teal
        QColor(0xce, 0x91, 0x78),  # salmon
        QColor(0xdc, 0xdc, 0xaa),  # khaki
        QColor(0x9c, 0xdc, 0xfe),  # light blue
        QColor(0xc5, 0x86, 0xc0),  # purple
        QColor(0x6a, 0x99, 0x55),  # green
        QColor(0xd7, 0xba, 0x7d),  # gold
        QColor(0x56, 0x9c, 0xd6),  # blue
    ]

    def __init__(self):
        super().__init__()
        self._regions: List[Region] = []

    def add_region(self, x1: float, y1: float, x2: float, y2: float) -> int:
        """Add region (coords sorted to min/max). Returns its index."""
        x_min, x_max = min(x1, x2), max(x1, x2)
        y_min, y_max = min(y1, y2), max(y1, y2)

        color = self._color_palette[len(self._regions) % len(self._color_palette)]
        label = f"Region {len(self._regions) + 1}"

        self._regions.append(Region(
            x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max,
            color=color, label=label))
        self.regions_changed.emit()
        return len(self._regions) - 1

    def remove_region(self, index: int):
        if 0 <= index < len(self._regions):
            self._regions.pop(index)
            self.regions_changed.emit()

    def clear_all(self):
        if self._regions:
            self._regions.clear()
            self.regions_changed.emit()

    def get_regions(self) -> List[Region]:
        return self._regions.copy()

    def get_region(self, index: int) -> Region:
        return self._regions[index]

    def region_count(self) -> int:
        return len(self._regions)


def filter_points(points: np.ndarray, region: Region) -> np.ndarray:
    """Filter (N,2) points to those inside `region`. Returns (M,2), M<=N."""
    if points.size == 0:
        return points
    mask = (points[:, 0] >= region.x_min) & (points[:, 0] <= region.x_max) & \
           (points[:, 1] >= region.y_min) & (points[:, 1] <= region.y_max)
    return points[mask]
