from src.models import (
    SimulationType, ElementType, GeometryFeatures,
    BoundaryCondition, MeshSettings, SolverSettings
)

def test_sim_type_values():
    assert SimulationType.STATIC_STRUCTURAL.value == "static_structural"
    assert SimulationType.TRANSIENT_STRUCTURAL.value == "transient_structural"
    assert SimulationType.THERMAL_STRUCTURAL.value == "thermal_structural"

def test_geometry_features_fields():
    f = GeometryFeatures(
        bbox=(100.0, 50.0, 20.0), volume=80000.0, surface_area=14000.0,
        body_count=1, thin_walls=False, holes=[], symmetry_planes=[], sharp_edges=False,
    )
    assert f.bbox == (100.0, 50.0, 20.0)
    assert f.body_count == 1

def test_mesh_settings_default_zones():
    m = MeshSettings(global_size_mm=3.2, element_type=ElementType.SOLID)
    assert m.refinement_zones == []

def test_solver_settings_defaults():
    s = SolverSettings()
    assert s.substeps == 1
    assert s.large_deflection is False
    assert s.outputs == []
