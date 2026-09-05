"""Off-screen pyvista render with support faces blue and load faces orange. No Qt."""
from __future__ import annotations

import os
import tempfile
import threading

import numpy as np
import pyvista as pv

from src.agent.schema import GeometrySummary

# pyvista/VTK's off-screen renderer is not safe to drive from multiple threads
# at once within a process (create_session now runs the render off the event
# loop via a threadpool, so concurrent uploads can otherwise overlap here).
# Serialise the whole build-plotter/screenshot/close sequence per process.
_RENDER_LOCK = threading.Lock()

SUPPORT_RGB = (63, 111, 158)
LOAD_RGB = (217, 138, 43)
BASE_RGB = (208, 212, 216)
WINDOW = (1200, 900)
_TESS_TOL_LINEAR = 0.1
_TESS_TOL_ANGULAR = 0.2
_MATCH_TOL_MM = 0.5
_AREA_TOL = 0.02

if os.name != "nt" and not os.environ.get("DISPLAY"):
    try:
        pv.start_xvfb()
    except Exception:
        pass  # pyvista >= 0.45 has no start_xvfb(); on Linux without DISPLAY the first
        # render will abort the process, so set DISPLAY (Xvfb) or use the Docker image


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % rgb


def _face_meshes(named_solid):
    """Yield (centroid, area, PolyData) per face of one solid."""
    for face in named_solid.shape.Faces():
        try:
            pd = face.toVtkPolyData(_TESS_TOL_LINEAR, _TESS_TOL_ANGULAR)
        except Exception:
            try:
                pd = face.toVtkPolyData()
            except Exception:
                continue
        if pd is None or pd.GetNumberOfCells() == 0:
            continue
        c = face.Center()
        yield (c.x, c.y, c.z), face.Area(), pv.wrap(pd)


def _match(summary: GeometrySummary, centroid, area) -> str | None:
    for f in summary.faces:
        c = f.centroid_mm
        if (abs(c.x - centroid[0]) <= _MATCH_TOL_MM and abs(c.y - centroid[1]) <= _MATCH_TOL_MM
                and abs(c.z - centroid[2]) <= _MATCH_TOL_MM
                and abs(f.area_mm2 - area) <= _AREA_TOL * max(f.area_mm2, 1.0)):
            return f.id
    return None


def _expand(summary: GeometrySummary, targets: list[str]) -> set[str]:
    out: set[str] = set()
    for t in targets:
        out.update(summary.target_face_ids(t))
    return out


def _build_plotter(named_solids, summary: GeometrySummary, support_targets: list[str],
                   load_targets: list[str]) -> pv.Plotter:
    """Build and configure a plotter with all meshes, colors, and camera setup."""
    support_faces = _expand(summary, support_targets)
    load_faces = _expand(summary, load_targets)
    plotter = pv.Plotter(off_screen=True, window_size=list(WINDOW))
    plotter.set_background("white")
    for ns in named_solids:
        for centroid, area, mesh in _face_meshes(ns):
            fid = _match(summary, centroid, area)
            color = BASE_RGB
            if fid in support_faces:
                color = SUPPORT_RGB
            elif fid in load_faces:
                color = LOAD_RGB
            plotter.add_mesh(mesh, color=_hex(color), smooth_shading=False, show_edges=False)
    plotter.view_isometric()
    plotter.camera.zoom(1.2)
    return plotter


def render_image(named_solids, summary: GeometrySummary, support_targets: list[str],
                 load_targets: list[str]) -> np.ndarray:
    with _RENDER_LOCK:
        plotter = _build_plotter(named_solids, summary, support_targets, load_targets)
        try:
            img = plotter.screenshot(return_img=True)
            return np.asarray(img)[:, :, :3].astype(np.uint8)
        finally:
            plotter.close()


def render_png(named_solids, summary: GeometrySummary, support_targets: list[str],
               load_targets: list[str]) -> bytes:
    with _RENDER_LOCK:
        plotter = _build_plotter(named_solids, summary, support_targets, load_targets)
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            plotter.screenshot(path)
            with open(path, "rb") as fh:
                return fh.read()
        finally:
            plotter.close()
            try:
                os.remove(path)
            except OSError:
                pass
