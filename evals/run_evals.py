# evals/run_evals.py
"""Score the proposal agent against hand-written references. Run: python -m evals.run_evals [part ...] [--repeats N]"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import date
from pathlib import Path

from src.agent.pipeline import run_pipeline
from src.agent.proposer import playbook_hash, propose
from src.agent.schema import GeometrySummary, SetupProposal
from src.agent.summary import build_summary
from src.geometry.analyzer import GeometryAnalyzer
from src.materials.database import MaterialDatabase

PARTS_DIR = Path(__file__).parent / "parts"
RESULTS_DIR = Path(__file__).parent / "results"
COLUMNS = ["load_cases", "supports", "loads", "material", "first_pass_valid", "overall"]
FAMILIES = {"Steel": "Steel", "Iron": "Steel", "Aluminum": "Aluminum", "Polymer": "Polymer",
            "Composite": "Polymer", "Titanium": "Titanium", "Copper": "Copper", "Nickel": "Steel",
            "Magnesium": "Aluminum", "Metal": "Steel", "Semi": "Polymer", "Concrete": "Polymer"}


def _resolve(token: str, summary: GeometrySummary) -> str | None:
    kind, _, value = token.partition(":")
    if kind == "id":
        return value if summary.target_exists(value) else None
    if kind == "label":
        for f in summary.faces:
            if f.label.startswith(value):
                return f.id
        return None
    if kind == "hole_group":
        for g in summary.hole_groups:
            if g.count == int(value):
                return g.id
        return None
    return None


def resolve_reference_targets(reference: dict, summary: GeometrySummary) -> dict:
    out = json.loads(json.dumps(reference))
    for key in ("supports", "loads"):
        for item in out.get(key, []):
            item["targets"] = [t for t in (_resolve(x, summary) for x in item.get("targets", [])) if t]
            item["alternatives"] = [t for t in (_resolve(x, summary) for x in item.get("alternatives", [])) if t]
    return out


def _accel_match(ref, got) -> bool:
    rm = math.sqrt(sum(c * c for c in ref))
    gm = math.sqrt(sum(c * c for c in got))
    if rm == 0.0 and gm == 0.0:
        return True
    if rm == 0.0 or gm == 0.0:
        return False
    if abs(gm - rm) > 0.25 * rm:
        return False
    cos = sum(a * b for a, b in zip(ref, got)) / (rm * gm)
    return cos >= math.cos(math.radians(15))


def _fraction_matched(ref_items: list[dict], got_targets: list[str]) -> float:
    if not ref_items:
        return 1.0
    hits = 0
    for item in ref_items:
        accepted = set(item["targets"]) | set(item["alternatives"])
        if accepted & set(got_targets):
            hits += 1
    return hits / len(ref_items)


def score_part(proposal: SetupProposal, reference: dict, db: MaterialDatabase, first_pass_valid: bool) -> dict:
    got_accels = [lc.acceleration_g.as_tuple() for lc in proposal.load_cases]
    ref_cases = reference.get("load_cases", [])
    case_hits = sum(1 for rc in ref_cases if any(_accel_match(tuple(rc["acceleration_g"]), g) for g in got_accels))
    load_cases = case_hits / len(ref_cases) if ref_cases else 1.0

    supports = _fraction_matched(reference.get("supports", []), [s.target for s in proposal.supports])
    loads = _fraction_matched(reference.get("loads", []), [l.target for l in proposal.loads])

    material = 0.0
    if proposal.materials:
        matches = 0
        for mat in proposal.materials:
            row = db.get_by_id(mat.material_id)
            if row and FAMILIES.get(row["category"], row["category"]) == reference.get("material_family"):
                matches += 1
        material = matches / len(proposal.materials)

    fpv = 1.0 if first_pass_valid else 0.0
    overall = (load_cases + supports + loads + material + fpv) / 5
    return {"load_cases": load_cases, "supports": supports, "loads": loads, "material": material,
            "first_pass_valid": fpv, "overall": overall}


def _load_part(name: str):
    d = PARTS_DIR / name
    features, solids = GeometryAnalyzer.analyze_with_solids(str(d / "part.step"))
    summary = build_summary(features, [ns.body for ns in solids])
    brief = (d / "brief.md").read_text(encoding="utf-8").strip()
    reference = resolve_reference_targets(json.loads((d / "reference.json").read_text(encoding="utf-8")), summary)
    return summary, brief, reference


def run(part_names: list[str] | None = None, repeats: int = 3, propose_fn=propose) -> str:
    db = MaterialDatabase()
    names = part_names or sorted(p.name for p in PARTS_DIR.iterdir() if (p / "part.step").exists())
    rows = []
    for name in names:
        summary, brief, reference = _load_part(name)
        runs = []
        for i in range(repeats):
            result = run_pipeline(summary, brief, db, session_id=f"eval-{name}-{i}", propose_fn=propose_fn)
            runs.append(score_part(result.proposal, reference, db, result.attempts == 1 and result.valid))
        rows.append((name, runs))

    lines = [f"# Eval results {date.today().isoformat()} · playbook {playbook_hash()} · {repeats} runs per part", "",
             "| part | " + " | ".join(COLUMNS) + " |", "|---|" + "---|" * len(COLUMNS)]
    totals = {c: [] for c in COLUMNS}
    for name, runs in rows:
        cells = []
        for c in COLUMNS:
            vals = [r[c] for r in runs]
            m = statistics.mean(vals)
            spread = (max(vals) - min(vals)) if len(vals) > 1 else 0.0
            totals[c].append(m)
            cells.append(f"{m:.2f} ±{spread / 2:.2f}")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines.append("| **all** | " + " | ".join(f"**{statistics.mean(totals[c]):.2f}**" if totals[c] else "—" for c in COLUMNS) + " |")
    table = "\n".join(lines) + "\n"

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{date.today().isoformat()}_{playbook_hash()}.md"
    out.write_text(table, encoding="utf-8")
    print(table)
    print("wrote", out)
    return table


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("parts", nargs="*")
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()
    run(args.parts or None, args.repeats)
