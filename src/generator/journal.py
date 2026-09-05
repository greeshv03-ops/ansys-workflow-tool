from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from src.models import SimulationConfig, SimulationType
from src.materials.database import MaterialDatabase

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    trim_blocks=True,
    lstrip_blocks=True,
)
_TEMPLATE_MAP = {
    SimulationType.STATIC_STRUCTURAL:    "static_structural.wbjn.j2",
    SimulationType.TRANSIENT_STRUCTURAL: "transient_structural.wbjn.j2",
    SimulationType.THERMAL_STRUCTURAL:   "thermal_structural.wbjn.j2",
}


def _num(value) -> str:
    return f"{value:g}"


_ENV.filters["num"] = _num


def _fmt(value, unit: str = "") -> str:
    """Format a numeric property value with an optional Workbench unit suffix."""
    text = f"{value:g}"
    return f"{text} [{unit}]" if unit else text


def _resolve_materials(config: SimulationConfig, db: MaterialDatabase) -> list[dict]:
    """Look up Engineering Data properties for each unique assigned material.

    Bodies sharing the same ``material_id`` collapse to a single Engineering
    Data entry, preserving first-seen order so the journal is deterministic.
    """
    materials: list[dict] = []
    seen: set[int] = set()
    for bm in config.body_materials:
        if bm.material_id in seen:
            continue
        seen.add(bm.material_id)
        row = db.get_by_id(bm.material_id)
        if row is None:
            continue
        materials.append({
            "name":                 row["name"],
            "density":              _fmt(row["rho_kgm3"], "kg m^-3"),
            "youngs_modulus":       f"{row['E_GPa'] * 1e9:.0f} [Pa]",
            "poissons_ratio":       _fmt(row["nu"]),
            "thermal_expansion":    _fmt(row["alpha_1e6K"] * 1e-6, "C^-1") if row["alpha_1e6K"] is not None else None,
            "thermal_conductivity": _fmt(row["k_WmK"], "W m^-1 C^-1") if row["k_WmK"] is not None else None,
            "specific_heat":        _fmt(row["Cp_JkgK"], "J kg^-1 C^-1") if row["Cp_JkgK"] is not None else None,
        })
    return materials


class JournalGenerator:

    @staticmethod
    def write(
        config: SimulationConfig,
        output_dir: str | Path,
        db: MaterialDatabase | None = None,
    ) -> tuple[str, str]:
        template_name = _TEMPLATE_MAP.get(config.sim_type)
        if template_name is None:
            raise ValueError(f"No template registered for sim_type={config.sim_type!r}")
        materials = _resolve_materials(config, db or MaterialDatabase())
        content = _ENV.get_template(template_name).render(
            config=config,
            materials=materials,
            load_cases=getattr(config, "load_cases", []),
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / "simulation_setup.wbjn"
        path.write_text(content, encoding="utf-8")
        return str(path), str(out)
