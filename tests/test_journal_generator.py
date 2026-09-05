import pytest
from pathlib import Path
from src.generator.journal import JournalGenerator
from src.generator.summary import SummaryGenerator
from src.models import (
    SimulationConfig, SimulationType, ElementType,
    GeometryFeatures, MeshSettings, SolverSettings, BoundaryCondition,
    BodyMaterial,
)

@pytest.fixture
def config():
    return SimulationConfig(
        geometry_path=r"C:\models\bracket.step",
        features=GeometryFeatures(
            bbox=(100.,50.,20.), volume=80000, surface_area=14000,
            body_count=1, thin_walls=False, holes=[], symmetry_planes=[], sharp_edges=False),
        sim_type=SimulationType.STATIC_STRUCTURAL,
        body_materials=[BodyMaterial(
            body_name="bracket", body_ids=[0],
            material_id=1, material_name="Structural Steel")],
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

@pytest.fixture
def transient_config(config):
    from dataclasses import replace
    return replace(
        config,
        sim_type=SimulationType.TRANSIENT_STRUCTURAL,
        solver=SolverSettings(end_time=2.0, initial_step=0.01, min_step=0.001,
                              max_step=0.1, outputs=["total_deformation"]),
    )

@pytest.fixture
def thermal_config(config):
    from dataclasses import replace
    return replace(config, sim_type=SimulationType.THERMAL_STRUCTURAL)

def test_journal_transient_uses_correct_template(transient_config, tmp_path):
    wbjn, _ = JournalGenerator.write(transient_config, str(tmp_path))
    assert "Transient Structural" in Path(wbjn).read_text()

def test_journal_thermal_uses_coupled_template(thermal_config, tmp_path):
    wbjn, _ = JournalGenerator.write(thermal_config, str(tmp_path))
    assert "Steady-State Thermal" in Path(wbjn).read_text()

def test_summary_transient_renders_time_settings(transient_config, tmp_path):
    html = Path(SummaryGenerator.write(transient_config, str(tmp_path))).read_text()
    assert "End time" in html and "2.0" in html

def test_journal_unknown_sim_type_raises():
    from unittest.mock import MagicMock
    fake_config = MagicMock()
    fake_config.sim_type = "not_a_real_sim_type"
    with pytest.raises(ValueError, match="No template registered"):
        JournalGenerator.write(fake_config, "/tmp")


def test_journal_creates_engineering_data_material(config, tmp_path):
    wbjn, _ = JournalGenerator.write(config, str(tmp_path))
    text = Path(wbjn).read_text()
    assert "Engineering Data" in text
    assert 'CreateMaterial(Name="Structural Steel")' in text


def test_journal_material_includes_density(config, tmp_path):
    wbjn, _ = JournalGenerator.write(config, str(tmp_path))
    text = Path(wbjn).read_text()
    # Structural Steel density is 7850 kg/m^3
    assert "7850" in text
    assert "[kg m^-3]" in text or "kg/m^3" in text


def test_journal_material_includes_elasticity(config, tmp_path):
    wbjn, _ = JournalGenerator.write(config, str(tmp_path))
    text = Path(wbjn).read_text()
    # Structural Steel: E = 200 GPa, nu = 0.30. Workbench wants Young's
    # Modulus in Pa, so 200 GPa => 2e11 Pa (200000000000) and a Poisson's
    # Ratio of 0.3 should appear verbatim.
    assert "Young's Modulus" in text
    assert "200000000000" in text  # 200 GPa in Pa
    assert "Poisson's Ratio" in text
    assert "0.3" in text


def test_journal_deduplicates_repeated_materials(tmp_path):
    # Two body groups assigned to the same material — Engineering Data
    # should only contain one CreateMaterial call.
    from dataclasses import replace
    base = SimulationConfig(
        geometry_path=r"C:\models\bracket.step",
        features=GeometryFeatures(
            bbox=(100., 50., 20.), volume=80000, surface_area=14000,
            body_count=2, thin_walls=False, holes=[], symmetry_planes=[], sharp_edges=False),
        sim_type=SimulationType.STATIC_STRUCTURAL,
        body_materials=[
            BodyMaterial(body_name="bracket-A", body_ids=[0], material_id=1, material_name="Structural Steel"),
            BodyMaterial(body_name="bracket-B", body_ids=[1], material_id=1, material_name="Structural Steel"),
        ],
        boundary_conditions=[],
        mesh=MeshSettings(global_size_mm=0.5, element_type=ElementType.SOLID),
        solver=SolverSettings(outputs=["total_deformation"]),
    )
    wbjn, _ = JournalGenerator.write(base, str(tmp_path))
    text = Path(wbjn).read_text()
    assert text.count('CreateMaterial(Name="Structural Steel")') == 1


def test_journal_no_materials_still_renders(config, tmp_path):
    from dataclasses import replace
    no_mat = replace(config, body_materials=[])
    wbjn, _ = JournalGenerator.write(no_mat, str(tmp_path))
    text = Path(wbjn).read_text()
    # Geometry import still happens; no CreateMaterial calls.
    assert "bracket.step" in text
    assert "CreateMaterial" not in text


def test_journal_thermal_includes_thermal_properties(thermal_config, tmp_path):
    wbjn, _ = JournalGenerator.write(thermal_config, str(tmp_path))
    text = Path(wbjn).read_text()
    # Thermal-structural needs thermal expansion + conductivity + specific
    # heat so the Steady-State Thermal system has what it needs.
    assert "Coefficient of Thermal Expansion" in text
    assert "Thermal Conductivity" in text
    assert "Specific Heat" in text


def test_journal_single_system_when_no_load_cases(config, tmp_path):
    wbjn, _ = JournalGenerator.write(config, str(tmp_path))
    text = Path(wbjn).read_text()
    assert text.count("CreateSystem(") == 1
    assert "ComponentsToShare" not in text


def test_journal_one_system_per_load_case(config, tmp_path):
    from dataclasses import replace
    from src.models import LoadCaseBlock
    cases = [
        LoadCaseBlock(name="static 1g", boundary_conditions=[
            BoundaryCondition(bc_type="Fixed Support", target="Cyl hole #1"),
            BoundaryCondition(bc_type="Acceleration", target="All Bodies", magnitude=9806.65, direction="(0, 0, -1)", unit="mm/s^2")]),
        LoadCaseBlock(name="shock 5g", boundary_conditions=[
            BoundaryCondition(bc_type="Fixed Support", target="Cyl hole #1"),
            BoundaryCondition(bc_type="Force", target="+X face", magnitude=500.0, direction="(0, 0, -1)")]),
    ]
    multi = replace(config, load_cases=cases)
    wbjn, _ = JournalGenerator.write(multi, str(tmp_path))
    text = Path(wbjn).read_text()
    assert text.count("CreateSystem(") == 2
    assert 'system1.DisplayText = "static 1g"' in text
    assert 'system2.DisplayText = "shock 5g"' in text
    assert text.count("ComponentsToShare") == 1
    assert 'GetComponent(Name="Model")' in text
    assert "Force on +X face: 500 N along (0, 0, -1)" in text
    assert text.count('CreateMaterial(Name="Structural Steel")') == 1
    lines = text.splitlines()
    assert '# system1 "static 1g"' in lines
    assert '# system2 "shock 5g"' in lines
    assert "\n# system2" in text
    assert "#   Fixed Support on Cyl hole #1" in lines
    assert "#   Force on +X face: 500 N along (0, 0, -1)" in lines
    open_mechanical_lines = [ln for ln in lines if ln.startswith("# Open Mechanical")]
    assert len(open_mechanical_lines) == 1


def test_journal_escapes_special_characters_in_load_case_name(config, tmp_path):
    import json
    from dataclasses import replace
    from src.models import LoadCaseBlock, BoundaryCondition as BC
    special_name = 'weird "quote"\nand a backslash \\ end'
    cases = [LoadCaseBlock(name=special_name, boundary_conditions=[
        BC(bc_type="Fixed Support", target="Cyl hole #1"),
    ])]
    special = replace(config, load_cases=cases)
    wbjn, _ = JournalGenerator.write(special, str(tmp_path))
    text = Path(wbjn).read_text()
    compile(text, "simulation_setup.wbjn", "exec")
    assert f"system1.DisplayText = {json.dumps(special_name)}" in text


def test_journal_multi_load_case_names_with_special_characters_compile(config, tmp_path):
    from dataclasses import replace
    from src.models import LoadCaseBlock, BoundaryCondition as BC
    cases = [
        LoadCaseBlock(name='first "case"', boundary_conditions=[
            BC(bc_type="Fixed Support", target="Cyl hole #1"),
        ]),
        LoadCaseBlock(name='second\ncase\\with\\backslashes', rationale='line one\nline two', boundary_conditions=[
            BC(bc_type="Force", target='face\nwith\nnewlines', magnitude=500.0, direction="Y"),
        ]),
    ]
    multi = replace(config, load_cases=cases)
    wbjn, _ = JournalGenerator.write(multi, str(tmp_path))
    text = Path(wbjn).read_text()
    compile(text, "simulation_setup.wbjn", "exec")
    # The rationale and target contained embedded newlines; pycomment must
    # collapse them to one line each so no bare continuation line escapes
    # the leading "#" and breaks the script.
    assert "line one line two" in text
    assert "face with newlines" in text


def test_summary_omits_agent_sections_when_empty(config, tmp_path):
    html = Path(SummaryGenerator.write(config, str(tmp_path))).read_text()
    assert "Load Cases" not in html and "Assumptions" not in html and "Open Questions" not in html


def test_summary_renders_load_cases_and_rationale(config, tmp_path):
    from dataclasses import replace
    from src.models import LoadCaseBlock, BodyMaterial
    agent_cfg = replace(
        config,
        body_materials=[BodyMaterial(body_name="bracket", body_ids=[0], material_id=1,
                                     material_name="Structural Steel", rationale="brief says mild steel")],
        boundary_conditions=[BoundaryCondition(bc_type="Fixed Support", target="Cyl hole #1", rationale="bolted to frame")],
        load_cases=[LoadCaseBlock(name="shock 5g", rationale="pothole per ISO 16750-3", boundary_conditions=[
            BoundaryCondition(bc_type="Acceleration", target="All Bodies", magnitude=49033.25, direction="(0, 0, -1)", unit="mm/s^2")])],
        assumptions=["mass hangs from the free end"],
        questions=["bolt preload?"],
    )
    html = Path(SummaryGenerator.write(agent_cfg, str(tmp_path))).read_text()
    assert "Load Cases" in html and "shock 5g" in html and "pothole per ISO 16750-3" in html
    assert "brief says mild steel" in html and "bolted to frame" in html
    assert "Assumptions" in html and "mass hangs from the free end" in html
    assert "Open Questions" in html and "bolt preload?" in html
