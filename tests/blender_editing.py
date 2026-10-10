"""Block edits must change data, local preview chunks, saves and all exports."""

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import minecraft_builder
from minecraft_builder import live_edit as edit
from minecraft_builder import ui
from minecraft_builder.perimeter import ui as perimeter_ui

OUT = ROOT / "build/live-edit"
OUT.mkdir(parents=True, exist_ok=True)
minecraft_builder.register()
scene = bpy.context.scene
report = {"blender": bpy.app.version_string, "checks": []}
cases = []


def action(target, mode):
    result = bpy.ops.minecraft_builder.edit_action(target=target, action=mode)
    assert result == {"FINISHED"}, (target, mode, result)


def lookup(build):
    origin = build.get("perimeter", {}).get("origin", (0, 0, 0))
    return {
        tuple(p[i] + origin[i] for i in range(3)): build["palette"][p[3]] for p in build["cells"]
    }


def export(p, target, name):
    build = (ui if target == "MODEL" else perimeter_ui).snapshot(p)
    (OUT / (name + ".json")).write_text(json.dumps(build))
    cases.append(name)
    operator = (
        bpy.ops.minecraft_builder.export
        if target == "MODEL"
        else bpy.ops.minecraft_perimeter.export
    )
    for fmt in ("schem", "litematic", "bp"):
        assert operator(filepath=str(OUT / (name + "." + fmt)), format=fmt) == {"FINISHED"}


m = scene.minecraft_builder
m.target_version = "26.1.2"
m.width = m.height = m.depth = 8
bpy.ops.object.select_all(action="DESELECT")
source = bpy.data.objects["Cube"]
source.select_set(True)
bpy.context.view_layer.objects.active = source
bpy.ops.minecraft_builder.capture()
bpy.ops.minecraft_builder.generate()
base = ui.snapshot(m)
assert bpy.ops.minecraft_builder.edit_start(target="MODEL") == {"FINISHED"}
m.edit_brush = "minecraft:blue_wool"
m.edit_position = (3, 3, 3)
action("MODEL", "ADD")
m.edit_position = (0, 0, 0)
action("MODEL", "DELETE")
m.edit_position = (1, 0, 0)
action("MODEL", "REPLACE")
action("MODEL", "PICK")
m.edit_position = (4, 4, 4)
action("MODEL", "MOVE")
changed = ui.snapshot(m)
cells = lookup(changed)
assert (
    cells[3, 3, 3] == cells[4, 4, 4] == "minecraft:blue_wool"
    and (0, 0, 0) not in cells
    and (1, 0, 0) not in cells
)
action("MODEL", "UNDO")
assert (1, 0, 0) in lookup(ui.snapshot(m)) and (4, 4, 4) not in lookup(ui.snapshot(m))
action("MODEL", "REDO")
assert lookup(ui.snapshot(m)) == cells
export(m, "MODEL", "model_manual_edits")
model_document = edit.document(m)
assert m.edit_last_chunks <= 7
assert bpy.ops.minecraft_builder.generate() == {"FINISHED"}
assert lookup(ui.snapshot(m)) == cells and not m.edit_enabled
report["checks"].append("model add/delete/repaint/move, undo/redo, exports and keep-on-regenerate")
m.keep_manual_edits = False
assert bpy.ops.minecraft_builder.generate() == {"FINISHED"}
assert ui.snapshot(m)["cells"] == base["cells"] and not edit.document(m)["patches"]
report["checks"].append("regeneration checkbox resets edits only when a new preview succeeds")

