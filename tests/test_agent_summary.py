import cadquery as cq
import pytest
from src.agent.summary import build_summary, FACE_CAP
from src.geometry.analyzer import GeometryAnalyzer
from src.models import Body, FaceLabel, GeometryFeatures


@pytest.fixture(scope="session")
def plate_4holes_step(tmp_path_factory):
    path = tmp_path_factory.mktemp("cad") / "plate4.step"
    plate = (cq.Workplane("XY").box(100, 60, 10)
             .faces(">Z").workplane().rect(70, 40, forConstruction=True).vertices().hole(8))
    cq.exporters.export(plate, str(path))
    return str(path)


@pytest.fixture(scope="session")
def plate_2holes_step(tmp_path_factory):
    path = tmp_path_factory.mktemp("cad") / "plate2.step"
    plate = (cq.Workplane("XY").box(100, 30, 10)
             .faces(">Z").workplane().pushPoints([(-30, 0), (30, 0)]).hole(6))
    cq.exporters.export(plate, str(path))
    return str(path)


def test_analyzer_records_cylinder_axis(plate_2holes_step):
    features = GeometryAnalyzer.analyze(plate_2holes_step)
    cyl = [f for f in features.faces if f.face_type == "cylindrical"]
    assert cyl and all(f.axis is not None and f.axis_point is not None for f in cyl)
    assert abs(abs(cyl[0].axis[2]) - 1.0) < 1e-3


def test_analyzer_records_face_index(plate_2holes_step):
    features = GeometryAnalyzer.analyze(plate_2holes_step)
    assert sorted(f.index for f in features.faces) == list(range(len(features.faces)))


def test_summary_units_and_ids(plate_2holes_step):
    features, solids = GeometryAnalyzer.analyze_with_solids(plate_2holes_step)
    s = build_summary(features, [ns.body for ns in solids])
    assert s.units == {"length": "mm", "force": "N", "mass": "kg"}
    assert [f.id for f in s.faces] == [f"f{i}" for i in range(len(s.faces))]
    assert s.faces[0].label == features.faces[0].name
    assert abs(s.estimated_mass_kg - features.volume * 1e-9 * 7850) < 1e-6


def test_hole_group_linear(plate_2holes_step):
    features, solids = GeometryAnalyzer.analyze_with_solids(plate_2holes_step)
    s = build_summary(features, [ns.body for ns in solids])
    assert len(s.hole_groups) == 1
    g = s.hole_groups[0]
    assert g.id == "hg1" and g.count == 2 and g.pattern == "linear"
    assert abs(g.radius_mm - 3.0) < 0.05
    assert abs(abs(g.plane_normal.z) - 1.0) < 1e-3


def test_hole_group_rectangular(plate_4holes_step):
    features, solids = GeometryAnalyzer.analyze_with_solids(plate_4holes_step)
    s = build_summary(features, [ns.body for ns in solids])
    assert len(s.hole_groups) == 1
    assert s.hole_groups[0].count == 4
    assert s.hole_groups[0].pattern == "rectangular"


def _synthetic_features(n_faces: int, tiny: bool = False, n_tiny: int = 0) -> GeometryFeatures:
    faces = [FaceLabel(name=f"face {i}", face_type="planar", area=100.0,
                       centroid=(0, 0, 0), normal=(0, 0, 1), index=i) for i in range(n_faces)]
    tiny_count = n_tiny + (1 if tiny else 0)
    for k in range(tiny_count):
        name = "speck" if tiny_count == 1 else f"speck{k}"
        faces.append(FaceLabel(name=name, face_type="planar", area=0.01,
                               centroid=(1, 1, 1), normal=(0, 0, 1), index=n_faces + k))
    total = sum(f.area for f in faces)
    return GeometryFeatures(bbox=(100, 50, 20), volume=1000.0, surface_area=total, body_count=1,
                            thin_walls=False, holes=[], symmetry_planes=[], sharp_edges=False, faces=faces,
                            bodies=[Body(id=0, name="b", volume=1000.0, centroid=(0, 0, 0), bbox=(100, 50, 20))])


def test_prunes_tiny_faces():
    f = _synthetic_features(5, tiny=True)
    s = build_summary(f, f.bodies)
    assert all(face.label != "speck" for face in s.faces)
    assert len(s.faces) == 5


def test_face_cap_rejects_large_parts():
    f = _synthetic_features(FACE_CAP + 1)
    with pytest.raises(ValueError, match="above the cap"):
        build_summary(f, f.bodies)


def test_single_body_faces_get_body_zero():
    f = _synthetic_features(3)
    s = build_summary(f, f.bodies)
    assert {face.body_id for face in s.faces} == {0}


def test_face_cap_checked_after_pruning():
    """Raw face count exceeds FACE_CAP, but enough faces are prunable that the
    kept (post-prune) count is under the cap, so build_summary must succeed."""
    n_significant = 50
    n_tiny = 200
    f = _synthetic_features(n_significant, n_tiny=n_tiny)
    assert len(f.faces) == n_significant + n_tiny > FACE_CAP
    s = build_summary(f, f.bodies)
    assert len(s.faces) == n_significant
