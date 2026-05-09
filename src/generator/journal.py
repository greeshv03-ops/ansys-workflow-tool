from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from src.models import SimulationConfig, SimulationType

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_ENV = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)))
_TEMPLATE_MAP = {
    SimulationType.STATIC_STRUCTURAL:    "static_structural.wbjn.j2",
    SimulationType.TRANSIENT_STRUCTURAL: "transient_structural.wbjn.j2",
    SimulationType.THERMAL_STRUCTURAL:   "thermal_structural.wbjn.j2",
}


class JournalGenerator:

    @staticmethod
    def write(config: SimulationConfig, output_dir: str | Path) -> tuple[str, str]:
        template_name = _TEMPLATE_MAP.get(config.sim_type)
        if template_name is None:
            raise ValueError(f"No template registered for sim_type={config.sim_type!r}")
        content = _ENV.get_template(template_name).render(
            config=config, generated_at=datetime.now().strftime("%Y-%m-%d %H:%M")
        )
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / "simulation_setup.wbjn"
        path.write_text(content, encoding="utf-8")
        return str(path), str(out)
