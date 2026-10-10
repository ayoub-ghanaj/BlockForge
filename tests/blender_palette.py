"""Version-exact palettes, optional materials and refresh in both workflows."""

import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import minecraft_builder
from minecraft_builder import catalog, ui
from minecraft_builder.perimeter import ui as perimeter

minecraft_builder.register()
bpy.context.preferences.use_preferences_save = False
checks = []
for target in ("MODEL", "PERIMETER"):
    p = ui.palette_settings(bpy.context, target)
    p.target_version = "26.1.2"
    glass = next(r for r in p.blocks if r.state == "minecraft:glass")
    assert glass.special_appearance and not p.special_appearance
    assert glass.state not in {b.state for b in ui.chosen_blocks(p)[1]}
    p.search = "minecraft:glass"
    p.regex_search = False
    bpy.ops.minecraft_builder.only_blocks(target=target, scope="FILTERED")
    assert not ui.eligible_rows(p)
    p.special_appearance = True
    assert [b.state for b in ui.chosen_blocks(p)[1]] == ["minecraft:glass"]
    assert len(ui.eligible_rows(p)) == 1
    # Reloading after an update keeps Include/Exclude and selected version.
    bpy.ops.minecraft_builder.load_preset(target=target)
    assert p.target_version == "26.1.2"
    assert [b.state for b in ui.chosen_blocks(p)[1]] == ["minecraft:glass"]
    assert len(p.blocks) == len(catalog.bundled()["26.1.2"].blocks)
    p.width = p.depth = p.height = 4
    if target == "MODEL":
        bpy.ops.object.select_all(action="DESELECT")
        cube = bpy.data.objects["Cube"]
        cube.select_set(True)
        bpy.context.view_layer.objects.active = cube
        bpy.ops.minecraft_builder.capture()
        bpy.ops.minecraft_builder.generate()
        build = ui.snapshot(p)
    else:
        p.project_kind = "FLOOR"
        p.protection = "NONE"
        bpy.ops.minecraft_perimeter.generate()
        build = perimeter.snapshot(p)
    assert build["palette"] == ["minecraft:glass"]
    p.special_appearance = False
    try:
        (ui.snapshot if target == "MODEL" else perimeter.snapshot)(p)
        raise AssertionError("Changed optional choice did not invalidate preview")
    except ValueError:
        pass
    checks.append(
        target
        + ": optional checkbox, exclusive glass palette, generation, refresh preserves rules and signature invalidation"
    )
report = {"status": "passed", "blender": bpy.app.version_string, "checks": checks}
out = ROOT / "build/verification"
out.mkdir(parents=True, exist_ok=True)
(out / "blender-palette.json").write_text(json.dumps(report, indent=2))
print("BLENDER_PALETTE_PASS", json.dumps(report), flush=True)
