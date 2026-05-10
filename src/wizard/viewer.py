"""Embeddable 3D geometry viewer built on pyvistaqt + VTK.

The widget renders one VTK actor per body so material picking can dispatch
on actor identity. Face picking dispatches on cell identity within an actor,
using a per-cell `face_id` array baked in at tessellation time.

Per-body color comes from a deterministic palette keyed on the STEP part
name, so all instances of the same part share a color and the user can
visually tell parts apart. When a material is assigned to a body group,
the color is replaced with a material-category shade.
"""
from __future__ import annotations

import hashlib
import os

os.environ.setdefault("QT_API", "pyqt6")

import pyvista as pv
from pyvistaqt import QtInteractor
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QSlider,
    QSplitter, QVBoxLayout, QWidget
)


_HIGHLIGHT_COLOR = "#ffb347"
_EDGE_COLOR = "#3a4154"
_TESS_TOL_LINEAR = 0.1
_TESS_TOL_ANGULAR = 0.2

# Distinct colors that read well against the dark background; ordered to
# avoid neighbouring entries that look too similar.
_PART_PALETTE = [
    "#4f9bc7", "#e2a32d", "#7bbf6a", "#c66e6e",
    "#9b6ab5", "#e07b3c", "#3fb8af", "#c19761",
    "#5c8aff", "#dd8888", "#7a9c80", "#bfb04a",
]

