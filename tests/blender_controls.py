"""Exercise block controls and all six source-up directions in real Blender."""

import json
import math
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import minecraft_builder
from minecraft_builder import ui
from minecraft_builder.core.palette import linear

minecraft_builder.register()
p = bpy.context.scene.minecraft_builder
p.target_version = "26.1.2"
out = ROOT / "build/upright"
out.mkdir(parents=True, exist_ok=True)
report = {"blender": bpy.app.version_string, "checks": []}

# Row editing is independent of active-row selection.
blue = next(r for r in p.blocks if r.state == "minecraft:blue_wool")
red = next(r for r in p.blocks if r.state == "minecraft:red_wool")
blue.policy = "DENY"
assert "minecraft:blue_wool" not in {b.state for b in ui.chosen_blocks(p)[1]}
blue.policy = "ALLOW"
red.policy = "ALLOW"
p.whitelist = True
assert {b.state for b in ui.chosen_blocks(p)[1]} == {"minecraft:blue_wool", "minecraft:red_wool"}
report["checks"].append("direct row Include/Exclude changes eligible materials")

assert bpy.ops.minecraft_builder.material_preset(preset="ALL") == {"FINISHED"}
p.search = r"minecraft:(red|blue)_wool$"
p.regex_search = True
assert bpy.ops.minecraft_builder.select_blocks(mode="ALL") == {"FINISHED"}
assert {r.state for r in p.blocks if r.selected} == {"minecraft:red_wool", "minecraft:blue_wool"}
p.rule_scope = "CHECKED"
assert bpy.ops.minecraft_builder.rules(policy="DENY") == {"FINISHED"}
assert blue.policy == red.policy == "DENY"
assert sum(r.policy == "DENY" for r in p.blocks) == 2
assert bpy.ops.minecraft_builder.select_blocks(mode="INVERT") == {"FINISHED"}
assert not any(r.selected for r in p.blocks)
p.rule_scope = "FILTERED"
assert bpy.ops.minecraft_builder.rules(policy="ALLOW") == {"FINISHED"}
assert blue.policy == red.policy == "ALLOW"
p.search = "["
before = [r.policy for r in p.blocks]
try:
    bpy.ops.minecraft_builder.rules(policy="DENY")
except RuntimeError:
    pass  # Blender raises on reports marked ERROR.
assert before == [r.policy for r in p.blocks]
p.regex_search = False
p.search = "wool"
p.category = "ALL"
assert sum(ui.matches_filter(p, r) for r in p.blocks) == 16
report["checks"].append(
    "regex, literal search, select all, invert, checked and filtered scopes, invalid-regex guard"
)

# The user must be able to make an EXCLUSIVE allow-list in one action.
assert bpy.ops.minecraft_builder.material_preset(preset="ALL") == {"FINISHED"}
p.search = "minecraft:blue_wool"
p.regex_search = False
assert bpy.ops.minecraft_builder.only_blocks(scope="FILTERED") == {"FINISHED"}
assert p.whitelist and {b.state for b in ui.chosen_blocks(p)[1]} == {"minecraft:blue_wool"}
assert len(ui.eligible_rows(p)) == 1
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_cube_add(size=2)
p.width = p.height = p.depth = 4
assert bpy.ops.minecraft_builder.capture() == {"FINISHED"}
assert bpy.ops.minecraft_builder.generate() == {"FINISHED"}
assert ui.snapshot(p)["palette"] == ["minecraft:blue_wool"]
assert bpy.ops.minecraft_builder.select_blocks(mode="NONE") == {"FINISHED"}
red.selected = True
assert bpy.ops.minecraft_builder.only_blocks(scope="CHECKED") == {"FINISHED"}
assert {b.state for b in ui.chosen_blocks(p)[1]} == {"minecraft:red_wool"}
assert bpy.ops.minecraft_builder.generate() == {"FINISHED"}
assert ui.snapshot(p)["palette"] == ["minecraft:red_wool"]
p.regex_search = True
p.search = r"minecraft:(red|blue)_wool$"
assert bpy.ops.minecraft_builder.only_blocks(scope="FILTERED") == {"FINISHED"}
assert {b.state for b in ui.chosen_blocks(p)[1]} == {"minecraft:red_wool", "minecraft:blue_wool"}
p.search = "does_not_exist"
before = [r.policy for r in p.blocks]
assert bpy.ops.minecraft_builder.only_blocks(scope="FILTERED") == {"CANCELLED"}
assert [r.policy for r in p.blocks] == before
report["checks"].append(
    "exclusive checked/search allow-list controls actual generated blocks; empty search preserves rules"
)

