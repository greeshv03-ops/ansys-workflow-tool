import pytest
from pathlib import Path
from src.generator.journal import JournalGenerator
from src.generator.summary import SummaryGenerator
from src.models import (
    SimulationConfig, SimulationType, ElementType,
    GeometryFeatures, MeshSettings, SolverSettings, BoundaryCondition
)

@pytest.fixture
def config():
    return SimulationConfig(
        geometry_path=r"C:\models\bracket.step",
        features=GeometryFeatures(
            bbox=(100.,50.,20.), volume=80000, surface_area=14000,
            body_count=1, thin_walls=False, holes=[], symmetry_planes=[], sharp_edges=False),
        sim_type=SimulationType.STATIC_STRUCTURAL,
        material_id=1, material_name="Structural Steel",
        boundary_conditions=[
            BoundaryCondition(bc_type="Fixed", target="Face A"),
            BoundaryCondition(bc_type="Force", target="Face B", magnitude=500., direction="Y"),
        ],
        mesh=MeshSettings(global_size_mm=0.5, element_type=ElementType.SOLID),
        solver=SolverSettings(outputs=["total_deformation", "von_mises_stress"]),
    )

def test_journal_file_created(config, tmp_path):
    wbjn, _ = JournalGenerator.write(config, str(tmp_path))
    assert Path(wbjn).exists() and wbjn.endswith(".wbjn")

def test_journal_contains_geometry_path(config, tmp_path):
    wbjn, _ = JournalGenerator.write(config, str(tmp_path))
    assert "bracket.step" in Path(wbjn).read_text()

def test_journal_references_static_structural(config, tmp_path):
    wbjn, _ = JournalGenerator.write(config, str(tmp_path))
    assert "Static Structural" in Path(wbjn).read_text()

def test_summary_file_created(config, tmp_path):
    html = SummaryGenerator.write(config, str(tmp_path))
    assert Path(html).exists() and html.endswith(".html")

def test_summary_contains_material(config, tmp_path):
    html = SummaryGenerator.write(config, str(tmp_path))
    assert "Structural Steel" in Path(html).read_text()

def test_summary_contains_bc_entries(config, tmp_path):
    content = Path(SummaryGenerator.write(config, str(tmp_path))).read_text()
    assert "Fixed" in content and "Force" in content and "Face A" in content
