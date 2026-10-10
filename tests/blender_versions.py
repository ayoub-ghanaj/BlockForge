"""Regression checks for explicit version selection and saved-file migration."""

import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import minecraft_builder
from minecraft_builder import catalog, ui
from minecraft_builder.core.palette import Profile

minecraft_builder.register()
p = bpy.context.scene.minecraft_builder
assert p.target_version == "NONE"
assert not bpy.ops.minecraft_builder.generate.poll()
p.target_version = "26.1.2"
assert p.loaded_version == "26.1.2" and len(p.blocks) > 450
assert p["selected_profile_id"] == "26.1.2"
assert bpy.ops.minecraft_builder.generate.poll()

# Inserting a new preset and reversing the list must not change this scene.
original = catalog.profiles


def reordered(settings):
    profiles = original(settings)
    return {
        "future-test": Profile("future-test", 9999, profiles["26.1.2"].blocks),
        **dict(reversed(list(profiles.items()))),
    }


catalog.profiles = reordered
ui.version_items(p, None)
assert p.target_version == "26.1.2"
catalog.profiles = original

out = ROOT / "build/verification"
out.mkdir(parents=True, exist_ok=True)
(ROOT / ".testing").mkdir(exist_ok=True)
saved = ROOT / ".testing/version-selection.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(saved))
bpy.ops.wm.open_mainfile(filepath=str(saved))
p = bpy.context.scene.minecraft_builder
assert p.target_version == "26.1.2"
p.target_version = "NONE"
assert p.target_version == "NONE" and not bpy.ops.minecraft_builder.generate.poll()

# Exercise the legacy stored-field layout using a generated cube, so the
# regression can run in a fresh checkout without privately imported models.
p.target_version = "26.1.2"
p.width = p.height = p.depth = 8
bpy.ops.object.select_all(action="DESELECT")
cube = bpy.data.objects.get("Cube")
cube.select_set(True)
bpy.context.view_layer.objects.active = cube
assert bpy.ops.minecraft_builder.capture() == {"FINISHED"}
assert bpy.ops.minecraft_builder.generate() == {"FINISHED"}, p.status
del p["selected_profile_id"]
assert p.loaded_version == "26.1.2"
assert p.target_version == "26.1.2"
build = ui.snapshot(p)
assert len(build["cells"]) == 296
assert bpy.ops.minecraft_builder.export(filepath=str(out / "migration-cube.bp"), format="bp") == {
    "FINISHED"
}
p.target_version = "26.3"
try:
    ui.snapshot(p)
    raise AssertionError("Stale preview exported after changing versions")
except ValueError as error:
    assert "Settings changed" in str(error)
report = {
    "status": "passed",
    "blender": bpy.app.version_string,
    "new_scene_requires_version": True,
    "selection_survives_preset_reordering": True,
    "selection_survives_save_reload": True,
    "legacy_version_fields_preserve_preview": True,
    "version_change_requires_regeneration": True,
}
(out / "blender-versions.json").write_text(json.dumps(report, indent=2))
print("VERSION_SELECTION_PASS", json.dumps(report))
