import cadquery as cq
import numpy as np
import pytest
from src.agent.render import render_image, render_png, SUPPORT_RGB, LOAD_RGB
from src.agent.summary import build_summary
from src.geometry.analyzer import GeometryAnalyzer


@pytest.fixture(scope="session")
def box_hole(tmp_path_factory):
    path = tmp_path_factory.mktemp("cad") / "box_hole.step"
    shape = cq.Workplane("XY").box(100, 50, 20).faces(">Z").workplane().hole(10)
    cq.exporters.export(shape, str(path))
    features, solids = GeometryAnalyzer.analyze_with_solids(str(path))
    return features, solids, build_summary(features, [ns.body for ns in solids])


def _count_color(img, rgb, tol=25):
    diff = np.abs(img[:, :, :3].astype(int) - np.array(rgb)[None, None, :])
    return int((diff.max(axis=2) <= tol).sum())


def test_render_image_shape(box_hole):
    features, solids, summary = box_hole
    img = render_image(solids, summary, [], [])
    assert img.shape[0] == 900 and img.shape[1] == 1200 and img.dtype == np.uint8


def test_render_colors_support_and_load_faces(box_hole):
    features, solids, summary = box_hole
    top = next(f.id for f in summary.faces if f.label.startswith("+Z"))
    right = next(f.id for f in summary.faces if f.label.startswith("+X"))
    plain = render_image(solids, summary, [], [])
    colored = render_image(solids, summary, [top], [right])
    assert _count_color(colored, SUPPORT_RGB) > 500 > _count_color(plain, SUPPORT_RGB)
    assert _count_color(colored, LOAD_RGB) > 200 > _count_color(plain, LOAD_RGB)


def test_render_png_bytes(box_hole):
    features, solids, summary = box_hole
    data = render_png(solids, summary, [], [])
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 1000
