from PyQt6.QtWidgets import (
    QWizardPage, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QComboBox, QListWidget, QListWidgetItem
)

from src.models import MeshSettings, ElementType, RefinementZone


class MeshPage(QWizardPage):

    def __init__(self):
        super().__init__()
        self.setTitle("Step 5 — Mesh Settings")
        self.setSubTitle("Smart defaults are pre-filled. Adjust if needed.")
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Global element size (mm):"))
        self._size = QDoubleSpinBox()
        self._size.setRange(0.1, 500.0)
        self._size.setDecimals(2)
        self._size.setSingleStep(0.5)
        row.addWidget(self._size)
        self._size_hint = QLabel("")
        self._size_hint.setStyleSheet("color:gray;font-size:11px")
        row.addWidget(self._size_hint)
        row.addStretch()
        layout.addLayout(row)

        layout.addWidget(QLabel("Element type:"))
        self._elem = QComboBox()
        for et in ElementType:
            self._elem.addItem(et.value, et)
        layout.addWidget(self._elem)

        self._warn = QLabel("⚠ Thin wall detected — Shell elements are recommended.")
        self._warn.setStyleSheet("color:orange")
        self._warn.hide()
        layout.addWidget(self._warn)

        layout.addWidget(QLabel("Refinement zones (from geometry analysis):"))
        self._zones = QListWidget()
        layout.addWidget(self._zones)

    def initializePage(self):
        defaults = self.wizard().property("smart_defaults") or {}
        features = self.wizard().property("geometry_features")

        self._size.setValue(defaults.get("element_size_mm", 5.0))
        if features:
            self._size_hint.setText(f"(L/50 of {min(features.bbox):.1f} mm)")
            if features.thin_walls:
                self._warn.show()

        elem_str = defaults.get("element_type", "Solid")
        for i in range(self._elem.count()):
            if self._elem.itemText(i) == elem_str:
                self._elem.setCurrentIndex(i)
                break

        self._zones.clear()
        for rz in defaults.get("refinement_zones", []):
            self._zones.addItem(QListWidgetItem(
                f"{rz['zone_type'].title()}: {rz['size_mm']} mm — {rz['description']}"
            ))

    def validatePage(self) -> bool:
        defaults = self.wizard().property("smart_defaults") or {}
        zones = [
            RefinementZone(zone_type=rz["zone_type"], size_mm=rz["size_mm"], description=rz["description"])
            for rz in defaults.get("refinement_zones", [])
        ]
        self.wizard().setProperty("mesh_settings", MeshSettings(
            global_size_mm=self._size.value(),
            element_type=self._elem.currentData(),
            refinement_zones=zones,
        ))
        return True
