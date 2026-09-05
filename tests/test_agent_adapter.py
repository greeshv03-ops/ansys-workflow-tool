import pytest
from src.agent.adapter import to_config, G_MM_S2
from src.agent.schema import SetupProposal, GeometrySummary
from src.materials.database import MaterialDatabase
from src.models import GeometryFeatures, SimulationType, ElementType, LoadCaseBlock


def vec(x, y, z):
    return {"x": x, "y": y, "z": z}


@pytest.fixture
def summary():
    return GeometrySummary.model_validate({
        "units": {"length": "mm", "force": "N", "mass": "kg"},
        "bbox_mm": vec(100, 50, 20), "volume_mm3": 100000.0, "estimated_mass_kg": 0.785,
        "bodies": [{"id": 0, "name": "bracket", "volume_mm3": 100000.0, "centroid_mm": vec(0, 0, 0), "bbox_mm": vec(100, 50, 20)}],
        "faces": [
            {"id": "f0", "body_id": 0, "type": "planar", "area_mm2": 5000, "centroid_mm": vec(0, 0, 10), "normal": vec(0, 0, 1), "radius_mm": None, "label": "+Z face (top, 5000 mm²)"},
            {"id": "f1", "body_id": 0, "type": "planar", "area_mm2": 1000, "centroid_mm": vec(50, 0, 0), "normal": vec(1, 0, 0), "radius_mm": None, "label": "+X face (right, 1000 mm²)"},
            {"id": "f2", "body_id": 0, "type": "cylindrical", "area_mm2": 250, "centroid_mm": vec(-40, 0, 0), "normal": None, "radius_mm": 4.0, "label": "Cyl hole #1"},
            {"id": "f3", "body_id": 0, "type": "cylindrical", "area_mm2": 250, "centroid_mm": vec(-40, 15, 0), "normal": None, "radius_mm": 4.0, "label": "Cyl hole #2"},
        ],
        "hole_groups": [{"id": "hg1", "face_ids": ["f2", "f3"], "radius_mm": 4.0, "count": 2, "plane_normal": vec(0, 0, 1), "pattern": "linear"}],
        "symmetry_planes": [], "thin_walls": False,
    })


@pytest.fixture
def features():
    return GeometryFeatures(bbox=(100., 50., 20.), volume=100000., surface_area=16500., body_count=1,
                            thin_walls=False, holes=[], symmetry_planes=[], sharp_edges=False)


@pytest.fixture
def proposal():
    return SetupProposal.model_validate({
        "materials": [{"body_id": 0, "material_id": 5, "rationale": "aluminum bracket"}],
        "supports": [{"id": "s1", "target": "hg1", "type": "fixed", "rationale": "bolted"}],
        "loads": [{"id": "l1", "target": "f1", "type": "force", "magnitude": 500.0, "direction": vec(0, 0, -1), "rationale": "mass"},
                  {"id": "l2", "target": "f0", "type": "pressure", "magnitude": 0.2, "direction": vec(0, 0, -1), "rationale": "snow"}],
        "load_cases": [
            {"name": "static 1g", "acceleration_g": vec(0, 0, -1), "load_ids": ["l1"], "support_ids": ["s1"], "rationale": "gravity"},
            {"name": "shock 5g", "acceleration_g": vec(0, 0, -5), "load_ids": ["l1", "l2"], "support_ids": ["s1"], "rationale": "pothole"},
        ],
        "mesh": {"global_size_mm": 4.0, "element_type": "Solid", "refinement": [{"target": "hg1", "size_mm": 1.0, "reason": "bolt holes"}]},
        "assumptions": ["mass at the free end"], "questions": ["bolt preload?"],
    })


def test_config_basics(proposal, summary, features):
    cfg = to_config(proposal, summary, features, r"C:\parts\bracket.step", MaterialDatabase())
    assert cfg.sim_type == SimulationType.STATIC_STRUCTURAL
    assert cfg.geometry_path.endswith("bracket.step")
    assert cfg.body_materials[0].material_name == "Aluminum Alloy 6061-T6"
    assert cfg.body_materials[0].body_ids == [0]
    assert cfg.body_materials[0].rationale == "aluminum bracket"
    assert cfg.assumptions == ["mass at the free end"] and cfg.questions == ["bolt preload?"]


def test_hole_group_support_expands_to_member_faces(proposal, summary, features):
    cfg = to_config(proposal, summary, features, "p.step", MaterialDatabase())
    fixed = [bc for bc in cfg.boundary_conditions if bc.bc_type == "Fixed Support"]
    assert [bc.target for bc in fixed] == ["Cyl hole #1", "Cyl hole #2"]
    assert fixed[0].rationale == "bolted"


def test_loads_map_units_and_direction(proposal, summary, features):
    cfg = to_config(proposal, summary, features, "p.step", MaterialDatabase())
    force = next(bc for bc in cfg.boundary_conditions if bc.bc_type == "Force")
    assert force.target == "+X face (right, 1000 mm²)" and force.magnitude == 500.0
    assert force.unit == "N" and force.direction == "(0, 0, -1)"
    pressure = next(bc for bc in cfg.boundary_conditions if bc.bc_type == "Pressure")
    assert pressure.unit == "MPa" and pressure.magnitude == 0.2


def test_load_cases_carry_acceleration(proposal, summary, features):
    cfg = to_config(proposal, summary, features, "p.step", MaterialDatabase())
    assert [lc.name for lc in cfg.load_cases] == ["static 1g", "shock 5g"]
    assert all(isinstance(lc, LoadCaseBlock) for lc in cfg.load_cases)
    shock = cfg.load_cases[1]
    accel = next(bc for bc in shock.boundary_conditions if bc.bc_type == "Acceleration")
    assert abs(accel.magnitude - 5 * G_MM_S2) < 1e-6 and accel.unit == "mm/s^2"
    assert accel.direction == "(0, 0, -1)" and accel.target == "All Bodies"
    # shock case: 2 hole faces fixed + l1 + l2 + acceleration
    assert len(shock.boundary_conditions) == 5
    assert len(cfg.load_cases[0].boundary_conditions) == 4


def test_mesh_mapping(proposal, summary, features):
    cfg = to_config(proposal, summary, features, "p.step", MaterialDatabase())
    assert cfg.mesh.global_size_mm == 4.0 and cfg.mesh.element_type == ElementType.SOLID
    assert cfg.mesh.refinement_zones[0].size_mm == 1.0
    assert "bolt holes" in cfg.mesh.refinement_zones[0].description
    assert "total_deformation" in cfg.solver.outputs


def test_existing_config_defaults_unchanged():
    from src.models import SimulationConfig, MeshSettings, SolverSettings
    cfg = SimulationConfig(geometry_path="x", features=None, sim_type=SimulationType.STATIC_STRUCTURAL,
                           body_materials=[], boundary_conditions=[],
                           mesh=MeshSettings(1.0, ElementType.SOLID), solver=SolverSettings())
    assert cfg.load_cases == [] and cfg.assumptions == [] and cfg.questions == []
