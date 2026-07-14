#!/usr/bin/env python3
"""
sensor_io.config_loader — sensors.yaml 로드 및 스키마 검증.

공개 함수:
    load_sensor_config(path) -> dict

반환 dict는 ScanSource(config) 및 ScanSource.get_initial_tfs()가
그대로 소비할 수 있는 형식이어야 한다(계약: docs/PORTING_PLAN.md §3.3).
신뢰경계: 외부 파일 입력 — 누락/타입 오류 시 필드명 포함 ValueError 발생.
"""

from pathlib import Path
from typing import Any

import yaml

# 허용 discriminate_by 값 (PORTING_PLAN.md §3.3)
_VALID_DISCRIMINATE_BY = {"port", "source_ip"}

# 필수 mounting 하위 필드 및 기대 타입
_MOUNTING_FIELDS: dict[str, type] = {
    "tx": (int, float),
    "ty": (int, float),
    "yaw_deg": (int, float),
    "flipped": bool,
}


def _require(mapping: dict, field: str, context: str) -> Any:
    """mapping에서 field를 꺼내 반환. 없으면 context 포함 ValueError."""
    if field not in mapping:
        raise ValueError(f"sensors.yaml: 필수 필드 누락 — '{context}.{field}'")
    return mapping[field]


def _validate_network(network: dict) -> None:
    """network 섹션 구조·타입·discriminate_by 값 검증."""
    if not isinstance(network, dict):
        raise ValueError("sensors.yaml: 'network' 는 매핑(dict)이어야 합니다")

    _require(network, "bind_ip", "network")
    if not isinstance(network["bind_ip"], str):
        raise ValueError("sensors.yaml: 'network.bind_ip' 는 문자열이어야 합니다")

    for side in ("front", "rear"):
        node = _require(network, side, "network")
        if not isinstance(node, dict):
            raise ValueError(f"sensors.yaml: 'network.{side}' 는 매핑(dict)이어야 합니다")
        ip_val = _require(node, "ip", f"network.{side}")
        if not isinstance(ip_val, str):
            raise ValueError(f"sensors.yaml: 'network.{side}.ip' 는 문자열이어야 합니다")
        port_val = _require(node, "port", f"network.{side}")
        if not isinstance(port_val, int):
            raise ValueError(f"sensors.yaml: 'network.{side}.port' 는 정수(int)이어야 합니다")

    disc = _require(network, "discriminate_by", "network")
    if disc not in _VALID_DISCRIMINATE_BY:
        raise ValueError(
            f"sensors.yaml: 'network.discriminate_by' 값 '{disc}' 은(는) 허용되지 않습니다 "
            f"— 허용값: {sorted(_VALID_DISCRIMINATE_BY)}"
        )


def _validate_mounting(mounting: dict) -> None:
    """mounting 섹션 구조·필드·타입 검증."""
    if not isinstance(mounting, dict):
        raise ValueError("sensors.yaml: 'mounting' 는 매핑(dict)이어야 합니다")

    for side in ("front", "rear"):
        node = _require(mounting, side, "mounting")
        if not isinstance(node, dict):
            raise ValueError(f"sensors.yaml: 'mounting.{side}' 는 매핑(dict)이어야 합니다")
        for field, expected_types in _MOUNTING_FIELDS.items():
            val = _require(node, field, f"mounting.{side}")
            if not isinstance(val, expected_types):
                raise ValueError(
                    f"sensors.yaml: 'mounting.{side}.{field}' 타입 오류 "
                    f"— 기대 {expected_types}, 실제 {type(val).__name__}"
                )


def _validate_preprocessing(preprocessing: dict) -> None:
    """preprocessing 섹션 구조·타입 검증."""
    if not isinstance(preprocessing, dict):
        raise ValueError("sensors.yaml: 'preprocessing' 는 매핑(dict)이어야 합니다")

    for field in ("min_range_m", "max_range_m"):
        val = _require(preprocessing, field, "preprocessing")
        if not isinstance(val, (int, float)):
            raise ValueError(
                f"sensors.yaml: 'preprocessing.{field}' 는 수치형이어야 합니다"
            )

    aef = _require(preprocessing, "enable_average_filter", "preprocessing")
    if not isinstance(aef, bool):
        raise ValueError(
            "sensors.yaml: 'preprocessing.enable_average_filter' 는 bool이어야 합니다"
        )


def load_sensor_config(path: str) -> dict:
    """
    sensors.yaml을 로드하고 스키마를 검증하여 반환한다.

    반환 dict 구조(PORTING_PLAN.md §3.3):
        {
            'network': { 'bind_ip', 'front': {'ip','port'}, 'rear': {'ip','port'},
                         'discriminate_by' },
            'mounting': { 'front': {'tx','ty','yaw_deg','flipped'},
                          'rear':  {'tx','ty','yaw_deg','flipped'} },
            'preprocessing': { 'min_range_m', 'max_range_m', 'enable_average_filter' },
        }

    ScanSource(config) 및 ScanSource.get_initial_tfs()가 직접 소비 가능.

    Args:
        path: sensors.yaml 파일 경로 (절대·상대 모두 허용).

    Returns:
        검증 완료된 설정 dict.

    Raises:
        FileNotFoundError: 파일이 없을 때.
        ValueError: 필수 필드 누락, 타입 오류, discriminate_by 잘못된 값.
    """
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"sensors.yaml 파일을 찾을 수 없습니다: {resolved}")

    try:
        with resolved.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ValueError(f"sensors.yaml: YAML 파싱 오류 — {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("sensors.yaml: 최상위 구조가 매핑(dict)이어야 합니다")

    # 최상위 필수 섹션 확인
    for section in ("network", "mounting", "preprocessing"):
        if section not in raw:
            raise ValueError(f"sensors.yaml: 필수 섹션 누락 — '{section}'")

    _validate_network(raw["network"])
    _validate_mounting(raw["mounting"])
    _validate_preprocessing(raw["preprocessing"])

    return raw
