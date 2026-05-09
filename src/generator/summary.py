from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from src.models import SimulationConfig

_TEMPLATES_DIR = Path(__file__).parent / "templates"


class SummaryGenerator:

    @staticmethod
    def write(config: SimulationConfig, output_dir: str) -> str:
        env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)))
        content = env.get_template("settings_summary.html.j2").render(
            config=config, generated_at=datetime.now().strftime("%Y-%m-%d %H:%M")
        )
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / "settings_summary.html"
        path.write_text(content, encoding="utf-8")
        return str(path)
