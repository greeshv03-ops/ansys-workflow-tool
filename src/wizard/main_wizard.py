from PyQt6.QtWidgets import QWizard
from src.wizard.pages.page_upload import UploadPage
from src.wizard.pages.page_simtype import SimTypePage
from src.wizard.pages.page_material import MaterialPage
from src.wizard.pages.page_bcs import BCsPage
from src.wizard.pages.page_mesh import MeshPage
from src.wizard.pages.page_solver import SolverPage
from src.models import SimulationConfig


class ANSYSWizard(QWizard):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ANSYS Simulation Setup Wizard")
        self.setMinimumSize(820, 620)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        for page in [UploadPage(), SimTypePage(), MaterialPage(),
                     BCsPage(), MeshPage(), SolverPage()]:
            self.addPage(page)

    def get_config(self) -> SimulationConfig:
        return SimulationConfig(
            geometry_path=self.property("geometry_path") or "",
            features=self.property("geometry_features"),
            sim_type=self.property("sim_type"),
            material_id=self.property("material_id") or 0,
            material_name=self.property("material_name") or "",
            boundary_conditions=self.property("boundary_conditions") or [],
            mesh=self.property("mesh_settings"),
            solver=self.property("solver_settings"),
        )
