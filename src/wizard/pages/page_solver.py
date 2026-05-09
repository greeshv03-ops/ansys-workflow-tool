from pathlib import Path

from PyQt6.QtWidgets import (
    QWizardPage, QVBoxLayout, QFormLayout, QDoubleSpinBox,
    QSpinBox, QCheckBox, QGroupBox, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QFileDialog
)
from PyQt6.QtCore import Qt

from src.models import SolverSettings, SimulationType
from src.generator.journal import JournalGenerator
from src.generator.summary import SummaryGenerator

_OUTPUTS = [
    ("total_deformation",   "Total Deformation"),
    ("von_mises_stress",    "Von Mises Stress"),
    ("safety_factor",       "Safety Factor"),
    ("equivalent_strain",   "Equivalent Elastic Strain"),
    ("velocity",            "Velocity (Transient)"),
    ("acceleration",        "Acceleration (Transient)"),
    ("temperature",         "Temperature (Thermal)"),
    ("heat_flux",           "Heat Flux (Thermal)"),
]


class SolverPage(QWizardPage):

    def __init__(self):
        super().__init__()
        self.setTitle("Step 6 — Solver Settings")
        self.setSubTitle("Configure the solver, pick output results, then generate your files.")
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self._static_grp = QGroupBox("Static Structural")
        sf = QFormLayout(self._static_grp)
        self._substeps = QSpinBox()
        self._substeps.setRange(1, 100)
        self._substeps.setValue(1)
        self._lrg_defl = QCheckBox("Enable Large Deflection")
        sf.addRow("Substeps:", self._substeps)
        sf.addRow(self._lrg_defl)
        layout.addWidget(self._static_grp)

        self._time_grp = QGroupBox("Time Integration")
        tf = QFormLayout(self._time_grp)
        self._end = QDoubleSpinBox()
        self._end.setRange(0.001, 10000)
        self._end.setDecimals(3)
        self._end.setValue(1.0)
        self._init = QDoubleSpinBox()
        self._init.setRange(0.0001, 1000)
        self._init.setDecimals(4)
        self._init.setValue(0.01)
        self._mn = QDoubleSpinBox()
        self._mn.setRange(0.00001, 1000)
        self._mn.setDecimals(5)
        self._mn.setValue(0.001)
        self._mx = QDoubleSpinBox()
        self._mx.setRange(0.0001, 10000)
        self._mx.setDecimals(3)
        self._mx.setValue(0.1)
        tf.addRow("End time (s):", self._end)
        tf.addRow("Initial step (s):", self._init)
        tf.addRow("Min step (s):", self._mn)
        tf.addRow("Max step (s):", self._mx)
        layout.addWidget(self._time_grp)

        layout.addWidget(QLabel("<b>Output requests</b>"))
        self._out_list = QListWidget()
        for key, label in _OUTPUTS:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setCheckState(Qt.CheckState.Unchecked)
            self._out_list.addItem(item)
        layout.addWidget(self._out_list)

        gen_btn = QPushButton("Generate Journal + Summary")
        gen_btn.setStyleSheet(
            "background-color:#003087;color:white;padding:9px;font-size:14px;border-radius:4px"
        )
        gen_btn.clicked.connect(self._generate)
        layout.addWidget(gen_btn)

        self._result = QLabel("")
        self._result.setWordWrap(True)
        layout.addWidget(self._result)

    def initializePage(self):
        defaults = self.wizard().property("smart_defaults") or {}
        sim_type = self.wizard().property("sim_type")
        is_static = sim_type == SimulationType.STATIC_STRUCTURAL
        self._static_grp.setVisible(is_static)
        self._time_grp.setVisible(not is_static)
        if not is_static:
            self._end.setValue(defaults.get("end_time", 1.0))
            self._init.setValue(defaults.get("initial_step", 0.01))
            self._mn.setValue(defaults.get("min_step", 0.001))
            self._mx.setValue(defaults.get("max_step", 0.1))
        default_outputs = set(defaults.get("outputs", []))
        for i in range(self._out_list.count()):
            item = self._out_list.item(i)
            item.setCheckState(
                Qt.CheckState.Checked
                if item.data(Qt.ItemDataRole.UserRole) in default_outputs
                else Qt.CheckState.Unchecked
            )

    def _build_solver(self) -> SolverSettings:
        outputs = [
            self._out_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._out_list.count())
            if self._out_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        return SolverSettings(
            substeps=self._substeps.value(),
            large_deflection=self._lrg_defl.isChecked(),
            end_time=self._end.value(),
            initial_step=self._init.value(),
            min_step=self._mn.value(),
            max_step=self._mx.value(),
            outputs=outputs,
        )

    def _generate(self):
        out_dir = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if not out_dir:
            return
        self.wizard().setProperty("solver_settings", self._build_solver())
        config = self.wizard().get_config()
        try:
            wbjn, _ = JournalGenerator.write(config, out_dir)
            html = SummaryGenerator.write(config, out_dir)
            self._result.setText(
                f"✓ Files written to {out_dir}\n"
                f"  • {Path(wbjn).name}\n"
                f"  • {Path(html).name}\n\n"
                f"In ANSYS Workbench: File → Scripting → Run Script File → select .wbjn"
            )
        except Exception as e:
            self._result.setText(f"Error: {e}")