p = scene.minecraft_perimeter
p.target_version = "26.1.2"
p.project_kind = "FLOOR"
p.width = 40
p.depth = 24
p.height = 12
p.glass_material = "minecraft:blue_stained_glass"
assert bpy.ops.minecraft_perimeter.generate() == {"FINISHED"}
original = perimeter_ui.snapshot(p)
assert bpy.ops.minecraft_builder.edit_start(target="PERIMETER") == {"FINISHED"}
root = edit.root_object(bpy.context, p, "PERIMETER")
old_chunks = {
    tuple(o["mb_edit_chunk_key"]): o.as_pointer() for o in root.children if "mb_edit_chunk_key" in o
}
p.edit_brush = "minecraft:orange_wool"
p.edit_position = (6, 3, 6)
action("PERIMETER", "ADD")
new_chunks = {
    tuple(o["mb_edit_chunk_key"]): o.as_pointer() for o in root.children if "mb_edit_chunk_key" in o
}
assert sum(old_chunks.get(k) == v for k, v in new_chunks.items()) >= len(old_chunks) - 1
# A native Blender move of the cursor must be read, not silently reset by Add.
p.edit_cursor.location = edit.display((10.5, 4.5, 10.5), "PERIMETER")
action("PERIMETER", "ADD")
assert lookup(perimeter_ui.snapshot(p))[10, 4, 10] == "minecraft:orange_wool"
p.edit_position = (1, 0, 1)
action("PERIMETER", "DELETE")
# Expand the floor-only export toward a canonical border cell without shifting visuals.
p.edit_position = (0, 2, 0)
action("PERIMETER", "ADD")
edited = perimeter_ui.snapshot(p)
assert edited["perimeter"]["origin"] == [0, 0, 0]
assert lookup(edited)[0, 2, 0] == "minecraft:orange_wool"
assert edited["perimeter"]["protection"]["manual_edits_require_inspection"]
model_unchanged = ui.snapshot(m)
export(p, "PERIMETER", "perimeter_manual_edits")
p.preview_real_scale = False
p.preview_real_scale = True
assert tuple(root.scale) == (1, 1, 1) and lookup(perimeter_ui.snapshot(p)) == lookup(edited)
assert ui.snapshot(m) == model_unchanged
report["checks"].append(
    "perimeter local section updates, canonical coordinates, dragged cursor placement, colored glass and independent model data"
)

# Deliver both edited workflows together after the isolation/reset checks.
m.keep_manual_edits = True
edit.save_document(m, model_document)
edit.generation_finished(bpy.context, m, "MODEL")
assert lookup(ui.snapshot(m)) == cells
p.step = 5
for area in bpy.context.screen.areas if bpy.context.screen else ():
    if area.type == "VIEW_3D":
        space = area.spaces.active
        space.show_region_ui = True
        space.region_3d.view_location = (44, -12, 2)
        space.region_3d.view_distance = 95
        space.region_3d.view_rotation = Vector((30, -50, 60)).to_track_quat("Z", "Y")
        space.shading.color_type = "MATERIAL"
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "live-edit-example.blend"))
bpy.ops.wm.open_mainfile(filepath=str(OUT / "live-edit-example.blend"))
p = bpy.context.scene.minecraft_perimeter
assert lookup(perimeter_ui.snapshot(p)) == lookup(edited)
assert bpy.ops.minecraft_builder.edit_start(target="PERIMETER") == {"FINISHED"}
action("PERIMETER", "UNDO")
assert (0, 2, 0) not in lookup(perimeter_ui.snapshot(p))
action("PERIMETER", "REDO")
assert lookup(perimeter_ui.snapshot(p)) == lookup(edited)
action("PERIMETER", "CLEAR")
assert lookup(perimeter_ui.snapshot(p)) == lookup(original)
action("PERIMETER", "UNDO")
assert lookup(perimeter_ui.snapshot(p)) == lookup(edited)
report["checks"].append(
    "saved block layer and undo history survive reload; Clear edits is undoable"
)
(OUT / "cases.json").write_text(json.dumps(cases))
report["status"] = "passed"
(OUT / "blender-live-edit.json").write_text(json.dumps(report, indent=2))
print("BLENDER_LIVE_EDIT_PASS", json.dumps(report))
