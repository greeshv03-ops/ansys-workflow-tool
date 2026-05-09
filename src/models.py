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
class GeometryFeatures:
    bbox: tuple[float, float, float]
    volume: float
    surface_area: float
    body_count: int
    thin_walls: bool
    holes: list[dict]
    symmetry_planes: list[str]
    sharp_edges: bool


@dataclass
class BoundaryCondition:
    bc_type: str
    target: str
    magnitude: Optional[float] = None
    direction: Optional[str] = None
    unit: str = "N"


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
class SimulationConfig:
    geometry_path: str
    features: GeometryFeatures
    sim_type: SimulationType
    material_id: int
    material_name: str
    boundary_conditions: list[BoundaryCondition]
    mesh: MeshSettings
    solver: SolverSettings
