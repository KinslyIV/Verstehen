import math
from typing import Literal, TypeGuard

from pydantic import BaseModel, Field


class RegionTuning(BaseModel):
    dilation: float = 20
    blur: float = 40
    bitmap: int = 256
    edge_alpha: float = 0.2
    enabled: bool = True


class PhysicsTuning(BaseModel):
    charge_strength: float = -240
    link_strength: float = 1
    link_distance: float = 40
    gravity: float = 0.12
    cluster_pull: float = 0.15
    velocity_decay: float = 0.4
    depth_mode: Literal["off", "vertical", "radial"] = "off"
    depth_strength: float = 0.8
    depth_spacing: float = 60
    depth_base_radius: float = 220


class GraphRenderSettings(BaseModel):
    size_units: Literal["world"] = "world"
    node_size: float = 2
    edge_width: float = 1
    arrow_length: float = 2
    label_zoom: float = 0.5
    label_size: float = 3
    cluster_labels: bool = True
    cluster_label_size: float = 14
    regions: RegionTuning = Field(default_factory=RegionTuning)
    physics: PhysicsTuning = Field(default_factory=PhysicsTuning)


LADDERS = {
    "node_size": [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8, 12],
    "edge_width": [0.1, 0.2, 0.4, 0.6, 0.8, 1, 1.5, 2, 3, 4, 6],
    "arrow_length": [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8, 12],
    "label_size": [0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8, 12, 16],
    "cluster_label_size": [7, 8, 9, 10, 12, 14, 16, 18, 20, 24, 28],
    "label_zoom": [0.125, 0.175, 0.25, 0.35, 0.45, 0.5, 0.75, 1, 1.5, 2, 3],
    "dilation": [4, 5, 7.5, 10, 15, 20, 30, 40, 60, 80, 120],
    "blur": [10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 120],
    "edge_alpha": [0.025, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.4, 0.6, 0.8, 1],
    "bitmap": [128, 192, 256, 384, 512],
}
RANGES = {
    "charge_strength": (-480, -120),
    "link_strength": (0.25, 4),
    "link_distance": (10, 160),
    "gravity": (0.03, 0.48),
    "cluster_pull": (0, 1),
    "velocity_decay": (0.18, 0.9),
    "depth_strength": (0.2, 3.2),
    "depth_spacing": (15, 240),
    "depth_base_radius": (55, 880),
}


def finite_number(value: object) -> TypeGuard[int | float]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def sanitize_render_settings(raw: object) -> GraphRenderSettings:
    data = raw if isinstance(raw, dict) else {}
    defaults = GraphRenderSettings().model_dump()
    output = defaults.copy()
    for key in (
        "node_size",
        "edge_width",
        "arrow_length",
        "label_zoom",
        "label_size",
        "cluster_label_size",
    ):
        value = data.get(key)
        if finite_number(value):
            output[key] = min(LADDERS[key], key=lambda stop: abs(stop - value))
    if isinstance(data.get("cluster_labels"), bool):
        output["cluster_labels"] = data["cluster_labels"]
    for section in ("regions", "physics"):
        nested = data.get(section)
        if not isinstance(nested, dict):
            continue
        result = defaults[section].copy()
        for key, value in nested.items():
            if key in LADDERS and finite_number(value):
                result[key] = min(LADDERS[key], key=lambda stop: abs(stop - value))
            elif key in RANGES and finite_number(value):
                low, high = RANGES[key]
                result[key] = min(max(value, low), high)
            elif key == "enabled" and isinstance(value, bool):
                result[key] = value
            elif key == "depth_mode":
                result[key] = value if value in ("vertical", "radial") else "off"
        output[section] = result
    if data.get("size_units") != "world":
        for key in ("node_size", "arrow_length", "label_size"):
            output[key] = defaults[key]
        output["regions"]["dilation"] = 20
    return GraphRenderSettings.model_validate(output)
