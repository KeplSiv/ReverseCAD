"""Versioned capture and API contracts. All external numbers must be finite."""
from __future__ import annotations

import math
import re
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")


def identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError("Identifier must contain 1–96 letters, digits, underscores or hyphens")
    return value


def safe_asset_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or len(value) > 240 or "\\" in value or "\x00" in value or path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise ValueError("Asset path must be a relative path without traversal")
    if any(part.startswith(".") for part in path.parts):
        raise ValueError("Hidden asset names are not permitted")
    allowed_roots = {"rgb", "depth", "confidence", "masks", "video"}
    allowed_files = {"manifest.json", "frames.jsonl", "checksums.json", "annotations.json", "motion.jsonl", "capture_diagnostics.json"}
    if (len(path.parts) == 1 and value not in allowed_files) or (len(path.parts) > 1 and path.parts[0] not in allowed_roots):
        raise ValueError("Asset is not an allowed capture-package file")
    return value


def finite(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("NaN and infinity are not permitted")
    if isinstance(value, dict):
        for v in value.values():
            finite(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            finite(v)
    return value


class Contract(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def check_finite(cls, data):
        return finite(data)


class Segment(Contract):
    segment_id: str
    T_object_world: list[float] = Field(min_length=16, max_length=16)
    registered: bool

    @field_validator("segment_id")
    @classmethod
    def valid_id(cls, value):
        return identifier(value)


class ScanManifest(Contract):
    schema_version: Literal[1]
    scan_id: str
    source: Literal["synthetic", "arkit", "camera_manual"]
    device: str = Field(min_length=1, max_length=200)
    created_at: str
    complete: bool
    segments: list[Segment] = Field(min_length=1, max_length=32)
    frame_count: int = Field(ge=1, le=240)

    @field_validator("scan_id")
    @classmethod
    def valid_id(cls, value):
        return identifier(value)


class FrameQuality(Contract):
    blur_score: float = Field(ge=0)
    accepted: bool
    reasons: list[str] = Field(default_factory=list, max_length=64)


class CaptureFrame(Contract):
    schema_version: Literal[1]
    scan_id: str
    segment_id: str
    frame_id: str
    timestamp_s: float = Field(ge=0)
    rgb_path: str
    rgb_width: int = Field(gt=0, le=8192)
    rgb_height: int = Field(gt=0, le=8192)
    orientation: Literal["up"] = "up"
    depth_path: str | None = None
    depth_width: int = Field(ge=0, le=2048)
    depth_height: int = Field(ge=0, le=2048)
    depth_row_bytes: int = Field(ge=0, le=65536)
    depth_byte_order: Literal["little"] = "little"
    confidence_path: str | None = None
    mask_path: str | None = None
    depth_calibration_mode: Literal["pixel_center", "native_arkit"] = "pixel_center"
    depth_intrinsics: list[float] | None = Field(default=None, min_length=9, max_length=9)
    intrinsics: list[float] = Field(min_length=9, max_length=9)
    intrinsics_width: int = Field(gt=0, le=8192)
    intrinsics_height: int = Field(gt=0, le=8192)
    T_world_camera: list[float] = Field(min_length=16, max_length=16)
    tracking_state: Literal["normal", "limited", "unavailable"]
    quality: FrameQuality

    @field_validator("scan_id", "segment_id", "frame_id")
    @classmethod
    def valid_id(cls, value):
        return identifier(value)

    @field_validator("rgb_path", "depth_path", "confidence_path", "mask_path")
    @classmethod
    def valid_path(cls, value):
        return safe_asset_path(value) if value else value

    @model_validator(mode="after")
    def dimensions(self):
        if self.depth_path and (not self.depth_width or not self.depth_height or self.depth_row_bytes < self.depth_width * 4):
            raise ValueError("Depth dimensions and stride disagree")
        if self.depth_path and self.depth_row_bytes % 4:
            raise ValueError("Float32 depth row stride must be divisible by four")
        if self.intrinsics[0] <= 0 or self.intrinsics[4] <= 0 or abs(self.intrinsics[8] - 1) > 1e-6:
            raise ValueError("Camera calibration must have positive focal lengths and K[2,2]=1")
        if self.rgb_width * self.rgb_height > 40_000_000:
            raise ValueError("RGB image exceeds decoded-pixel limit")
        return self


class Measurement(Contract):
    id: str
    name: str
    value: float
    unit: Literal["mm"]
    source: Literal["manual", "depth_fit", "design_inference", "multiview", "multiview_estimate", "symmetry"]
    confirmed: bool
    critical: bool
    uncertainty_mm: float | None = Field(default=None, ge=0)
    observation_ids: list[str] = Field(default_factory=list, max_length=240)


class Contact(Contract):
    id: str
    point_m: list[float] = Field(min_length=3, max_length=3)
    normal: list[float] = Field(min_length=3, max_length=3)
    radius_mm: float = Field(gt=0, le=1000)

    @field_validator("normal")
    @classmethod
    def nonzero_normal(cls, v):
        if sum(x*x for x in v) < 1e-10:
            raise ValueError("Contact normal must be nonzero")
        return v


class Annotations(Contract):
    repair_scope: Literal["general", "cube_exterior", "rectangular_planar", "automatic"] = "general"
    planar_thickness_mm: float | None = Field(default=None, gt=0, le=100)
    crop_min_m: list[float] | None = Field(default=None, min_length=3, max_length=3)
    crop_max_m: list[float] | None = Field(default=None, min_length=3, max_length=3)
    contacts: list[Contact] = Field(default_factory=list, max_length=32)
    damage_points_m: list[list[float]] = Field(default_factory=list, max_length=256)
    measurements: list[Measurement] = Field(default_factory=list, max_length=128)
    attachment_method: str = Field(default="", max_length=128)
    scale_reference: dict[str, float] | None = None
    evidence_state: Literal["missing_part", "fragment", "matching_part"] = "missing_part"

    @model_validator(mode="after")
    def constraints(self):
        if bool(self.crop_min_m) != bool(self.crop_max_m):
            raise ValueError("Crop requires both minimum and maximum")
        if self.crop_min_m and any(a >= b for a,b in zip(self.crop_min_m, self.crop_max_m)):
            raise ValueError("Crop minimum must precede maximum on each axis")
        if any(len(p) != 3 for p in self.damage_points_m):
            raise ValueError("Damage points must each contain three coordinates")
        if len({m.id for m in self.measurements}) != len(self.measurements):
            raise ValueError("Measurement identifiers must be unique")
        if self.scale_reference:
            if any(self.scale_reference.get(k, 0) <= 0 for k in ("measured_mm", "observed_mm")):
                raise ValueError("Scale reference needs positive measured_mm and observed_mm")
            if self.scale_reference.get("uncertainty_mm", -1) < 0:
                raise ValueError("Scale reference needs nonnegative uncertainty_mm")
        return self


class CreateScan(Contract):
    scan_id: str | None = None
    source: Literal["synthetic", "arkit", "camera_manual"]
    project_id: str | None = None

    @field_validator("scan_id", "project_id")
    @classmethod
    def valid_id(cls, value):
        return identifier(value) if value else value


class RepairRequest(Contract):
    scan_id: str
    family: Literal["bridge_handle", "cup_handle", "bracket"]
    parameters: dict[str, float] = Field(default_factory=dict, max_length=48)
    attachment_method: str = Field(min_length=1, max_length=128)
    mode: Literal["manual", "fixture", "live"] = "manual"
    acknowledge_uncertainty: bool = False
    request_id: str | None = None
    manufacturing: dict[str, Any] = Field(default_factory=dict)
    provider_consent: bool = False
    candidate_id: str | None = Field(default=None, max_length=128)

    @field_validator("scan_id", "request_id")
    @classmethod
    def valid_id(cls, value):
        return identifier(value) if value else value


class ReconstructionRequest(Contract):
    request_id: str | None = None
    compare_methods: bool = False

    @field_validator("request_id")
    @classmethod
    def valid_id(cls, value):
        return identifier(value) if value else value


class CandidateRequest(Contract):
    family: Literal["bridge_handle", "cup_handle", "bracket"]
    attachment_method: str = Field(min_length=1, max_length=128)


class LiveGeometryRequest(Contract):
    session_id: str
    sequence: int = Field(ge=0)
    vertices: list[tuple[float,float,float]] = Field(min_length=4,max_length=8000)
    triangles: list[tuple[int,int,int]] = Field(min_length=4,max_length=12000)
    camera_positions: list[tuple[float,float,float]] = Field(min_length=3,max_length=24)
    unit: Literal['m'] = 'm'

    @field_validator('session_id')
    @classmethod
    def live_session(cls,value): return identifier(value)

    @model_validator(mode='after')
    def valid_live_mesh(self):
        if any(abs(x)>100 for p in self.vertices+self.camera_positions for x in p):
            raise ValueError('AR coordinates exceed the live workspace')
        if any(min(f)<0 or max(f)>=len(self.vertices) or len(set(f))!=3 for f in self.triangles):
            raise ValueError('Invalid triangle indices')
        spans=[max(p[i] for p in self.vertices)-min(p[i] for p in self.vertices) for i in range(3)]
        if max(spans)>1 or max(spans)<.005:
            raise ValueError('Select one object between 5 mm and 1 m for live prediction')
        return self
