#!/usr/bin/env python3
"""
TF calculation utilities for LiDAR calibration (merged_lidar-centric).

Pure math — no ROS, no Qt, no scipy. merged_lidar is the reference frame (origin);
scan_front / scan_rear are positioned relative to it via jog transforms.

Conventions (numeric-coding §1/§2): 2D rigid transforms, yaw in radians, active
transform, frame composition T_result = T_parent * T_child. flipped = upside-down
(roll=pi) handled as a Y-negate in 2D at the point-transform boundary.
Original (ROS2): scripts/tf_calculator.py of lidar_calibration_2d.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

import yaml


@dataclass
class TFTransform2D:
    """2D rigid transform. tx/ty meters, yaw radians, flipped=upside-down."""
    tx: float = 0.0
    ty: float = 0.0
    yaw: float = 0.0
    flipped: bool = False


@dataclass
class CalibrationOutput:
    """Complete calibration output (merged_lidar-centric)."""
    icp_correction: TFTransform2D
    jog_front: TFTransform2D
    jog_rear_original: TFTransform2D
    jog_rear_corrected: TFTransform2D
    num_successful: int = 0
    median_correspondence_distance: float = 0.0


def compute_median(values: List[float]) -> float:
    """Median of a list (empty → 0.0)."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 0:
        return (s[n // 2 - 1] + s[n // 2]) / 2.0
    return s[n // 2]


def compose_tf(parent: TFTransform2D, child: TFTransform2D) -> TFTransform2D:
    """Compose two 2D transforms: T_result = T_parent * T_child."""
    result_yaw = parent.yaw + child.yaw
    result_tx = (parent.tx
                 + math.cos(parent.yaw) * child.tx
                 - math.sin(parent.yaw) * child.ty)
    result_ty = (parent.ty
                 + math.sin(parent.yaw) * child.tx
                 + math.cos(parent.yaw) * child.ty)
    return TFTransform2D(tx=result_tx, ty=result_ty, yaw=result_yaw,
                         flipped=child.flipped)


def invert_tf(tf: TFTransform2D) -> TFTransform2D:
    """Inverse of a 2D rigid transform."""
    inv_yaw = -tf.yaw
    inv_tx = -(math.cos(tf.yaw) * tf.tx + math.sin(tf.yaw) * tf.ty)
    inv_ty = -(-math.sin(tf.yaw) * tf.tx + math.cos(tf.yaw) * tf.ty)
    return TFTransform2D(tx=inv_tx, ty=inv_ty, yaw=inv_yaw, flipped=tf.flipped)


def normalize_angle(angle: float) -> float:
    """Normalize angle to [-pi, pi]."""
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def compute_symmetry_info(jog_front: TFTransform2D, jog_rear: TFTransform2D) -> dict:
    """
    Symmetry analysis between front/rear about merged_lidar origin.

    Ideal symmetric rear = (-front.tx, -front.ty, front.yaw + pi).
    Returns dict: ideal_rear_tx/ty/yaw, delta_tx/ty/yaw, is_symmetric.
    Thresholds: 2 mm position, 0.5 deg yaw.
    """
    ideal_rear_tx = -jog_front.tx
    ideal_rear_ty = -jog_front.ty
    ideal_rear_yaw = normalize_angle(jog_front.yaw + math.pi)

    delta_tx = abs(jog_rear.tx - ideal_rear_tx)
    delta_ty = abs(jog_rear.ty - ideal_rear_ty)
    delta_yaw = abs(normalize_angle(jog_rear.yaw - ideal_rear_yaw))

    threshold_pos = 0.002
    threshold_yaw = math.radians(0.5)
    is_symmetric = (delta_tx < threshold_pos
                    and delta_ty < threshold_pos
                    and delta_yaw < threshold_yaw)

    return {
        'ideal_rear_tx': ideal_rear_tx,
        'ideal_rear_ty': ideal_rear_ty,
        'ideal_rear_yaw': ideal_rear_yaw,
        'delta_tx': delta_tx,
        'delta_ty': delta_ty,
        'delta_yaw': delta_yaw,
        'is_symmetric': is_symmetric,
    }


def mirror_front_to_rear(jog_front: TFTransform2D, rear_flipped: bool) -> TFTransform2D:
    """Perfectly symmetric rear transform from front (mirror about merged origin)."""
    return TFTransform2D(
        tx=-jog_front.tx,
        ty=-jog_front.ty,
        yaw=normalize_angle(jog_front.yaw + math.pi),
        flipped=rear_flipped,
    )


def apply_symmetric_correction(
    jog_front: TFTransform2D,
    jog_rear_original: TFTransform2D,
    icp_correction: TFTransform2D,
) -> tuple:
    """
    Split the ICP correction equally: front gets -C/2, rear gets +C/2.

    Distributes the error symmetrically (≈ averaging front-ref and rear-ref ICP),
    preserving the relative transform. Returns (sym_front, sym_rear).
    """
    half_corr = TFTransform2D(
        tx=icp_correction.tx / 2.0,
        ty=icp_correction.ty / 2.0,
        yaw=icp_correction.yaw / 2.0,
    )
    neg_half_corr = TFTransform2D(
        tx=-icp_correction.tx / 2.0,
        ty=-icp_correction.ty / 2.0,
        yaw=-icp_correction.yaw / 2.0,
    )

    sym_front = compose_tf(neg_half_corr, jog_front)
    sym_front.flipped = jog_front.flipped

    sym_rear = compose_tf(half_corr, jog_rear_original)
    sym_rear.flipped = jog_rear_original.flipped

    return sym_front, sym_rear


def compute_full_calibration_merged(
    med_dx: float,
    med_dy: float,
    med_dyaw: float,
    jog_front: TFTransform2D,
    jog_rear: TFTransform2D,
    num_successful: int,
    med_corr_dist: float,
) -> CalibrationOutput:
    """
    Build calibration output in the merged_lidar frame.

    jog_rear_corrected = compose_tf(icp_correction, jog_rear).
    """
    icp_correction = TFTransform2D(tx=med_dx, ty=med_dy, yaw=med_dyaw)
    jog_rear_corrected = compose_tf(icp_correction, jog_rear)

    return CalibrationOutput(
        icp_correction=icp_correction,
        jog_front=jog_front,
        jog_rear_original=jog_rear,
        jog_rear_corrected=jog_rear_corrected,
        num_successful=num_successful,
        median_correspondence_distance=med_corr_dist,
    )


def save_calibration_yaml(
    output: CalibrationOutput,
    filepath: str,
    scan_topic_front: str = "/scan_front",
    scan_topic_rear: str = "/scan_rear",
    num_samples: int = 0,
    average_filter_enabled: bool = False,
    downsample_stride: int = 1,
):
    """Save calibration results to YAML (merged_lidar-centric). Format frozen (ADR-002)."""
    output_path = Path(filepath)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    data = {
        "calibration": {
            "reference_frame": "merged_lidar",
            "reference_sensor": scan_topic_front,
            "calibrated_sensor": scan_topic_rear,
            "icp_correction": {
                "dx": round(float(output.icp_correction.tx), 6),
                "dy": round(float(output.icp_correction.ty), 6),
                "dyaw_rad": round(float(output.icp_correction.yaw), 6),
                "dyaw_deg": round(float(math.degrees(output.icp_correction.yaw)), 2),
            },
            "merged_lidar_to_scan_front": {
                "tx": round(float(output.jog_front.tx), 6),
                "ty": round(float(output.jog_front.ty), 6),
                "yaw_rad": round(float(output.jog_front.yaw), 6),
                "yaw_deg": round(float(math.degrees(output.jog_front.yaw)), 2),
                "flipped": bool(output.jog_front.flipped),
            },
            "merged_lidar_to_scan_rear_original": {
                "tx": round(float(output.jog_rear_original.tx), 6),
                "ty": round(float(output.jog_rear_original.ty), 6),
                "yaw_rad": round(float(output.jog_rear_original.yaw), 6),
                "yaw_deg": round(float(math.degrees(output.jog_rear_original.yaw)), 2),
                "flipped": bool(output.jog_rear_original.flipped),
            },
            "merged_lidar_to_scan_rear_corrected": {
                "tx": round(float(output.jog_rear_corrected.tx), 6),
                "ty": round(float(output.jog_rear_corrected.ty), 6),
                "yaw_rad": round(float(output.jog_rear_corrected.yaw), 6),
                "yaw_deg": round(float(math.degrees(output.jog_rear_corrected.yaw)), 2),
                "flipped": bool(output.jog_rear_corrected.flipped),
            },
            "statistics": {
                "num_samples": num_samples,
                "successful_alignments": int(output.num_successful),
                "median_correspondence_distance": round(
                    float(output.median_correspondence_distance), 4),
                "average_filter_enabled": average_filter_enabled,
                "downsample_stride": downsample_stride,
            },
        }
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# Auto-generated by lidar_2d_calibration_window\n")
        f.write(f"# Generated: {timestamp}\n")
        f.write("# Method: merged_lidar-centric ICP alignment\n")
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    print(f"Results saved to: {output_path}")