assert bpy.ops.minecraft_builder.material_preset(preset="SURVIVAL") == {"FINISHED"}
_, allowed = ui.chosen_blocks(p)
ids = {b.state.split("[")[0] for b in allowed}
assert "minecraft:blue_wool" in ids
assert "minecraft:budding_amethyst" not in ids
assert "minecraft:suspicious_sand" not in ids
assert "minecraft:petrified_oak_slab" not in ids
assert not any("infested_" in s for s in ids)
p.target_version = "1.13"
assert bpy.ops.minecraft_builder.material_preset(preset="SURVIVAL") == {"FINISHED"}
assert "minecraft:smooth_stone" not in {b.state for b in ui.chosen_blocks(p)[1]}
report["checks"].append("survival preset excludes unobtainable materials and pre-1.14 smooth stone")

p.target_version = "26.1.2"
assert bpy.ops.minecraft_builder.material_preset(preset="ALL") == {"FINISHED"}
p.whitelist = True
p.hollow = False
p.width = p.height = p.depth = 3
for r in p.blocks:
    if r.state in ("minecraft:red_wool", "minecraft:blue_wool"):
        r.policy = "ALLOW"
p.search = ""
p.slabs = p.stairs = False
blocks = {b.state: b for b in ui.chosen_blocks(p)[1]}
materials = {}
for state, b in blocks.items():
    mat = bpy.data.materials.new(state)
    mat.use_nodes = True
    mat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = tuple(
        linear(v / 255) for v in b.rgb
    ) + (1,)
    materials[state] = mat

for direction, axis, sign in [
    ("Z", 2, 1),
    ("NEG_Z", 2, -1),
    ("Y", 1, 1),
    ("NEG_Y", 1, -1),
    ("X", 0, 1),
    ("NEG_X", 0, -1),
]:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    p.sources.clear()
    p.model_up = direction
    parts = []
    for height, state in [(0, "minecraft:blue_wool"), (2, "minecraft:red_wool")]:
        location = [0, 0, 0]
        location[axis] = height * sign
        bpy.ops.mesh.primitive_cube_add(size=1, location=location)
        obj = bpy.context.object
        obj.data.materials.append(materials[state])
        parts.append(obj)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in parts:
        obj.select_set(True)
    assert bpy.ops.minecraft_builder.capture() == {"FINISHED"}
    assert bpy.ops.minecraft_builder.generate() == {"FINISHED"}, p.status
    build = ui.snapshot(p)
    positions = {build["palette"][i]: (x, y, z) for x, y, z, i in build["cells"]}
    assert positions == {"minecraft:blue_wool": (0, 0, 0), "minecraft:red_wool": (0, 2, 0)}, (
        direction,
        positions,
    )
    preview = next(
        o
        for o in bpy.context.scene.objects
        if o.get("minecraft_builder_preview") == p.preview_token
    )
    # The same preview has its red head above its blue feet in Blender Z.
    zs = {}
    for polygon in preview.data.polygons:
        color = tuple(
            round(v * 255) for v in preview.data.materials[polygon.material_index].diffuse_color[:3]
        )
        zs.setdefault(color, []).extend(preview.data.vertices[i].co.z for i in polygon.vertices)
    assert len(zs) == 2 and sorted((min(v), max(v)) for v in zs.values()) == [
        (0.0, 1.0),
        (2.0, 3.0),
    ]
    if direction == "Z":
        original_scale = tuple(preview.scale)
        original_cells = build["cells"]
        p.preview_real_scale = True
        assert tuple(preview.scale) == (1.0, 1.0, 1.0)
        assert ui.snapshot(p)["cells"] == original_cells
        bpy.context.scene.unit_settings.scale_length = 0.01
        p.preview_real_scale = False
        p.preview_real_scale = True
        assert all(abs(v - 100) < 1e-3 for v in preview.scale)
        bpy.context.scene.unit_settings.scale_length = 1
        p.preview_real_scale = False
        assert tuple(preview.scale) == original_scale
        (out / "orientation_probe.json").write_text(json.dumps(build))
        for fmt in ("schem", "litematic", "bp"):
            assert bpy.ops.minecraft_builder.export(
                filepath=str(out / ("orientation_probe." + fmt)), format=fmt
            ) == {"FINISHED"}
    preview.rotation_euler.x = math.pi
    try:
        ui.snapshot(p)
        raise AssertionError("Preview-only rotation was silently ignored")
    except ValueError as error:
        assert "Preview was rotated" in str(error)
    preview.rotation_euler.x = 0
    ui.snapshot(p)
    report["checks"].append(
        "upright red head / blue feet and preview transform guard: " + direction
    )

report["status"] = "passed"
(ROOT / "build/verification/blender-controls.json").write_text(json.dumps(report, indent=2))
print("BLENDER_CONTROLS_PASS", json.dumps(report))
