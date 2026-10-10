"""Exercise an in-session extension upgrade with cached, disabled old modules."""

import importlib
import json
import sys
import tomllib
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
bpy.context.preferences.use_preferences_save = False
folder = ROOT / ".testing/blender-upgrade-repo"
folder.mkdir(parents=True, exist_ok=True)
repo = bpy.context.preferences.extensions.repos.new(
    name="Builder upgrade test",
    module="builder_upgrade_test",
    custom_directory=str(folder),
    remote_url="",
    source="USER",
)
package = "bl_ext." + repo.module + ".minecraft_builder"
target = (
    sys.argv[sys.argv.index("--") + 1]
    if "--" in sys.argv
    else tomllib.loads((ROOT / "minecraft_builder/blender_manifest.toml").read_text())["version"]
)
repair_broken = "broken" in sys.argv
previous = "0.4.0" if "from040" in sys.argv else "0.1.2"
out = ROOT / "build/verification"
out.mkdir(parents=True, exist_ok=True)
report = {
    "blender": bpy.app.version_string,
    "from": previous,
    "to": target,
    "repair_broken_030": repair_broken,
    "checks": [],
}


def install(version):
    path = ROOT / "dist" / f"minecraft_builder-{version}.zip"
    if not path.exists():
        path = ROOT / "tests/fixtures/releases" / path.name
    assert bpy.ops.extensions.package_install_files(
        filepath=str(path), repo=repo.module, enable_on_install=True
    ) == {"FINISHED"}


install(previous)
old_ui = importlib.import_module(package + ".ui")
if previous == "0.1.2":
    assert not hasattr(old_ui, "palette_settings")
p = bpy.context.scene.minecraft_builder
p.target_version = "26.1.2"
p.width = p.height = p.depth = 8
bpy.ops.object.select_all(action="DESELECT")
cube = bpy.data.objects["Cube"]
cube.select_set(True)
bpy.context.view_layer.objects.active = cube
assert bpy.ops.minecraft_builder.capture() == {"FINISHED"}
assert bpy.ops.minecraft_builder.generate() == {"FINISHED"}
original = old_ui.snapshot(p)
assert len(original["cells"]) == 296
snapshot_name = p.snapshot.name
assert bpy.ops.preferences.addon_disable(module=package) == {"FINISHED"}
assert package + ".ui" in sys.modules, "Test must retain the cached old submodule"
if repair_broken:
    install("0.3.0")
    assert not hasattr(importlib.import_module(package + ".ui"), "palette_settings")
    assert not hasattr(bpy.context.scene.minecraft_builder, "edit_enabled")
    report["checks"].append(
        "reproduced both missing palette_settings and missing edit_enabled in mixed 0.3.0"
    )
install(target)
new_ui = importlib.import_module(package + ".ui")
report["has_palette_settings"] = hasattr(new_ui, "palette_settings")
try:
    assert hasattr(new_ui, "palette_settings"), "Upgrade reused the old UI module"
    p = bpy.context.scene.minecraft_builder
    assert p.target_version == "26.1.2" and p.snapshot.name == snapshot_name
    assert hasattr(p, "edit_enabled") and hasattr(p, "manual_edits")
    assert new_ui.snapshot(p)["cells"] == original["cells"]
    assert not p.face_matching, (
        "An old scene must keep average-color settings until the user enables face matching"
    )
    report["checks"].append(
        "disabled "
        + previous
        + " -> current ZIP preserves version, settings and generated snapshot"
    )
    assert bpy.ops.minecraft_builder.edit_start(target="MODEL") == {"FINISHED"}
    p.edit_brush = "minecraft:blue_wool"
    p.edit_position = (3, 3, 3)
    assert bpy.ops.minecraft_builder.edit_action(target="MODEL", action="ADD") == {"FINISHED"}
    saved = new_ui.snapshot(p)
    assert len(saved["cells"]) == 297
    q = bpy.context.scene.minecraft_perimeter
    q.target_version = "26.1.2"
    q.project_kind = "FLOOR"
    q.width = 8
    q.depth = 6
    assert hasattr(q, "edit_enabled")
    assert bpy.ops.minecraft_perimeter.generate() == {"FINISHED"}
    assert bpy.ops.minecraft_builder.edit_start(target="PERIMETER") == {"FINISHED"}
    q.edit_brush = "minecraft:blue_wool"
    q.edit_position = (1, 0, 1)
    assert bpy.ops.minecraft_builder.edit_action(target="PERIMETER", action="REPLACE") == {
        "FINISHED"
    }
    report["checks"].append(
        "Model and Perimeter live editing after upgrade without restarting Blender"
    )
    assert bpy.ops.preferences.addon_disable(module=package) == {"FINISHED"}
    assert bpy.ops.preferences.addon_enable(module=package) == {"FINISHED"}
    p = bpy.context.scene.minecraft_builder
    assert importlib.import_module(package + ".ui").snapshot(p)["cells"] == saved["cells"]
    edit = importlib.import_module(package + ".live_edit")
    for hooks in (
        bpy.app.handlers.load_post,
        bpy.app.handlers.undo_post,
        bpy.app.handlers.redo_post,
    ):
        assert sum(getattr(f, "__module__", "") == edit.__name__ for f in hooks) == 1, (
            "Duplicate edit handlers"
        )
    report["checks"].append("disable and re-enable preserves saved manual edits")
    report["status"] = "passed"
finally:
    if "status" not in report:
        report["status"] = "failed"
    (
        out
        / (
            "blender-upgrade-"
            + target
            + ("-broken" if repair_broken else "-from040" if previous == "0.4.0" else "")
            + ".json"
        )
    ).write_text(json.dumps(report, indent=2))
    print("BLENDER_UPGRADE", json.dumps(report), flush=True)
