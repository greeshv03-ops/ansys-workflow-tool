from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SimulationType(Enum):
    STATIC_STRUCTURAL = "static_structural"
    TRANSIENT_STRUCTURAL = "transient_structural"
    THERMAL_STRUCTURAL = "thermal_structural"


class ElementType(Enum):
    SOLID = "Solid"
    SHELL = "Shell"
    AUTO = "Auto"


@dataclass
class FaceLabel:
    name: str
    face_type: str
    area: float
    centroid: tuple[float, float, float]
    normal: Optional[tuple[float, float, float]] = None
    radius: Optional[float] = None
    axis: Optional[tuple[float, float, float]] = None        # cylinder axis direction
    axis_point: Optional[tuple[float, float, float]] = None  # a point on that axis
    index: int = -1                                          # position in features.faces


@dataclass
class Body:
    id: int
    name: str
    volume: float
    centroid: tuple[float, float, float]
    bbox: tuple[float, float, float]


@dataclass
class GeometryFeatures:
    bbox: tuple[float, float, float]
    volume: float
    surface_area: float
    body_count: int
    thin_walls: bool
    holes: list[dict]
    symmetry_planes: list[str]
    sharp_edges: bool
    faces: list[FaceLabel] = field(default_factory=list)
    bodies: list[Body] = field(default_factory=list)


@dataclass
class BoundaryCondition:
    bc_type: str
    target: str
    magnitude: Optional[float] = None
    direction: Optional[str] = None
    unit: str = "N"
    rationale: str = ""


@dataclass
class RefinementZone:
    zone_type: str
    size_mm: float
    description: str


@dataclass
class MeshSettings:
    global_size_mm: float
    element_type: ElementType
    refinement_zones: list[RefinementZone] = field(default_factory=list)


@dataclass
class SolverSettings:
    substeps: int = 1
    large_deflection: bool = False
    end_time: float = 1.0
    initial_step: float = 0.01
    min_step: float = 0.001
    max_step: float = 0.1
    integration_method: str = "Newmark"
    outputs: list[str] = field(default_factory=list)


@dataclass
class BodyMaterial:
    """Material assignment for one group of bodies sharing the same part name."""
    body_name: str
    body_ids: list[int]
    material_id: int
    material_name: str
    rationale: str = ""


@dataclass
class LoadCaseBlock:
    """One Static Structural system's worth of boundary conditions, agent path only."""
    name: str
    boundary_conditions: list[BoundaryCondition] = field(default_factory=list)
    rationale: str = ""


@dataclass
class SimulationConfig:
    geometry_path: str
    features: GeometryFeatures
    sim_type: SimulationType
    body_materials: list[BodyMaterial]
    boundary_conditions: list[BoundaryCondition]
    mesh: MeshSettings
    solver: SolverSettings
    load_cases: list[LoadCaseBlock] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)

    @property
    def primary_material_name(self) -> str:
        """First-assigned material; used as the summary header for single-body parts."""
        return self.body_materials[0].material_name if self.body_materials else ""

    @property
    def primary_material_id(self) -> int:
        return self.body_materials[0].material_id if self.body_materials else 0
