import pytest
from src.agent.schema import SetupProposal, GeometrySummary
from src.agent.validator import validate
from src.materials.database import MaterialDatabase


def vec(x, y, z):
    return {"x": x, "y": y, "z": z}


@pytest.fixture
def summary():
    # One 100 x 50 x 20 box body, six planar faces + two hole faces in one group.
    faces = [
        {"id": "f0", "body_id": 0, "type": "planar", "area_mm2": 5000, "centroid_mm": vec(0, 0, 10), "normal": vec(0, 0, 1), "radius_mm": None, "label": "+Z face (top)"},
        {"id": "f1", "body_id": 0, "type": "planar", "area_mm2": 5000, "centroid_mm": vec(0, 0, -10), "normal": vec(0, 0, -1), "radius_mm": None, "label": "-Z face (bottom)"},
        {"id": "f2", "body_id": 0, "type": "planar", "area_mm2": 2000, "centroid_mm": vec(0, 25, 0), "normal": vec(0, 1, 0), "radius_mm": None, "label": "+Y face (front)"},
        {"id": "f3", "body_id": 0, "type": "planar", "area_mm2": 2000, "centroid_mm": vec(0, -25, 0), "normal": vec(0, -1, 0), "radius_mm": None, "label": "-Y face (back)"},
        {"id": "f4", "body_id": 0, "type": "planar", "area_mm2": 1000, "centroid_mm": vec(50, 0, 0), "normal": vec(1, 0, 0), "radius_mm": None, "label": "+X face (right)"},
        {"id": "f5", "body_id": 0, "type": "planar", "area_mm2": 1000, "centroid_mm": vec(-50, 0, 0), "normal": vec(-1, 0, 0), "radius_mm": None, "label": "-X face (left)"},
        {"id": "f6", "body_id": 0, "type": "cylindrical", "area_mm2": 250, "centroid_mm": vec(-40, 0, 0), "normal": None, "radius_mm": 4.0, "label": "Cyl hole #1"},
        {"id": "f7", "body_id": 0, "type": "cylindrical", "area_mm2": 250, "centroid_mm": vec(-40, 15, 0), "normal": None, "radius_mm": 4.0, "label": "Cyl hole #2"},
    ]
    return GeometrySummary.model_validate({
        "units": {"length": "mm", "force": "N", "mass": "kg"},
        "bbox_mm": vec(100, 50, 20), "volume_mm3": 100000.0, "estimated_mass_kg": 0.785,
        "bodies": [{"id": 0, "name": "bracket", "volume_mm3": 100000.0, "centroid_mm": vec(0, 0, 0), "bbox_mm": vec(100, 50, 20)}],
        "faces": faces,
        "hole_groups": [{"id": "hg1", "face_ids": ["f6", "f7"], "radius_mm": 4.0, "count": 2, "plane_normal": vec(0, 0, 1), "pattern": "linear"}],
        "symmetry_planes": [], "thin_walls": False,
    })


def good_proposal():
    return {
        "materials": [{"body_id": 0, "material_id": 1, "rationale": "steel"}],
        "supports": [{"id": "s1", "target": "hg1", "type": "fixed", "rationale": "bolted"}],
        "loads": [{"id": "l1", "target": "f4", "type": "force", "magnitude": 500.0, "direction": vec(0, 0, -1), "rationale": "load"}],
        "load_cases": [{"name": "1g", "acceleration_g": vec(0, 0, -1), "load_ids": ["l1"], "support_ids": ["s1"], "rationale": "gravity"}],
        "mesh": {"global_size_mm": 4.0, "element_type": "Solid", "refinement": [{"target": "hg1", "size_mm": 1.0, "reason": "holes"}]},
        "assumptions": [], "questions": [],
    }


@pytest.fixture
def db():
    return MaterialDatabase()


def run(d, summary, db):
    return validate(SetupProposal.model_validate(d), summary, db)


def test_good_proposal_is_valid(summary, db):
    assert run(good_proposal(), summary, db) == []


def test_rule1_body_without_material(summary, db):
    d = good_proposal(); d["materials"] = []
    msgs = run(d, summary, db)
    assert any(m.startswith("rule1") and "body 0" in m for m in msgs)


def test_rule1_unknown_material_id(summary, db):
    d = good_proposal(); d["materials"][0]["material_id"] = 9999
    assert any(m.startswith("rule1") and "9999" in m for m in run(d, summary, db))


def test_rule1_duplicate_material_for_body(summary, db):
    d = good_proposal(); d["materials"].append({"body_id": 0, "material_id": 5, "rationale": "x"})
    assert any(m.startswith("rule1") and "exactly one" in m for m in run(d, summary, db))


def test_rule2_no_supports(summary, db):
    d = good_proposal(); d["supports"] = []; d["load_cases"][0]["support_ids"] = []
    assert any(m.startswith("rule2") and "at least one support" in m for m in run(d, summary, db))


def test_rule2_unknown_target(summary, db):
    d = good_proposal(); d["loads"][0]["target"] = "f99"
    assert any(m.startswith("rule2") and "f99" in m for m in run(d, summary, db))


