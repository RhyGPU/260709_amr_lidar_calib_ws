#!/usr/bin/env python3
"""
SVD-based ICP alignment for 2D point clouds (scipy-free).

2D Iterative Closest Point (ICP) using Singular Value Decomposition (SVD) for the
rigid-body transform estimation. Mutual nearest-neighbor (NN) correspondences are
found with a pure-numpy brute-force search (no scipy KDTree) — point clouds are
small (~165 pts after downsample), so O(n*m) is cheap and removes the scipy
dependency (see docs/adr/ADR-001).

Units/frames: input clouds are (N,2) float, meters, in a common frame.
Original (ROS2): scripts/icp_algorithm.py of lidar_calibration_2d.
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class ICPConfig:
    """Configuration parameters for ICP alignment."""
    max_iterations: int = 50
    transform_epsilon: float = 1e-6
    max_correspondence_dist: float = 0.3  # meters
    min_correspondences: int = 30


@dataclass
class CalibrationResult:
    """Result of ICP calibration. dx/dy in meters, dyaw in radians."""
    dx: float = 0.0
    dy: float = 0.0
    dyaw: float = 0.0
    mean_correspondence_distance: float = float('inf')
    num_correspondences: int = 0
    converged: bool = False


def compute_svd_transform_2d(
    correspondences: List[Tuple[np.ndarray, np.ndarray]]
) -> Tuple[bool, np.ndarray, np.ndarray]:
    """
    Compute 2D rigid-body transform (R, t) aligning source points to target points
    via SVD on the cross-covariance matrix.

    Given N pairs (p_i, q_i):
      1. centroids p_bar, q_bar
      2. center, build 2x2 cross-covariance H = sum(p' @ q'^T)
      3. SVD H = U S Vt
      4. R = Vt.T @ U.T (reflection-corrected if det < 0)
      5. t = q_bar - R @ p_bar

    Args:
        correspondences: list of (source_pt, target_pt), each a (2,) array.

    Returns:
        (success, R(2,2), t(2,)). success=False if fewer than 3 pairs.
    """
    n = len(correspondences)
    if n < 3:
        return False, np.eye(2), np.zeros(2)

    p_bar = np.zeros(2)
    q_bar = np.zeros(2)
    for p, q in correspondences:
        p_bar += p
        q_bar += q
    p_bar /= n
    q_bar /= n

    H = np.zeros((2, 2))
    for p, q in correspondences:
        H += np.outer(p - p_bar, q - q_bar)

    U, _, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[1, :] *= -1.0
        R = Vt.T @ U.T

    t = q_bar - R @ p_bar
    return True, R, t


def _mutual_nn_bruteforce(
    source: np.ndarray, target: np.ndarray, thresh_sq: float
) -> Tuple[list, float]:
    """
    Mutual nearest-neighbor correspondences via pure-numpy brute force.

    Replaces scipy KDTree (ADR-001). For each source point find its nearest target
    and vice-versa; keep pairs that are mutual AND within sqrt(thresh_sq).

    Args:
        source: (N,2) array. target: (M,2) array. thresh_sq: squared max distance.

    Returns:
        (correspondences, total_dist) where correspondences is a list of
        (source_pt, target_pt) and total_dist is the sum of accepted distances.
    """
    if source.shape[0] == 0 or target.shape[0] == 0:
        return [], 0.0

    # Pairwise squared distances (N, M). N,M ~165 → ~27k entries, trivial.
    diff = source[:, None, :] - target[None, :, :]
    d2 = np.einsum('nmk,nmk->nm', diff, diff)

    idx_st = np.argmin(d2, axis=1)   # nearest target index for each source
    idx_ts = np.argmin(d2, axis=0)   # nearest source index for each target

    correspondences = []
    total_dist = 0.0
    for i in range(source.shape[0]):
        j = int(idx_st[i])
        dist_sq = float(d2[i, j])
        if dist_sq >= thresh_sq:
            continue
        if int(idx_ts[j]) == i:  # mutual
            correspondences.append((source[i], target[j]))
            total_dist += float(np.sqrt(dist_sq))
    return correspondences, total_dist


def align_svd_icp(
    source: np.ndarray,
    target: np.ndarray,
    config: ICPConfig
) -> CalibrationResult:
    """
    Run 2D ICP aligning `source` to `target` (both (N,2) meters, same frame).

    Per iteration: mutual-NN correspondences (brute force) → threshold filter →
    SVD transform → apply to source → accumulate → convergence check.

    Returns CalibrationResult with cumulative dx, dy (m), dyaw (rad).
    """
    result = CalibrationResult()

    if source.shape[0] == 0 or target.shape[0] == 0:
        return result

    source = source.copy()
    R_total = np.eye(2)
    t_total = np.zeros(2)
    thresh_sq = config.max_correspondence_dist ** 2

    for _ in range(config.max_iterations):
        correspondences, total_dist = _mutual_nn_bruteforce(source, target, thresh_sq)

        if len(correspondences) < config.min_correspondences:
            result.num_correspondences = len(correspondences)
            return result  # not enough correspondences → unconverged

        result.mean_correspondence_distance = total_dist / len(correspondences)
        result.num_correspondences = len(correspondences)

        success, R_inc, t_inc = compute_svd_transform_2d(correspondences)
        if not success:
            return result

        source = (R_inc @ source.T).T + t_inc

        # Accumulate: T_total = T_inc * T_prev
        t_total = R_inc @ t_total + t_inc
        R_total = R_inc @ R_total

        translation_delta = np.linalg.norm(t_inc)
        rotation_delta = abs(np.arctan2(R_inc[1, 0], R_inc[0, 0]))
        if (translation_delta < config.transform_epsilon and
                rotation_delta < config.transform_epsilon):
            result.converged = True
            break

    result.dyaw = float(np.arctan2(R_total[1, 0], R_total[0, 0]))
    result.dx = float(t_total[0])
    result.dy = float(t_total[1])

    # If iterations exhausted but close enough, still mark converged (parity with C++).
    if not result.converged and result.mean_correspondence_distance < 0.05:
        result.converged = True

    return result
