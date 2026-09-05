"""Pydantic models shared by the proposal agent, validator, adapter, and web app.

Vectors are objects, not tuples: structured-output JSON schema rejects prefixItems.
"""
from __future__ import annotations

import math
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Vec3(_Strict):
    x: float
    y: float
    z: float

    def as_tuple(self) -> tuple[float, float, float]:
        return (float(self.x), float(self.y), float(self.z))

    def length(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)


# ---------------------------------------------------------------- proposal

class MaterialAssignment(_Strict):
    body_id: int
    material_id: int = Field(description="Must exist in the materials database")
    rationale: str


class Support(_Strict):
    id: str = Field(description="s1, s2, ...")
    target: str = Field(description="face id (f12) or hole-group id (hg1)")
    type: Literal["fixed", "frictionless", "cylindrical", "displacement"]
    rationale: str


class Load(_Strict):
    id: str = Field(description="l1, l2, ...")
    target: str = Field(description="face id (f12) or hole-group id (hg1)")
    type: Literal["force", "pressure", "remote_force", "bearing_load"]
    magnitude: float = Field(description="N for force types, MPa for pressure")
    direction: Vec3 = Field(description="unit vector in the summary axes")
    rationale: str


class LoadCase(_Strict):
    name: str
    acceleration_g: Vec3 = Field(description="body acceleration in g, summary axes")
    load_ids: list[str]
    support_ids: list[str]
    rationale: str


class Refinement(_Strict):
    target: str
    size_mm: float
    reason: str


class MeshProposal(_Strict):
    global_size_mm: float
    element_type: Literal["Solid", "Shell", "Auto"]
    refinement: list[Refinement]


class SetupProposal(_Strict):
    materials: list[MaterialAssignment]
    supports: list[Support]
    loads: list[Load]
    load_cases: list[LoadCase]
    mesh: MeshProposal
    assumptions: list[str]
    questions: list[str]


# ----------------------------------------------------------------- summary

class SummaryBody(_Strict):
    id: int
    name: str
    volume_mm3: float
    centroid_mm: Vec3
    bbox_mm: Vec3


class SummaryFace(_Strict):
    id: str
    body_id: int
    type: Literal["planar", "cylindrical", "other"]
    area_mm2: float
    centroid_mm: Vec3
    normal: Optional[Vec3] = None
    radius_mm: Optional[float] = None
    label: str


class HoleGroup(_Strict):
    id: str
    face_ids: list[str]
    radius_mm: float
    count: int
    plane_normal: Vec3
    pattern: Literal["linear", "rectangular", "circular", "irregular"]


class GeometrySummary(_Strict):
    units: dict[str, str]
    bbox_mm: Vec3
    volume_mm3: float
    estimated_mass_kg: float
    bodies: list[SummaryBody]
    faces: list[SummaryFace]
    hole_groups: list[HoleGroup]
    symmetry_planes: list[str]
    thin_walls: bool

    def face_by_id(self, face_id: str) -> Optional[SummaryFace]:
        for f in self.faces:
            if f.id == face_id:
                return f
        return None

    def body_by_id(self, body_id: int) -> Optional[SummaryBody]:
        for b in self.bodies:
            if b.id == body_id:
                return b
        return None

    def hole_group_by_id(self, group_id: str) -> Optional[HoleGroup]:
        for g in self.hole_groups:
            if g.id == group_id:
                return g
        return None

    def target_face_ids(self, target: str) -> list[str]:
        """Resolve a proposal target to face ids. Unknown targets give []."""
        g = self.hole_group_by_id(target)
        if g is not None:
            return list(g.face_ids)
        return [target] if self.face_by_id(target) is not None else []

    def target_exists(self, target: str) -> bool:
        return bool(self.target_face_ids(target))
