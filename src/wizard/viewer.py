"""Embeddable 3D geometry viewer built on pyvistaqt + VTK.

The widget renders one VTK actor per body so material picking can dispatch
on actor identity. Face picking dispatches on cell identity within an actor,
using a per-cell `face_id` array baked in at tessellation time.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_API", "pyqt6")

import pyvista as pv
from pyvistaqt import QtInteractor
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

_DEFAULT_COLOR = "#a8b2bf"
_HIGHLIGHT_COLOR = "#ffb347"
_TESS_TOL_LINEAR = 0.1   # mm
_TESS_TOL_ANGULAR = 0.2  # rad


class GeometryViewer(QWidget):
    """A QWidget showing CAD geometry with click-to-pick on bodies and faces.

    Signals:
        body_picked(int): body_id of the clicked body.
        face_picked(int, int): (body_id, face_index) of the clicked face.
    """

    body_picked = pyqtSignal(int)
    face_picked = pyqtSignal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._plotter = QtInteractor(self)
        layout.addWidget(self._plotter.interactor)
        self._plotter.set_background("#1f2330")
        self._plotter.add_axes()

        self._actors: dict[int, "pv.PolyData"] = {}  # body_id -> mesh actor key
        self._meshes: dict[int, pv.PolyData] = {}    # body_id -> mesh
        self._highlighted: int | None = None
        self._face_picking_enabled = False

    def closeEvent(self, event):
        try:
            self._plotter.close()
        finally:
            super().closeEvent(event)

    def clear(self) -> None:
        self._plotter.clear()
        self._actors.clear()
        self._meshes.clear()
        self._highlighted = None

    def set_geometry(self, named_solids) -> None:
        """Replace the displayed geometry with the given list of NamedSolid."""
        self.clear()
        for ns in named_solids:
            mesh = _solid_to_mesh(ns)
            if mesh is None or mesh.n_cells == 0:
                continue
            self._meshes[ns.body.id] = mesh
            self._plotter.add_mesh(
                mesh,
                color=_DEFAULT_COLOR,
                show_edges=True,
                edge_color="#3a4154",
                line_width=0.5,
                name=f"body_{ns.body.id}",
                pickable=True,
            )
        self._plotter.reset_camera()
        self._enable_picking()

    def highlight_body(self, body_id: int | None) -> None:
        """Color the given body to indicate selection; pass None to clear."""
        if self._highlighted is not None and self._highlighted in self._meshes:
            self._plotter.add_mesh(
                self._meshes[self._highlighted],
                color=_DEFAULT_COLOR,
                show_edges=True,
                edge_color="#3a4154",
                line_width=0.5,
                name=f"body_{self._highlighted}",
                pickable=True,
            )
        if body_id is not None and body_id in self._meshes:
            self._plotter.add_mesh(
                self._meshes[body_id],
                color=_HIGHLIGHT_COLOR,
                show_edges=True,
                edge_color="#3a4154",
                line_width=0.5,
                name=f"body_{body_id}",
                pickable=True,
            )
        self._highlighted = body_id
        self._plotter.render()

    def set_face_picking(self, enabled: bool) -> None:
        """Toggle whether clicks emit face_picked instead of body_picked."""
        self._face_picking_enabled = enabled
        self._enable_picking()

    def _enable_picking(self) -> None:
        try:
            self._plotter.disable_picking()
        except Exception:
            pass
        if self._face_picking_enabled:
            self._plotter.enable_cell_picking(
                callback=self._on_cell_pick,
                show=False,
                show_message=False,
                style="surface",
                through=False,
            )
        else:
            self._plotter.enable_mesh_picking(
                callback=self._on_mesh_pick,
                show=False,
                show_message=False,
                use_actor=False,
            )

    def _on_mesh_pick(self, mesh) -> None:
        body_id = _body_id_of(mesh)
        if body_id is not None:
            self.body_picked.emit(body_id)

    def _on_cell_pick(self, picked) -> None:
        if picked is None or picked.n_cells == 0:
            return
        body_id = _body_id_of(picked)
        if body_id is None:
            return
        face_id = -1
        if "face_id" in picked.cell_data:
            face_ids = picked.cell_data["face_id"]
            if len(face_ids):
                face_id = int(face_ids[0])
        self.face_picked.emit(body_id, face_id)


def _body_id_of(mesh) -> int | None:
    if mesh is None:
        return None
    fd = mesh.field_data if hasattr(mesh, "field_data") else None
    if fd is not None and "body_id" in fd:
        try:
            return int(fd["body_id"][0])
        except Exception:
            return None
    return None


def _solid_to_mesh(named_solid) -> pv.PolyData | None:
    """Tessellate a NamedSolid to a pyvista PolyData with body_id + per-cell face_id."""
    try:
        import vtk
        from vtk.util.numpy_support import vtk_to_numpy

        face_meshes = []
        for face_idx, face in enumerate(named_solid.shape.Faces()):
            try:
                pd = face.toVtkPolyData(_TESS_TOL_LINEAR, _TESS_TOL_ANGULAR)
            except Exception:
                try:
                    pd = face.toVtkPolyData()
                except Exception:
                    continue
            if pd is None or pd.GetNumberOfCells() == 0:
                continue
            n = pd.GetNumberOfCells()
            arr = vtk.vtkIntArray()
            arr.SetName("face_id")
            arr.SetNumberOfValues(n)
            for k in range(n):
                arr.SetValue(k, face_idx)
            pd.GetCellData().AddArray(arr)
            face_meshes.append(pv.wrap(pd))

        if not face_meshes:
            try:
                full_pd = named_solid.shape.toVtkPolyData(_TESS_TOL_LINEAR, _TESS_TOL_ANGULAR)
            except Exception:
                full_pd = named_solid.shape.toVtkPolyData()
            mesh = pv.wrap(full_pd) if full_pd else None
        else:
            mesh = face_meshes[0].merge(face_meshes[1:]) if len(face_meshes) > 1 else face_meshes[0]

        if mesh is None or mesh.n_cells == 0:
            return None
        mesh.field_data["body_id"] = [named_solid.body.id]
        return mesh
    except Exception:
        return None
