# evals/make_parts.py
"""cadquery scripts for the eval parts. Run: python -m evals.make_parts"""
from __future__ import annotations

from pathlib import Path
import cadquery as cq

PARTS_DIR = Path(__file__).parent / "parts"


def bracket_l_4hole():
    base = cq.Workplane("XY").box(120, 80, 8).faces(">Z").workplane() \
        .rect(90, 50, forConstruction=True).vertices().hole(9)
    upright = cq.Workplane("XZ").center(0, 40).box(120, 80, 8).translate((0, -36, 0))
    return base.union(upright)  # upright spans z 0..80, overlapping the 8 mm base so the union fuses


def tray_open():
    outer = cq.Workplane("XY").box(300, 200, 60)
    inner = cq.Workplane("XY").box(296, 196, 60).translate((0, 0, 2))
    tray = outer.cut(inner)
    return tray.faces("<Z").workplane().rect(260, 160, forConstruction=True).vertices().hole(6)


def shaft_stepped():
    return (cq.Workplane("YZ").circle(15).extrude(60)
            .faces(">X").workplane().circle(20).extrude(100)
            .faces(">X").workplane().circle(15).extrude(60))


PARTS = {
    "bracket_l_4hole": bracket_l_4hole,
    "tray_open": tray_open,
    "shaft_stepped": shaft_stepped,
}


def main(names=None):
    for name, builder in PARTS.items():
        if names and name not in names:
            continue
        out = PARTS_DIR / name
        out.mkdir(parents=True, exist_ok=True)
        cq.exporters.export(builder(), str(out / "part.step"))
        print("wrote", out / "part.step")


if __name__ == "__main__":
    import sys
    main(sys.argv[1:] or None)
