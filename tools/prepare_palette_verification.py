"""Stage a labelled material gallery and exact game-shape checks for 26.1.2."""

import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from minecraft_builder.catalog import bundled
from minecraft_builder.core import exporters
from minecraft_builder.core.shapes import orientations, state_mask, with_properties


def main():
    out = ROOT / "build/palette-audit/game"
    out.mkdir(parents=True, exist_ok=True)
    profile = bundled()["26.1.2"]
    blocks = list(profile.blocks)
    columns = 24
    width = columns * 3
    depth = math.ceil(len(blocks) / columns) * 3
    palette = [b.state for b in blocks]
    colors = [b.rgb for b in blocks]
    shapes = [b.shape for b in blocks]
    stone = palette.index("minecraft:stone")
    water = len(palette)
    palette.append("minecraft:water[level=0]")
    colors.append((60, 90, 210))
    shapes.append("cube")
    cells = {(x, y, z): stone for x in range(width) for z in range(depth) for y in (0, 1)}
    rows = []
    for i, b in enumerate(blocks):
        x = 3 * (i % columns) + 1
        z = 3 * (i // columns) + 1
        cells[x, 2, z] = i
        # Live coral needs adjacent water. A sealed water cell underneath keeps
        # its color without introducing water as a converter material choice.
        name = b.state.split("[")[0]
        if name.endswith("_coral_block") and not name.startswith("minecraft:dead_"):
            cells[x, 1, z] = water
        rows.append((x, 2, z, b.state, ";".join(b.appearance), *b.rgb))
    build = {
        "size": [width, 4, depth],
        "version": profile.id,
        "data_version": profile.data_version,
        "palette": palette,
        "colors": colors,
        "shapes": shapes,
        "cells": [[*pos, index] for pos, index in cells.items()],
    }
    (out / "palette_gallery.json").write_text(json.dumps(build))
    for fmt in ("schem", "litematic", "bp"):
        exporters.write(
            out / ("palette_gallery." + fmt),
            build,
            fmt,
            f"Palette gallery - {len(blocks)} materials - MC26.1.2",
        )
    with (out / "palette-gallery.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("X", "Y", "Z", "State", "Optional appearance", "R", "G", "B"))
        writer.writerows(rows)
    cases = {}
    for b in blocks:
        for state, mask in orientations(b):
            cases[state] = mask
            if b.shape == "stairs":
                for corner in ("inner_left", "inner_right", "outer_left", "outer_right"):
                    changed = with_properties(state, shape=corner)
                    cases[changed] = state_mask(changed, "stairs")
    (out / "shape-cases.json").write_text(
        json.dumps([{"state": s, "mask": m} for s, m in cases.items()])
    )
    (out / "cases.json").write_text(json.dumps(["palette_gallery"]))
    print(len(blocks), "materials;", len(cases), "exact shapes;", len(cells), "gallery blocks")


if __name__ == "__main__":
    main()
