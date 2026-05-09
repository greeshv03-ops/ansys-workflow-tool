from src.defaults.engine import SmartDefaultsEngine
from src.models import GeometryFeatures, SimulationType

def _features(**kw):
    base = dict(bbox=(100.,50.,20.), volume=80000., surface_area=14000.,
                body_count=1, thin_walls=False, holes=[], symmetry_planes=[], sharp_edges=False)
    base.update(kw)
    return GeometryFeatures(**base)

def test_element_size_clamped_min():
    d = SmartDefaultsEngine.compute(_features(bbox=(10.,8.,5.)), SimulationType.STATIC_STRUCTURAL)
    assert d["element_size_mm"] == 0.5   # 5/50=0.1, clamped to 0.5

def test_element_size_clamped_max():
    d = SmartDefaultsEngine.compute(_features(bbox=(2000.,1500.,1200.)), SimulationType.STATIC_STRUCTURAL)
    assert d["element_size_mm"] == 20.0

def test_thin_wall_gives_shell():
    d = SmartDefaultsEngine.compute(_features(thin_walls=True), SimulationType.STATIC_STRUCTURAL)
    assert d["element_type"] == "Shell"

def test_solid_by_default():
    d = SmartDefaultsEngine.compute(_features(), SimulationType.STATIC_STRUCTURAL)
    assert d["element_type"] == "Solid"

def test_holes_produce_refinement_zones():
    d = SmartDefaultsEngine.compute(
        _features(holes=[{"diameter": 10.0, "position": (0,0,0)}]),
        SimulationType.STATIC_STRUCTURAL
    )
    assert len(d["refinement_zones"]) == 1
    assert abs(d["refinement_zones"][0]["size_mm"] - 1.25) < 0.01

def test_symmetry_suggestion():
    d = SmartDefaultsEngine.compute(_features(symmetry_planes=["XZ"]), SimulationType.STATIC_STRUCTURAL)
    assert d["suggest_symmetry"] is True

def test_static_structural_outputs():
    d = SmartDefaultsEngine.compute(_features(), SimulationType.STATIC_STRUCTURAL)
    assert "total_deformation" in d["outputs"]
    assert "von_mises_stress" in d["outputs"]
    assert d["substeps"] == 1

def test_transient_defaults():
    d = SmartDefaultsEngine.compute(_features(), SimulationType.TRANSIENT_STRUCTURAL)
    assert d["end_time"] == 1.0
    assert d["integration_method"] == "Newmark"

def test_thermal_structural_outputs():
    d = SmartDefaultsEngine.compute(_features(), SimulationType.THERMAL_STRUCTURAL)
    assert "temperature" in d["outputs"]
    assert d["coupling"] == "two_way"
