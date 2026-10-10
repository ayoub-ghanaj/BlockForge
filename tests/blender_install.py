"""Install the real ZIP into a project-local repository and exercise it."""

import importlib
import json
import tomllib
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
bpy.context.preferences.use_preferences_save = False
folder = ROOT / ".testing/blender-extension-repo"
folder.mkdir(parents=True, exist_ok=True)
repo = bpy.context.preferences.extensions.repos.new(
    name="Builder local test",
    module="builder_local_test",
    custom_directory=str(folder),
    remote_url="",
    source="USER",
)
version = tomllib.loads((ROOT / "minecraft_builder/blender_manifest.toml").read_text())["version"]
zip_name = f"minecraft_builder-{version}.zip"
result = bpy.ops.extensions.package_install_files(
    filepath=str(ROOT / "dist" / zip_name), repo=repo.module, enable_on_install=True
)
assert result == {"FINISHED"}, result
module = importlib.import_module("bl_ext.builder_local_test.minecraft_builder.ui")
p = bpy.context.scene.minecraft_builder
assert p.target_version == "NONE", p.target_version
assert not bpy.ops.minecraft_builder.generate.poll()
p.target_version = "26.1.2"
p.width = p.height = p.depth = 8
bpy.ops.object.select_all(action="DESELECT")
cube = bpy.data.objects.get("Cube")
cube.select_set(True)
bpy.context.view_layer.objects.active = cube
assert bpy.ops.minecraft_builder.capture() == {"FINISHED"}
assert bpy.ops.minecraft_builder.generate() == {"FINISHED"}, p.status
assert len(module.snapshot(p)["cells"]) == 296
p.preview_real_scale = True
preview = next(
    o for o in bpy.context.scene.objects if o.get("minecraft_builder_preview") == p.preview_token
)
assert tuple(preview.scale) == (1, 1, 1)
perimeter = importlib.import_module("bl_ext.builder_local_test.minecraft_builder.perimeter.ui")
q = bpy.context.scene.minecraft_perimeter
q.target_version = "26.1.2"
q.project_kind = "FLOOR"
q.width = 8
q.depth = 6
assert bpy.ops.minecraft_perimeter.generate() == {"FINISHED"}, q.status
assert len(perimeter.snapshot(q)["cells"]) == 96
assert len(module.snapshot(p)["cells"]) == 296
edit = importlib.import_module("bl_ext.builder_local_test.minecraft_builder.live_edit")
q.protection = "GLASS"
q.cover_kind = "BUTTON"
q.cover_material = "minecraft:stone_button[face=floor,facing=north,powered=false]"
assert bpy.ops.minecraft_perimeter.generate() == {"FINISHED"}
assert perimeter.snapshot(q)["perimeter"]["protection"]["cover_kind"] == "BUTTON"
assert bpy.ops.minecraft_builder.edit_start(target="PERIMETER") == {"FINISHED"}
q.edit_position = (1, 0, 1)
q.edit_brush = "minecraft:blue_wool"
assert bpy.ops.minecraft_builder.edit_action(target="PERIMETER", action="REPLACE") == {"FINISHED"}
assert edit.session(bpy.context, q, "PERIMETER").cells[1, 0, 1] == "minecraft:blue_wool"
assert perimeter.snapshot(q)["manual_edits"]["applied"] == 1
assert bpy.ops.minecraft_builder.edit_action(target="PERIMETER", action="UNDO") == {"FINISHED"}
assert p.face_matching and q.face_matching
assert hasattr(q, "texture_preview") and hasattr(p, "edit_radius")
q.edit_selection_a = (1, 0, 1)
q.edit_selection_b = (2, 0, 2)
assert bpy.ops.minecraft_builder.bulk_edit(target="PERIMETER", action="FILL") == {"FINISHED"}
assert all(
    edit.session(bpy.context, q, "PERIMETER").cells[x, 0, z] == "minecraft:blue_wool"
    for x in (1, 2)
    for z in (1, 2)
)
assert bpy.ops.minecraft_perimeter.check_protection() == {"FINISHED"}
protection = importlib.import_module("bl_ext.builder_local_test.minecraft_builder.protection_ui")
assert protection.current(q)["issue_count"] == 0
report = {
    "blender": bpy.app.version_string,
    "zip": zip_name,
    "installed": True,
    "enabled": True,
    "generated_hollow_blocks": 296,
    "generated_perimeter_blocks": 96,
    "one_meter_checkbox": True,
    "ground_cover": True,
    "live_edit_and_undo": True,
    "bulk_edit_and_protection": True,
    "module": module.__package__,
}
(ROOT / "build/verification/blender-install.json").write_text(json.dumps(report, indent=2))
print("ZIP_INSTALL_PASS", json.dumps(report))
