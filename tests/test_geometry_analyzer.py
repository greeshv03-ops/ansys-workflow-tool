import cadquery as cq
import pytest
from pathlib import Path
from src.geometry.analyzer import GeometryAnalyzer
from src.models import GeometryFeatures

@pytest.fixture(scope="session")
def simple_box_step(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cad")
    path = tmp / "box.step"
    box = cq.Workplane("XY").box(100, 50, 20)
    cq.exporters.export(box, str(path))
    return str(path)

@pytest.fixture(scope="session")
def box_with_hole_step(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cad")
    path = tmp / "box_hole.step"
    shape = cq.Workplane("XY").box(100, 50, 20).faces(">Z").workplane().hole(10)
    cq.exporters.export(shape, str(path))
    return str(path)

def test_analyze_returns_geometry_features(simple_box_step):
    result = GeometryAnalyzer.analyze(simple_box_step)
    assert isinstance(result, GeometryFeatures)

def test_bounding_box_correct(simple_box_step):
    result = GeometryAnalyzer.analyze(simple_box_step)
    assert abs(result.bbox[0] - 100.0) < 1.0
    assert abs(result.bbox[1] - 50.0) < 1.0
    assert abs(result.bbox[2] - 20.0) < 1.0

def test_body_count_single(simple_box_step):
    assert GeometryAnalyzer.analyze(simple_box_step).body_count == 1

def test_no_thin_wall_for_solid_box(simple_box_step):
    assert GeometryAnalyzer.analyze(simple_box_step).thin_walls is False

def test_holes_detected(box_with_hole_step):
    result = GeometryAnalyzer.analyze(box_with_hole_step)
    assert len(result.holes) >= 1
    assert abs(result.holes[0]["diameter"] - 10.0) < 1.0

def test_unsupported_format_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        GeometryAnalyzer.analyze("model.obj")

def test_iges_error_is_value_error_not_import_error(tmp_path):
    fake_iges = tmp_path / "fake.iges"
    fake_iges.write_text("fake content")
    try:
        GeometryAnalyzer.analyze(str(fake_iges))
    except ValueError:
        pass  # expected — either "Unsupported" or "IGES support unavailable"
    except Exception as e:
        pytest.fail(f"Expected ValueError, got {type(e).__name__}: {e}")
