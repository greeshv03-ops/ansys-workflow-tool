from PyQt6.QtWidgets import (
    QWizardPage, QVBoxLayout, QLineEdit,
    QListWidget, QListWidgetItem, QSplitter, QTextEdit
)
from PyQt6.QtCore import Qt, QTimer

from src.materials.database import MaterialDatabase


class MaterialPage(QWizardPage):

    def __init__(self):
        super().__init__()
        self.setTitle("Step 3 — Material Assignment")
        self.setSubTitle("Search and select a material. Properties are shown on the right.")
        self._db = MaterialDatabase()
        self._selected_id: int | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search materials…")
        self._search.textChanged.connect(lambda t: QTimer.singleShot(200, lambda: self._populate(t)))
        layout.addWidget(self._search)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_select)
        splitter.addWidget(self._list)
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        splitter.addWidget(self._detail)
        splitter.setSizes([300, 300])
        layout.addWidget(splitter)
        self._populate("structural steel")

    def _populate(self, q: str):
        self._list.clear()
        for m in self._db.search(q):
            item = QListWidgetItem(f"{m['name']}  [{m['category']}]")
            item.setData(Qt.ItemDataRole.UserRole, m["id"])
            self._list.addItem(item)

    def _on_select(self, item: QListWidgetItem | None):
        if not item:
            return
        m = self._db.get_by_id(item.data(Qt.ItemDataRole.UserRole))
        if not m:
            return
        self._selected_id = m["id"]
        self.wizard().setProperty("material_id", m["id"])
        self.wizard().setProperty("material_name", m["name"])
        lines = [f"<b>{m['name']}</b><br>Category: {m['category']}<br>",
                 f"E = {m['E_GPa']} GPa &nbsp; ν = {m['nu']} &nbsp; ρ = {m['rho_kgm3']} kg/m³"]
        if m.get("yield_MPa"):
            lines.append(f"Yield = {m['yield_MPa']} MPa &nbsp; UTS = {m['UTS_MPa']} MPa")
        if m.get("k_WmK"):
            lines.append(f"k = {m['k_WmK']} W/m·K &nbsp; Cp = {m['Cp_JkgK']} J/kg·K")
        self._detail.setHtml("<br>".join(lines))
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._selected_id is not None
