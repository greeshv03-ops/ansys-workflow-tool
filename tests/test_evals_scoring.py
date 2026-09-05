import pytest
from evals.run_evals import score_part, resolve_reference_targets, _accel_match
from src.agent.schema import SetupProposal, GeometrySummary
from src.materials.database import MaterialDatabase


def vec(x, y, z):
    return {"x": x, "y": y, "z": z}


@pytest.fixture
def summary():
    return GeometrySummary.model_validate({
        "units": {"length": "mm", "force": "N", "mass": "kg"}, "bbox_mm": vec(100, 50, 20),
        "volume_mm3": 1.0, "estimated_mass_kg": 1.0,
        "bodies": [{"id": 0, "name": "b", "volume_mm3": 1.0, "centroid_mm": vec(0, 0, 0), "bbox_mm": vec(100, 50, 20)}],
        "faces": [
            {"id": "f0", "body_id": 0, "type": "planar", "area_mm2": 5000, "centroid_mm": vec(0, 0, 10), "normal": vec(0, 0, 1), "radius_mm": None, "label": "+Z face (top)"},
            {"id": "f1", "body_id": 0, "type": "planar", "area_mm2": 5000, "centroid_mm": vec(0, 0, -10), "normal": vec(0, 0, -1), "radius_mm": None, "label": "-Z face (bottom)"},
            {"id": "f2", "body_id": 0, "type": "cylindrical", "area_mm2": 200, "centroid_mm": vec(1, 1, 0), "normal": None, "radius_mm": 4.0, "label": "Cyl hole #1"},
            {"id": "f3", "body_id": 0, "type": "cylindrical", "area_mm2": 200, "centroid_mm": vec(9, 1, 0), "normal": None, "radius_mm": 4.0, "label": "Cyl hole #2"}],
        "hole_groups": [{"id": "hg1", "face_ids": ["f2", "f3"], "radius_mm": 4.0, "count": 2, "plane_normal": vec(0, 0, 1), "pattern": "linear"}],
        "symmetry_planes": [], "thin_walls": False})


@pytest.fixture
def reference():
    return {
        "material_family": "Steel",
        "supports": [{"type": "fixed", "targets": ["hole_group:2"], "alternatives": ["label:-Z face"]}],
        "loads": [{"type": "force", "targets": ["label:+Z face"], "alternatives": []}],
        "load_cases": [{"name": "static", "acceleration_g": [0, 0, -1]}, {"name": "shock", "acceleration_g": [0, 0, -20]}],
    }


def proposal(support_target="hg1", load_target="f0", accels=((0, 0, -1), (0, 0, -20)), material_id=1):
    return SetupProposal.model_validate({
        "materials": [{"body_id": 0, "material_id": material_id, "rationale": "x"}],
        "supports": [{"id": "s1", "target": support_target, "type": "fixed", "rationale": "x"}],
        "loads": [{"id": "l1", "target": load_target, "type": "force", "magnitude": 100.0, "direction": vec(0, 0, -1), "rationale": "x"}],
        "load_cases": [{"name": f"c{i}", "acceleration_g": vec(*a), "load_ids": ["l1"], "support_ids": ["s1"], "rationale": "x"} for i, a in enumerate(accels)],
        "mesh": {"global_size_mm": 4.0, "element_type": "Solid", "refinement": []},
        "assumptions": [], "questions": []})


def test_resolve_targets(summary, reference):
    r = resolve_reference_targets(reference, summary)
    assert r["supports"][0]["targets"] == ["hg1"] and r["supports"][0]["alternatives"] == ["f1"]
    assert r["loads"][0]["targets"] == ["f0"]


def test_perfect_score(summary, reference):
    s = score_part(proposal(), resolve_reference_targets(reference, summary), MaterialDatabase(), first_pass_valid=True)
    assert s == {"load_cases": 1.0, "supports": 1.0, "loads": 1.0, "material": 1.0, "first_pass_valid": 1.0, "overall": 1.0}


def test_alternative_support_counts(summary, reference):
    s = score_part(proposal(support_target="f1"), resolve_reference_targets(reference, summary), MaterialDatabase(), True)
    assert s["supports"] == 1.0


def test_wrong_material_family_and_missing_case(summary, reference):
    s = score_part(proposal(accels=((0, 0, -1),), material_id=5), resolve_reference_targets(reference, summary), MaterialDatabase(), False)
    assert s["material"] == 0.0 and s["load_cases"] == 0.5 and s["first_pass_valid"] == 0.0
    assert abs(s["overall"] - (0.5 + 1 + 1 + 0 + 0) / 5) < 1e-9


def test_accel_match_rules():
    assert _accel_match((0, 0, -1), (0, 0, -1.2))          # within 25 percent magnitude
    assert not _accel_match((0, 0, -1), (0, 0, -1.3))
    assert not _accel_match((0, 0, -1), (0, 0.5, -0.866))  # 30 degrees off
    assert _accel_match((0, 0, 0), (0, 0, 0))              # both zero counts as a match


def test_two_materials_one_matches(summary, reference):
    prop = SetupProposal.model_validate({
        "materials": [
            {"body_id": 0, "material_id": 1, "rationale": "x"},
            {"body_id": 1, "material_id": 5, "rationale": "x"}
        ],
        "supports": [{"id": "s1", "target": "hg1", "type": "fixed", "rationale": "x"}],
        "loads": [{"id": "l1", "target": "f0", "type": "force", "magnitude": 100.0, "direction": vec(0, 0, -1), "rationale": "x"}],
        "load_cases": [{"name": "c0", "acceleration_g": vec(0, 0, -1), "load_ids": ["l1"], "support_ids": ["s1"], "rationale": "x"}, {"name": "c1", "acceleration_g": vec(0, 0, -20), "load_ids": ["l1"], "support_ids": ["s1"], "rationale": "x"}],
        "mesh": {"global_size_mm": 4.0, "element_type": "Solid", "refinement": []},
        "assumptions": [], "questions": []})
    s = score_part(prop, resolve_reference_targets(reference, summary), MaterialDatabase(), first_pass_valid=True)
    assert s["material"] == 0.5
