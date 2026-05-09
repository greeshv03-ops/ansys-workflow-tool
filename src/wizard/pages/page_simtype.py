from PyQt6.QtWidgets import (
    QWizardPage, QVBoxLayout, QRadioButton,
    QButtonGroup, QLabel, QGroupBox
)

from src.models import SimulationType
from src.defaults.engine import SmartDefaultsEngine

_DESCRIPTIONS = {
    SimulationType.STATIC_STRUCTURAL:    "Stress, strain, and deformation under constant loads.",
    SimulationType.TRANSIENT_STRUCTURAL: "Dynamic response to time-varying loads with inertia effects.",
    SimulationType.THERMAL_STRUCTURAL:   "Heat transfer coupled with thermally-induced structural stress.",
}


class SimTypePage(QWizardPage):

    def __init__(self):
        super().__init__()
        self.setTitle("Step 2 — Simulation Type")
        self.setSubTitle("Your choice drives all smart defaults on the following screens.")
        self._selected: SimulationType | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        group = QGroupBox("Analysis type")
        gl = QVBoxLayout(group)
        self._btns = QButtonGroup(self)
        for i, st in enumerate(SimulationType):
            btn = QRadioButton(st.value.replace("_", " ").title())
            lbl = QLabel(f"   {_DESCRIPTIONS[st]}")
            lbl.setStyleSheet("color:gray;font-size:11px")
            self._btns.addButton(btn, i)
            gl.addWidget(btn)
            gl.addWidget(lbl)
        self._btns.buttonClicked.connect(self._on_select)
        layout.addWidget(group)

    def _on_select(self, btn):
        self._selected = list(SimulationType)[self._btns.id(btn)]
        self.wizard().setProperty("sim_type", self._selected)
        features = self.wizard().property("geometry_features")
        if features:
            self.wizard().setProperty(
                "smart_defaults",
                SmartDefaultsEngine.compute(features, self._selected)
            )
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._selected is not None