# When a material is assigned, switch the body to a category-derived shade.
_MATERIAL_PALETTE = {
    "Steel":     "#7f8693",
    "Iron":      "#5a585a",
    "Aluminum":  "#b9c4d3",
    "Titanium":  "#a3a8b0",
    "Copper":    "#b87333",
    "Magnesium": "#cfd2d6",
    "Nickel":    "#a4a4a4",
    "Polymer":   "#d4b896",
    "Composite": "#3a4a5a",
    "Concrete":  "#a8a292",
    "Semi":      "#7a7a85",
    "Metal":     "#909295",
}


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
        layout.setSpacing(2)

        layout.addLayout(self._build_toolbar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._visibility_list = QListWidget()
        self._visibility_list.setMinimumWidth(150)
        self._visibility_list.setMaximumWidth(260)
        self._visibility_list.itemChanged.connect(self._on_visibility_changed)
        splitter.addWidget(self._visibility_list)

        self._plotter = QtInteractor(self)
        splitter.addWidget(self._plotter.interactor)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([180, 600])
        layout.addWidget(splitter)
        self._plotter.set_background("#1f2330")
        self._plotter.add_axes()

        self._meshes: dict[int, pv.PolyData] = {}
        self._base_colors: dict[int, str] = {}
        self._body_to_group: dict[int, str] = {}
        self._actor_for_body: dict[int, "vtkProp"] = {}
        self._explode_offsets: dict[int, tuple[float, float, float]] = {}
        self._highlighted: int | None = None
        self._face_picking_enabled = False
        self._hovered: int | None = None
        self._setup_hover_label()

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setContentsMargins(4, 2, 4, 2)
        for label, slot in [
            ("Iso", self._view_iso),
            ("Top", self._view_top),
            ("Front", self._view_front),
            ("Right", self._view_right),
            ("Fit", self._view_fit),
        ]:
            btn = QPushButton(label)
            btn.setFixedWidth(50)
            btn.clicked.connect(slot)
            bar.addWidget(btn)
        bar.addSpacing(12)
        bar.addWidget(QLabel("Explode:"))
        self._explode_slider = QSlider(Qt.Orientation.Horizontal)
        self._explode_slider.setRange(0, 100)
        self._explode_slider.setValue(0)
        self._explode_slider.setMaximumWidth(160)
        self._explode_slider.valueChanged.connect(self._on_explode_changed)
        bar.addWidget(self._explode_slider)
        bar.addStretch()
        return bar

    def _view_iso(self):
        self._plotter.view_isometric()

    def _view_top(self):
        self._plotter.view_xy()

    def _view_front(self):
        self._plotter.view_xz()

    def _view_right(self):
        self._plotter.view_yz()

    def _view_fit(self):
        self._plotter.reset_camera()

    def closeEvent(self, event):
        try:
            self._plotter.close()
        finally:
            super().closeEvent(event)

    def clear(self) -> None:
        self._plotter.clear()
        self._meshes.clear()
        self._base_colors.clear()
        self._body_to_group.clear()
        self._actor_for_body.clear()
        self._explode_offsets.clear()
        self._highlighted = None
        self._hovered = None
        self._visibility_list.blockSignals(True)
        self._visibility_list.clear()
        self._visibility_list.blockSignals(False)
        # vtkTextActor was attached to the renderer separately; re-add after clear()
        try:
            self._plotter.renderer.AddActor2D(self._hover_text)
            self._hover_text.SetInput("")
        except Exception:
            pass

    def set_geometry(self, named_solids) -> None:
        """Replace the displayed geometry with the given list of NamedSolid."""
        self.clear()
        centroids: dict[int, tuple[float, float, float]] = {}
        for ns in named_solids:
            mesh = _solid_to_mesh(ns)
            if mesh is None or mesh.n_cells == 0:
                continue
            self._meshes[ns.body.id] = mesh
            self._body_to_group[ns.body.id] = ns.body.name
            centroids[ns.body.id] = ns.body.centroid
            color = _color_for_part(ns.body.name)
            self._base_colors[ns.body.id] = color
            self._render_body(ns.body.id, color)
        self._compute_explode_offsets(centroids)
        if self._explode_slider.value() > 0:
            self._explode_slider.blockSignals(True)
            self._explode_slider.setValue(0)
            self._explode_slider.blockSignals(False)
        self._populate_visibility_list()
        self._plotter.reset_camera()
        self._enable_picking()

    def _populate_visibility_list(self) -> None:
        self._visibility_list.blockSignals(True)
        self._visibility_list.clear()
        seen: dict[str, int] = {}
        for body_id, name in self._body_to_group.items():
            seen[name] = seen.get(name, 0) + 1
        for name, count in seen.items():
            item = QListWidgetItem(f"{name}  ×{count}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._visibility_list.addItem(item)
        self._visibility_list.blockSignals(False)

    def _on_visibility_changed(self, item: QListWidgetItem) -> None:
        target_name = item.data(Qt.ItemDataRole.UserRole)
        visible = item.checkState() == Qt.CheckState.Checked
        for body_id, group_name in self._body_to_group.items():
            if group_name != target_name:
                continue
            actor = self._actor_for_body.get(body_id)
            if actor is None:
                continue
            try:
                actor.SetVisibility(1 if visible else 0)
            except Exception:
                pass
        self._plotter.render()

    def _compute_explode_offsets(self, centroids: dict[int, tuple[float, float, float]]) -> None:
        self._explode_offsets.clear()
        if not centroids:
            return
        cx = sum(c[0] for c in centroids.values()) / len(centroids)
        cy = sum(c[1] for c in centroids.values()) / len(centroids)
        cz = sum(c[2] for c in centroids.values()) / len(centroids)
        for body_id, c in centroids.items():
            self._explode_offsets[body_id] = (c[0] - cx, c[1] - cy, c[2] - cz)

    def _on_explode_changed(self, value: int) -> None:
        factor = value / 50.0  # 0 at 0, 1 at 50, 2 at 100
        for body_id, actor in self._actor_for_body.items():
            ox, oy, oz = self._explode_offsets.get(body_id, (0.0, 0.0, 0.0))
            try:
                actor.SetPosition(ox * factor, oy * factor, oz * factor)
            except Exception:
                pass
        self._plotter.render()

    def highlight_body(self, body_id: int | None) -> None:
        """Color the given body to indicate selection; pass None to clear."""
        if self._highlighted is not None and self._highlighted in self._meshes:
            self._render_body(self._highlighted, self._base_colors[self._highlighted])
        if body_id is not None and body_id in self._meshes:
            self._render_body(body_id, _HIGHLIGHT_COLOR)
        self._highlighted = body_id
        self._plotter.render()

    def set_body_material_category(self, body_ids, material_category: str) -> None:
        """Recolor the given bodies to reflect their assigned material category."""
        color = _MATERIAL_PALETTE.get(material_category)
        if color is None:
            return
        for body_id in body_ids:
            if body_id not in self._meshes:
                continue
            self._base_colors[body_id] = color
            if body_id != self._highlighted:
                self._render_body(body_id, color)
        self._plotter.render()

    def reset_body_colors(self) -> None:
        """Restore each body to its part-derived color (e.g. when materials cleared)."""
        for body_id, group_name in self._body_to_group.items():
            color = _color_for_part(group_name)
            self._base_colors[body_id] = color
            if body_id != self._highlighted:
                self._render_body(body_id, color)
        self._plotter.render()

    def set_face_picking(self, enabled: bool) -> None:
        self._face_picking_enabled = enabled
        self._enable_picking()

    def _render_body(self, body_id: int, color: str) -> None:
        actor = self._plotter.add_mesh(
            self._meshes[body_id],
            color=color,
            show_edges=True,
            edge_color=_EDGE_COLOR,
            line_width=0.5,
            name=f"body_{body_id}",
            pickable=True,
        )
        self._actor_for_body[body_id] = actor

    def _setup_hover_label(self) -> None:
        import vtk
        text_actor = vtk.vtkTextActor()
        text_actor.SetInput("")
        prop = text_actor.GetTextProperty()
        prop.SetFontSize(14)
        prop.SetColor(1, 1, 1)
        prop.SetBackgroundColor(0.05, 0.07, 0.12)
        prop.SetBackgroundOpacity(0.7)
        prop.SetFrame(False)
        text_actor.SetPosition(15, 15)
        self._plotter.renderer.AddActor2D(text_actor)
        self._hover_text = text_actor

        self._picker = vtk.vtkPropPicker()
        try:
            self._plotter.iren.add_observer("MouseMoveEvent", self._on_mouse_move)
        except Exception:
            pass

    def _on_mouse_move(self, *_):
        try:
            iren = self._plotter.iren
            x, y = iren.get_event_position() if hasattr(iren, "get_event_position") else iren.GetEventPosition()
            self._picker.Pick(x, y, 0, self._plotter.renderer)
            actor = self._picker.GetActor()
            new_id = None
            if actor is not None:
                for bid, a in self._actor_for_body.items():
                    if a is actor:
                        new_id = bid
                        break
            if new_id == self._hovered:
                return
            self._hovered = new_id
            if new_id is None:
                self._hover_text.SetInput("")
            else:
                name = self._body_to_group.get(new_id, f"Body {new_id}")
                self._hover_text.SetInput(name)
            self._plotter.render()
        except Exception:
            pass

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


def _color_for_part(name: str) -> str:
    digest = hashlib.md5(name.encode("utf-8")).digest()
    return _PART_PALETTE[digest[0] % len(_PART_PALETTE)]


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