def test_rule3_support_and_load_share_target(summary, db):
    d = good_proposal(); d["loads"][0]["target"] = "hg1"
    assert any(m.startswith("rule3") and "hg1" in m for m in run(d, summary, db))


def test_rule4_unknown_load_id(summary, db):
    d = good_proposal(); d["load_cases"][0]["load_ids"] = ["l9"]
    assert any(m.startswith("rule4") and "l9" in m for m in run(d, summary, db))


def test_rule4_empty_load_case(summary, db):
    d = good_proposal(); d["load_cases"][0]["load_ids"] = []; d["load_cases"][0]["acceleration_g"] = vec(0, 0, 0)
    assert any(m.startswith("rule4") and "no loads" in m for m in run(d, summary, db))


def test_rule4_unknown_support_id(summary, db):
    d = good_proposal(); d["load_cases"][0]["support_ids"] = ["s9"]
    assert any(m.startswith("rule4") and "s9" in m for m in run(d, summary, db))


def test_rule5_acceleration_too_high(summary, db):
    d = good_proposal(); d["load_cases"][0]["acceleration_g"] = vec(0, 0, -31)
    assert any(m.startswith("rule5") and "30 g" in m for m in run(d, summary, db))


def test_rule5_force_too_high(summary, db):
    d = good_proposal(); d["loads"][0]["magnitude"] = 2e6
    assert any(m.startswith("rule5") and "1e6" in m for m in run(d, summary, db))


def test_rule5_pressure_above_yield(summary, db):
    d = good_proposal(); d["loads"][0]["type"] = "pressure"; d["loads"][0]["magnitude"] = 400.0  # steel yield 250 MPa
    assert any(m.startswith("rule5") and "yield" in m for m in run(d, summary, db))


def test_rule6_global_size_out_of_band(summary, db):
    d = good_proposal(); d["mesh"]["global_size_mm"] = 0.5  # band is 1..10 for bbox max 100
    assert any(m.startswith("rule6") and "global" in m for m in run(d, summary, db))


def test_rule6_refinement_not_smaller(summary, db):
    d = good_proposal(); d["mesh"]["refinement"][0]["size_mm"] = 4.0
    assert any(m.startswith("rule6") and "refinement" in m for m in run(d, summary, db))


def test_rule7_fixed_covers_every_face(summary, db):
    d = good_proposal()
    d["supports"] = [{"id": f"s{i}", "target": f"f{i}", "type": "fixed", "rationale": "x"} for i in range(8)]
    d["loads"] = []; d["load_cases"][0]["load_ids"] = []; d["load_cases"][0]["support_ids"] = ["s0"]
    d["mesh"]["refinement"] = []
    assert any(m.startswith("rule7") and "every face" in m for m in run(d, summary, db))


def test_rule7_fixed_area_over_half(summary, db):
    d = good_proposal()
    d["supports"] = [{"id": "s1", "target": "f0", "type": "fixed", "rationale": "x"},
                     {"id": "s2", "target": "f1", "type": "fixed", "rationale": "x"}]  # 10000 of 16500 mm²
    assert any(m.startswith("rule7") and "50 percent" in m for m in run(d, summary, db))


def test_rule8_direction_not_unit(summary, db):
    d = good_proposal(); d["loads"][0]["direction"] = vec(0, 0, -2)
    assert any(m.startswith("rule8") and "l1" in m for m in run(d, summary, db))


def test_rule5_zero_yield_uses_uts(summary, db):
    # Cast Iron Gray has yield_MPa = 0 and UTS_MPa = 179
    # Material id 4 from seed data (0-indexed 3 in SEED_DATA list)
    cast_iron_row = db.search("Cast Iron Gray")
    assert len(cast_iron_row) > 0, "Cast Iron Gray not found in database"
    cast_iron_id = cast_iron_row[0]["id"]

    d = good_proposal()
    d["materials"][0]["material_id"] = cast_iron_id
    d["loads"][0]["type"] = "pressure"
    d["loads"][0]["magnitude"] = 179.0  # Equal to UTS
    msgs = run(d, summary, db)
    assert any(m.startswith("rule5") and "ultimate strength" in m for m in msgs), \
        f"Expected ultimate strength message for pressure at UTS, got: {msgs}"


def test_rule5_zero_yield_uts_below_threshold(summary, db):
    # Pressure below UTS should pass
    cast_iron_row = db.search("Cast Iron Gray")
    assert len(cast_iron_row) > 0
    cast_iron_id = cast_iron_row[0]["id"]

    d = good_proposal()
    d["materials"][0]["material_id"] = cast_iron_id
    d["loads"][0]["type"] = "pressure"
    d["loads"][0]["magnitude"] = 170.0  # Below UTS of 179
    msgs = run(d, summary, db)
    assert not any(m.startswith("rule5") and "pressure" in m for m in msgs), \
        f"Expected no pressure rule5 message for magnitude below UTS, got: {msgs}"
