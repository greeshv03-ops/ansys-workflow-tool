import json
import pytest
from pydantic import ValidationError
from src.agent.schema import SetupProposal, GeometrySummary, Vec3


def proposal_dict():
    return {
        "materials": [{"body_id": 0, "material_id": 1, "rationale": "steel bracket"}],
        "supports": [{"id": "s1", "target": "hg1", "type": "fixed", "rationale": "bolted to frame"}],
        "loads": [{"id": "l1", "target": "f2", "type": "force", "magnitude": 500.0,
                   "direction": {"x": 0, "y": 0, "z": -1}, "rationale": "hanging mass"}],
        "load_cases": [{"name": "static 1g", "acceleration_g": {"x": 0, "y": 0, "z": -1},
                        "load_ids": ["l1"], "support_ids": ["s1"], "rationale": "gravity only"}],
        "mesh": {"global_size_mm": 4.0, "element_type": "Solid",
                 "refinement": [{"target": "hg1", "size_mm": 1.0, "reason": "bolt holes"}]},
        "assumptions": ["mass hangs from the free end"],
        "questions": ["what is the bolt preload?"],
    }


def summary_dict():
    return {
        "units": {"length": "mm", "force": "N", "mass": "kg"},
        "bbox_mm": {"x": 100, "y": 50, "z": 20},
        "volume_mm3": 100000.0,
        "estimated_mass_kg": 0.785,
        "bodies": [{"id": 0, "name": "bracket", "volume_mm3": 100000.0,
                    "centroid_mm": {"x": 0, "y": 0, "z": 0}, "bbox_mm": {"x": 100, "y": 50, "z": 20}}],
        "faces": [{"id": "f0", "body_id": 0, "type": "planar", "area_mm2": 5000.0,
                   "centroid_mm": {"x": 0, "y": 0, "z": 10}, "normal": {"x": 0, "y": 0, "z": 1},
                   "radius_mm": None, "label": "+Z face (top, 5000 mm²)"}],
        "hole_groups": [],
        "symmetry_planes": ["XY"],
        "thin_walls": False,
    }


def test_proposal_round_trip():
    p = SetupProposal.model_validate(proposal_dict())
    assert p.loads[0].direction.as_tuple() == (0.0, 0.0, -1.0)
    assert SetupProposal.model_validate_json(p.model_dump_json()) == p


def test_vec3_length():
    assert abs(Vec3(x=3, y=4, z=0).length() - 5.0) < 1e-9


def test_proposal_rejects_unknown_support_type():
    d = proposal_dict()
    d["supports"][0]["type"] = "glued"
    with pytest.raises(ValidationError):
        SetupProposal.model_validate(d)


def test_proposal_rejects_extra_fields():
    d = proposal_dict()
    d["extra"] = 1
    with pytest.raises(ValidationError):
        SetupProposal.model_validate(d)


def test_proposal_schema_has_no_tuple_constructs():
    schema = json.dumps(SetupProposal.model_json_schema())
    assert "prefixItems" not in schema


def test_summary_round_trip():
    s = GeometrySummary.model_validate(summary_dict())
    assert s.faces[0].id == "f0"
    assert s.face_by_id("f0").label.startswith("+Z")
    assert s.face_by_id("nope") is None


def test_summary_target_face_ids_expands_hole_groups():
    d = summary_dict()
    d["faces"].append({"id": "f1", "body_id": 0, "type": "cylindrical", "area_mm2": 300.0,
                       "centroid_mm": {"x": 10, "y": 10, "z": 0}, "normal": None,
                       "radius_mm": 4.0, "label": "Cyl hole #1"})
    d["hole_groups"] = [{"id": "hg1", "face_ids": ["f1"], "radius_mm": 4.0, "count": 1,
                         "plane_normal": {"x": 0, "y": 0, "z": 1}, "pattern": "irregular"}]
    s = GeometrySummary.model_validate(d)
    assert s.target_face_ids("hg1") == ["f1"]
    assert s.target_face_ids("f0") == ["f0"]
    assert s.target_face_ids("zzz") == []
