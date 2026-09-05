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


def bracket_flat_2hole():
    return (cq.Workplane("XY").box(100, 40, 10)
            .faces(">Z").workplane().pushPoints([(-35, 0), (35, 0)]).hole(8))


def mount_pedestal():
    base = cq.Workplane("XY").box(120, 120, 10).faces(">Z").workplane() \
        .rect(90, 90, forConstruction=True).vertices().hole(10)
    post = cq.Workplane("XY").circle(20).extrude(80).translate((0, 0, 5))
    return base.union(post).faces(">Z").workplane().hole(12)


def enclosure_lidless():
    outer = cq.Workplane("XY").box(200, 150, 80)
    inner = cq.Workplane("XY").box(194, 144, 80).translate((0, 0, 3))
    box = outer.cut(inner)
    return box.faces("<Z").workplane().rect(170, 120, forConstruction=True).vertices().hole(5)


def frame_tube():
    """500 mm rectangular tube with 5 mm closed end plates; four holes in the -X plate."""
    outer = cq.Workplane("XY").box(500, 60, 40)
    inner = cq.Workplane("XY").box(490, 54, 34)
    tube = outer.cut(inner)
    return tube.faces("<X").workplane().rect(30, 15, forConstruction=True).vertices().hole(6)


def weldment_tee():
    beam = cq.Workplane("YZ").rect(50, 50).extrude(400).translate((-200, 0, 0))
    stub = cq.Workplane("XZ").rect(50, 50).extrude(150).translate((0, 0, 0))
    return beam.union(stub).faces("<X").workplane().rect(30, 30, forConstruction=True).vertices().hole(8)


def pin_clevis():
    return cq.Workplane("YZ").circle(10).extrude(120).faces(">X").workplane().circle(14).extrude(8)


def lid_flat():
    return (cq.Workplane("XY").box(300, 200, 6)
            .faces(">Z").workplane().rect(280, 180, forConstruction=True).vertices().hole(6)
            .faces(">Z").workplane().pushPoints([(0, 90), (0, -90)]).hole(6))


PARTS = {
    "bracket_l_4hole": bracket_l_4hole,
    "bracket_flat_2hole": bracket_flat_2hole,
    "mount_pedestal": mount_pedestal,
    "tray_open": tray_open,
    "enclosure_lidless": enclosure_lidless,
    "frame_tube": frame_tube,
    "weldment_tee": weldment_tee,
    "shaft_stepped": shaft_stepped,
    "pin_clevis": pin_clevis,
    "lid_flat": lid_flat,
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
