from collections import OrderedDict

from PyQt6.QtWidgets import (
    QWizardPage, QVBoxLayout, QHBoxLayout, QLineEdit,
    QListWidget, QListWidgetItem, QSplitter, QTextEdit, QLabel
)
from PyQt6.QtCore import Qt, QTimer

from src.materials.database import MaterialDatabase
from src.models import BodyMaterial
from src.wizard.viewer import GeometryViewer


_UNASSIGNED = "(none)"


class MaterialPage(QWizardPage):

    def __init__(self):
        super().__init__()
        self.setTitle("Step 3 — Material Assignment")
        self.setSubTitle(
            "Pick a body on the left, then assign it a material. "
            "Click bodies in the 3D view to select them."
        )
        self._db = MaterialDatabase()
        self._assignments: dict[str, dict] = {}  # body_name -> {body_ids, material_id, material_name}
        self._body_groups: list[tuple[str, list[int]]] = []  # ordered (name, ids)
        self._selected_body_name: str | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        body_panel = QSplitter(Qt.Orientation.Vertical)
        body_panel.addWidget(QLabel("<b>Bodies</b>"))
        self._body_list = QListWidget()
        self._body_list.currentItemChanged.connect(self._on_body_selected)
        body_panel.addWidget(self._body_list)
        splitter.addWidget(body_panel)

        material_panel = QSplitter(Qt.Orientation.Vertical)
        material_panel.addWidget(QLabel("<b>Materials</b>"))
        search_row = QHBoxLayout()
        search_widget = QLabel("Search:")
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter materials…")
        self._search.textChanged.connect(
            lambda t: QTimer.singleShot(150, lambda: self._populate_materials(t))
        )
        sw = QHBoxLayout()
        sw.addWidget(search_widget)
        sw.addWidget(self._search)
        from PyQt6.QtWidgets import QWidget
        search_container = QWidget()
        search_container.setLayout(sw)
        material_panel.addWidget(search_container)

        self._material_list = QListWidget()
        self._material_list.currentItemChanged.connect(self._on_material_selected)
        material_panel.addWidget(self._material_list)
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setMaximumHeight(110)
        material_panel.addWidget(self._detail)
        splitter.addWidget(material_panel)

        self._viewer = GeometryViewer()
        splitter.addWidget(self._viewer)
        self._viewer.body_picked.connect(self._on_viewer_body_picked)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 4)
        layout.addWidget(splitter)

        self._populate_materials("structural steel")

    def initializePage(self):
        named_solids = self.wizard().property("geometry_named_solids") or []
        self._viewer.set_geometry(named_solids)

        features = self.wizard().property("geometry_features")
        bodies = features.bodies if features and features.bodies else []
        groups: OrderedDict[str, list[int]] = OrderedDict()
        for b in bodies:
            groups.setdefault(b.name, []).append(b.id)
        if not groups:
            groups["Default body"] = [0]
        self._body_groups = list(groups.items())

        self._body_list.clear()
        for name, ids in self._body_groups:
            count = len(ids)
            label = f"{name}  ×{count}"
            item = QListWidgetItem(f"{label}\n  → {_UNASSIGNED}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._body_list.addItem(item)
        if self._body_list.count() > 0:
            self._body_list.setCurrentRow(0)

    def _populate_materials(self, q: str):
        self._material_list.clear()
        for m in self._db.search(q):
            item = QListWidgetItem(f"{m['name']}  [{m['category']}]")
            item.setData(Qt.ItemDataRole.UserRole, m["id"])
            self._material_list.addItem(item)

    def _on_body_selected(self, current: QListWidgetItem | None, previous):
        if not current:
            self._selected_body_name = None
            self._viewer.highlight_body(None)
            return
        body_name = current.data(Qt.ItemDataRole.UserRole)
        self._selected_body_name = body_name
        ids_for_group = next((ids for name, ids in self._body_groups if name == body_name), [])
        self._viewer.highlight_body(ids_for_group[0] if ids_for_group else None)

    def _on_material_selected(self, current: QListWidgetItem | None, previous):
        if not current:
            return
        m = self._db.get_by_id(current.data(Qt.ItemDataRole.UserRole))
        if not m:
            return
        self._render_material_detail(m)
        if self._selected_body_name is None:
            return
        ids = next((ids for name, ids in self._body_groups if name == self._selected_body_name), [])
        self._assignments[self._selected_body_name] = {
            "body_ids": ids,
            "material_id": m["id"],
            "material_name": m["name"],
        }
        self._refresh_body_row(self._selected_body_name)
        self._save_to_wizard()
        self.completeChanged.emit()

    def _on_viewer_body_picked(self, body_id: int):
        for row, (name, ids) in enumerate(self._body_groups):
            if body_id in ids:
                self._body_list.setCurrentRow(row)
                return

    def _refresh_body_row(self, body_name: str):
        for row in range(self._body_list.count()):
            item = self._body_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) != body_name:
                continue
            ids = next((ids for n, ids in self._body_groups if n == body_name), [])
            assigned = self._assignments.get(body_name, {}).get("material_name", _UNASSIGNED)
            item.setText(f"{body_name}  ×{len(ids)}\n  → {assigned}")
            return

    def _render_material_detail(self, m: dict):
        lines = [
            f"<b>{m['name']}</b>  ·  {m['category']}",
            f"E = {m['E_GPa']} GPa &nbsp; ν = {m['nu']} &nbsp; ρ = {m['rho_kgm3']} kg/m³",
        ]
        if m.get("yield_MPa"):
            lines.append(f"Yield = {m['yield_MPa']} MPa &nbsp; UTS = {m['UTS_MPa']} MPa")
        if m.get("k_WmK"):
            lines.append(f"k = {m['k_WmK']} W/m·K &nbsp; Cp = {m['Cp_JkgK']} J/kg·K")
        self._detail.setHtml("<br>".join(lines))

    def _save_to_wizard(self):
        body_materials = [
            BodyMaterial(
                body_name=name,
                body_ids=data["body_ids"],
                material_id=data["material_id"],
                material_name=data["material_name"],
            )
            for name, data in self._assignments.items()
        ]
        self.wizard().setProperty("body_materials", body_materials)

    def isComplete(self) -> bool:
        if not self._body_groups:
            return False
        return all(name in self._assignments for name, _ in self._body_groups)
