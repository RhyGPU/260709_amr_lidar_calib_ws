#!/usr/bin/env python3
"""
Calibration orchestration (merged_lidar-centric). PySide6 port of
scripts/calibration_engine.py (pyqtSignal → Signal, scipy-free core).

Workflow:
  1. Raw scan points (sensor-local) + jog transforms (merged→front, merged→rear)
  2. Transform both scans into merged_lidar frame
  3. Region-based ICP (rear→front in merged frame)
  4. Aggregate with MAD (Median Absolute Deviation) outlier rejection
  5. corrected jog_rear = compose_tf(icp_correction, jog_rear)

NOTE: point→merged transform is provided by the io layer's
ScanSource.transform_points_2d (injected to avoid coupling core→io).
"""

import math
from typing import Callable, List, Optional

import numpy as np
from PySide6.QtCore import QObject, Signal

from core.icp_algorithm import ICPConfig, CalibrationResult, align_svd_icp
from core.region_manager import Region, filter_points
from core.tf_calculator import (
    TFTransform2D,
    CalibrationOutput,
    compute_median,
    compute_full_calibration_merged,
    save_calibration_yaml,
)


class CalibrationEngine(QObject):
    """Orchestrates multi-region calibration in the merged_lidar frame."""

    region_result_ready = Signal(int, object)
    calibration_complete = Signal(object)
    calibration_error = Signal(str)
    progress_updated = Signal(str)

    def __init__(self, transform_fn: Optional[Callable] = None):
        """
        Args:
            transform_fn: callable(points (N,2), tf TFTransform2D) -> (N,2).
                Injected from io.scan_source.ScanSource.transform_points_2d.
                Falls back to a built-in 2D transform if None.
        """
        super().__init__()
        self._last_output = None
        self._transform_fn = transform_fn or self._default_transform

    @property
    def last_output(self):
        return self._last_output

    @staticmethod
    def _default_transform(points: np.ndarray, tf: TFTransform2D) -> np.ndarray:
        """2D transform with flip (roll=pi → Y-negate). Same as ScanSource."""
        if points is None or len(points) == 0:
            return points
        px = points[:, 0]
        py = -points[:, 1] if tf.flipped else points[:, 1]
        cos_y, sin_y = math.cos(tf.yaw), math.sin(tf.yaw)
        return np.column_stack([
            px * cos_y - py * sin_y + tf.tx,
            px * sin_y + py * cos_y + tf.ty,
        ])

    def run_calibration(
        self,
        raw_front: np.ndarray,
        raw_rear: np.ndarray,
        jog_front: TFTransform2D,
        jog_rear: TFTransform2D,
        regions: List[Region],
        config: ICPConfig,
    ):
        """Run region-based ICP calibration in the merged_lidar frame."""
        try:
            self.progress_updated.emit("Transforming scans to merged_lidar frame...")

            front_merged = self._transform_fn(raw_front, jog_front)
            rear_merged = self._transform_fn(raw_rear, jog_rear)

            if front_merged is None or len(front_merged) == 0:
                self.calibration_error.emit("No front scan points available")
                return
            if rear_merged is None or len(rear_merged) == 0:
                self.calibration_error.emit("No rear scan points available")
                return

            self.progress_updated.emit(
                f"Points in merged frame: front={len(front_merged)}, "
                f"rear={len(rear_merged)}")

            region_results = []
            for i, region in enumerate(regions):
                self.progress_updated.emit(
                    f"Processing region {i + 1}/{len(regions)}: {region.label}")

                filtered_front = filter_points(front_merged, region)
                filtered_rear = filter_points(rear_merged, region)

                if len(filtered_front) < config.min_correspondences:
                    self.progress_updated.emit(
                        f"Region {i + 1} skipped: front points "
                        f"({len(filtered_front)} < {config.min_correspondences})")
                    continue
                if len(filtered_rear) < config.min_correspondences:
                    self.progress_updated.emit(
                        f"Region {i + 1} skipped: rear points "
                        f"({len(filtered_rear)} < {config.min_correspondences})")
                    continue

                result = align_svd_icp(filtered_rear, filtered_front, config)
                self.region_result_ready.emit(i, result)
                region_results.append(result)

                status = "converged" if result.converged else "did not converge"
                self.progress_updated.emit(
                    f"Region {i + 1} {status}: "
                    f"dx={result.dx:.4f}, dy={result.dy:.4f}, "
                    f"dyaw={math.degrees(result.dyaw):.3f}°, "
                    f"mean_dist={result.mean_correspondence_distance:.4f}")

            converged_results = [r for r in region_results if r.converged]
            if len(converged_results) == 0:
                self.calibration_error.emit("No regions converged successfully")
                return

            self.progress_updated.emit(
                f"Aggregating {len(converged_results)} converged regions...")

            dx_values = [r.dx for r in converged_results]
            dy_values = [r.dy for r in converged_results]
            dyaw_values = [r.dyaw for r in converged_results]
            corr_dist_values = [r.mean_correspondence_distance for r in converged_results]

            dx_filtered = self.reject_outliers_mad(dx_values)
            dy_filtered = self.reject_outliers_mad(dy_values)
            dyaw_filtered = self.reject_outliers_mad(dyaw_values)
            corr_dist_filtered = self.reject_outliers_mad(corr_dist_values)

            if not dx_filtered or not dy_filtered or not dyaw_filtered:
                self.calibration_error.emit("All results rejected as outliers")
                return

            self.progress_updated.emit(
                f"Outlier rejection: kept {len(dx_filtered)}/{len(dx_values)} results")

            output = compute_full_calibration_merged(
                compute_median(dx_filtered),
                compute_median(dy_filtered),
                compute_median(dyaw_filtered),
                jog_front, jog_rear,
                len(dx_filtered),
                compute_median(corr_dist_filtered),
            )

            self._last_output = output
            self.progress_updated.emit("Calibration complete!")
            self.calibration_complete.emit(output)

        except Exception as e:  # noqa: BLE001 — surface any failure to the UI lane
            error_msg = f"Calibration failed: {str(e)}"
            self.progress_updated.emit(error_msg)
            self.calibration_error.emit(error_msg)

    @staticmethod
    def reject_outliers_mad(values: List[float], threshold: float = 2.0) -> List[float]:
        """Reject outliers using Median Absolute Deviation (MAD)."""
        if len(values) <= 1:
            return values
        median = compute_median(values)
        deviations = [abs(v - median) for v in values]
        mad = compute_median(deviations)
        if mad == 0.0:
            return values
        return [v for v in values if abs(v - median) <= threshold * mad]

    def save_results(self, output: CalibrationOutput, filepath: str):
        save_calibration_yaml(output, filepath)
        self.progress_updated.emit(f"Results saved to {filepath}")
