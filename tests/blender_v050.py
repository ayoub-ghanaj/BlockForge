"""Generic Blender fixtures: directional materials, packed textures and bulk edits."""

import json
import struct
import sys
import zipfile
import zlib
from pathlib import Path

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import minecraft_builder
from minecraft_builder import catalog, protection_ui, ui
from minecraft_builder import live_edit as edit
from minecraft_builder.core import exporters
from minecraft_builder.perimeter import streaming
from minecraft_builder.perimeter import ui as perimeter

OUT = ROOT / "build/v050"
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "game").mkdir(exist_ok=True)
bpy.context.preferences.use_preferences_save = False
minecraft_builder.register()
checks = []


def png(pixels):
    h, w, _ = pixels.shape

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\0" + row.tobytes() for row in pixels)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


pack = OUT / "generic-test-textures.zip"
with zipfile.ZipFile(pack, "w", zipfile.ZIP_DEFLATED) as archive:
    for number, name in enumerate(
        ("oak_log", "oak_log_top", "oak_planks", "stone", "blue_wool", "red_wool", "glass")
    ):
        pixels = np.zeros((16, 16, 4), np.uint8)
        pixels[:] = [
            (number * 31 + 40) % 256,
            (number * 57 + 70) % 256,
            (number * 79 + 20) % 256,
            255,
        ]
        pixels[:4, :, :3] = [255, 30, 20]
        pixels[:, 0, :3] = [20, 255, 30]
        if name == "glass":
            pixels[1:-1, 1:-1, 3] = 25
        archive.writestr("assets/minecraft/textures/block/" + name + ".png", png(pixels))


def select_palette(p, target):
    p.target_version = "26.1.2"
    p.search = r"minecraft:(oak_log|oak_stairs|stone|blue_wool|red_wool)(\[|$)"
    p.regex_search = True
    assert bpy.ops.minecraft_builder.only_blocks(target=target, scope="FILTERED") == {"FINISHED"}


def snapshot(p, target):
    return (ui.snapshot if target == "MODEL" else perimeter.snapshot)(p)


def cells(p, target):
    return edit.session(bpy.context, p, target).cells


def action(p, target, kind, pos=None):
    if pos is not None:
        p.edit_position = pos
    assert bpy.ops.minecraft_builder.edit_action(target=target, action=kind) == {"FINISHED"}


def bulk(p, target, kind):
    assert bpy.ops.minecraft_builder.bulk_edit(target=target, action=kind) == {"FINISHED"}


def assert_textures(p, target):
    root = edit.root_object(bpy.context, p, target)
    meshes = [
        o.data
        for o in [root, *root.children]
        if o.type == "MESH" and not o.get("mb_protection_overlay") and len(o.data.polygons)
    ]
    assert meshes
    for mesh in meshes:
        assert mesh.uv_layers.active is not None, mesh.name
        values = np.empty(len(mesh.loops) * 2, np.float32)
        mesh.uv_layers.active.data.foreach_get("uv", values)
        assert np.all(np.isfinite(values)) and values.min() >= -1e-5 and values.max() <= 1.00001
        assert mesh.materials[0] == p.texture_material
    assert p.texture_atlas.packed_file
    assert "needs refresh" not in p.texture_status, p.texture_status


for target in ("MODEL", "PERIMETER"):
    p = ui.palette_settings(bpy.context, target)
    select_palette(p, target)
    p.width = 12
    p.depth = 10
    p.height = 8
    p.preview_real_scale = True
    assert p.face_matching
    if target == "MODEL":
        p.preserve = False
        p.hollow = False
        bpy.ops.object.select_all(action="DESELECT")
        bpy.ops.mesh.primitive_cube_add(size=2, location=(13.5, -7.25, 3.0))
        source = bpy.context.object
        source.name = "Generic asymmetric rectangular fixture"
        # Different source faces, derived from a real material's per-face colors.
        block = next(
            b for b in catalog.bundled()["26.1.2"].blocks if b.state == "minecraft:oak_log[axis=y]"
        )
        colors = dict(block.faces)
        for face in source.data.polygons:
            rgb = colors["up" if abs(face.normal.x) > 0.5 else "north"]
            material = bpy.data.materials.new("Source face")
            material.diffuse_color = tuple(ui.linear(v / 255) for v in rgb) + (1,)
            source.data.materials.append(material)
            face.material_index = len(source.data.materials) - 1
        original = [tuple(v.co) for v in source.data.vertices]
        bpy.ops.minecraft_builder.capture()
        assert bpy.ops.minecraft_builder.generate() == {"FINISHED"}
        assert original == [tuple(v.co) for v in source.data.vertices]
        assert any("oak_log[axis=x]" in s for s in ui.snapshot(p)["palette"])
    else:
        p.project_kind = "FLOOR"
        p.protection = "GLASS"
        p.step = 5
        assert bpy.ops.minecraft_perimeter.generate() == {"FINISHED"}
        assert bpy.ops.minecraft_perimeter.check_protection() == {"FINISHED"}
        assert protection_ui.current(p)["issue_count"] == 0
    before = snapshot(p, target)
    assert bpy.ops.minecraft_builder.import_textures(target=target, filepath=str(pack)) == {
        "FINISHED"
    }
    assert snapshot(p, target) == before, "Textured display changed the exported build"
    assert_textures(p, target)
    assert bpy.ops.minecraft_builder.edit_start(target=target) == {"FINISHED"}
    assert_textures(p, target)  # Partitioning must retain UVs on unchanged sections.
    if target == "PERIMETER":
        action(p, target, "DELETE", (3, 1, 3))
        assert not protection_ui.current(p), "Old protection report survived a block edit"
        assert bpy.ops.minecraft_perimeter.check_protection() == {"FINISHED"}
        report = protection_ui.current(p)
        assert report["uncovered"] == 1 and report["unproven_light"] == 1, report
        (OUT / "protection-hole.json").write_text(json.dumps(report, indent=2))
        p.edit_brush = "minecraft:glass"
        action(p, target, "ADD", (3, 1, 3))
        assert bpy.ops.minecraft_perimeter.check_protection() == {"FINISHED"}
        assert protection_ui.current(p)["issue_count"] == 0
    y = 2 if target == "PERIMETER" else 0
    p.edit_selection_a = (1, y, 1)
    p.edit_selection_b = (3, y, 2)
    p.edit_brush = "minecraft:blue_wool"
    before = snapshot(p, target)
    bulk(p, target, "FILL")
    assert len(edit.document(p)["undo"][-1]) == 6
    action(p, target, "UNDO")
    assert snapshot(p, target)["cells"] == before["cells"]
    action(p, target, "REDO")
    bulk(p, target, "COPY")
    p.edit_position = (7, y, 5)
    p.edit_paste_overwrite = True
    p.edit_mirror = "X"
    bulk(p, target, "PASTE")
    assert all(
        cells(p, target)[x, y, z] == "minecraft:blue_wool"
        for x in range(7, 10)
        for z in range(5, 7)
    )
    p.edit_replace_source = "minecraft:blue_wool"
    p.edit_brush = "minecraft:red_wool"
    bulk(p, target, "REPLACE")
    assert cells(p, target)[1, y, 1] == "minecraft:red_wool"
    p.edit_position = (4, y, 4)
    p.edit_brush = "minecraft:oak_stairs"
    p.edit_facing = "east"
    action(p, target, "REPLACE" if target == "MODEL" else "ADD")
    p.edit_selection_a = p.edit_selection_b = (4, y, 4)
    p.edit_mirror = "X"
    bulk(p, target, "MIRROR")
    assert "facing=west" in cells(p, target)[4, y, 4]
    assert_textures(p, target)
    p.texture_preview = False
    assert bpy.ops.minecraft_builder.refresh_textures(target=target) == {"FINISHED"}
    p.texture_preview = True
    assert bpy.ops.minecraft_builder.refresh_textures(target=target) == {"FINISHED"}
    assert_textures(p, target)
    before = snapshot(p, target)
    assert (
        bpy.ops.minecraft_builder.generate()
        if target == "MODEL"
        else bpy.ops.minecraft_perimeter.generate()
    ) == {"FINISHED"}
    assert snapshot(p, target)["cells"] == before["cells"]
    assert_textures(p, target)
    # Export edited geometry through all formats; actual game reader cases.
    if target == "PERIMETER":
        assert bpy.ops.minecraft_perimeter.check_protection() == {"FINISHED"}
    result = snapshot(p, target)
    name = "generic_" + target.lower()
    (OUT / "game" / (name + ".json")).write_text(json.dumps(result))
    for fmt in ("schem", "litematic", "bp"):
        if target == "MODEL":
            exporters.write(OUT / "game" / (name + "." + fmt), result, fmt, name)
        else:
            streaming.write(OUT / "game" / (name + "." + fmt), result, fmt, name)
    checks.append(
        target
        + ": face matching, imported packed textures, UVs after chunk edits, bulk fill/copy/paste/mirror/replace, undo/redo, regeneration, three exports"
    )

# A differently shaped mesh verifies geometry independence beyond rectangular fixtures.
p = bpy.context.scene.minecraft_builder
saved_model = snapshot(p, "MODEL")
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "generic-feature-examples.blend"))
bpy.ops.wm.open_mainfile(filepath=str(OUT / "generic-feature-examples.blend"))
for target in ("MODEL", "PERIMETER"):
    p = ui.palette_settings(bpy.context, target)
    path = p.texture_source
    p.texture_source = str(OUT / "not-present.zip")
    assert bpy.ops.minecraft_builder.refresh_textures(target=target) == {"FINISHED"}
    assert_textures(p, target)
    p.texture_source = path
checks.append(
    "Packed atlases, UVs and manual edits survive save/reopen with the source ZIP unavailable"
)
p = bpy.context.scene.minecraft_builder
p.keep_manual_edits = False
p.texture_preview = False
bpy.ops.object.select_all(action="DESELECT")
bpy.ops.mesh.primitive_cone_add(
    vertices=7, radius1=1.7, radius2=0.4, depth=3.2, location=(-19, 4, 7)
)
source = bpy.context.object
source.name = "Independent seven-sided tapered fixture"
bpy.ops.minecraft_builder.capture()
assert bpy.ops.minecraft_builder.generate() == {"FINISHED"}
result = ui.snapshot(p)
assert result["cells"] and result["cells"] != saved_model["cells"]
assert not edit.document(p)["patches"]
checks.append(
    "Independent seven-sided tapered mesh converts without source-name or shape-specific rules"
)
p = bpy.context.scene.minecraft_perimeter
p.keep_manual_edits = False
p.texture_preview = False
p.width = 28
p.depth = 1
p.height = 4
p.protection = "LIGHTS"
p.check_dry_cover = False
p.light_material = "minecraft:sea_lantern"
assert bpy.ops.minecraft_perimeter.generate() == {"FINISHED"}
assert bpy.ops.minecraft_perimeter.check_protection() == {"FINISHED"}
assert protection_ui.current(p)["issue_count"] == 0
assert bpy.ops.minecraft_builder.edit_start(target="PERIMETER") == {"FINISHED"}
light = min(pos for pos, state in cells(p, "PERIMETER").items() if state == "minecraft:sea_lantern")
p.edit_brush = "minecraft:stone"
action(p, "PERIMETER", "REPLACE", light)
assert not protection_ui.current(p)
assert bpy.ops.minecraft_perimeter.check_protection() == {"FINISHED"}
assert protection_ui.current(p)["unproven_light"] > 0
p.edit_brush = "minecraft:sea_lantern"
action(p, "PERIMETER", "REPLACE", light)
assert bpy.ops.minecraft_perimeter.check_protection() == {"FINISHED"}
assert protection_ui.current(p)["issue_count"] == 0
result = perimeter.snapshot(p)
name = "generic_lit_perimeter"
(OUT / "game" / (name + ".json")).write_text(json.dumps(result))
for fmt in ("schem", "litematic", "bp"):
    streaming.write(OUT / "game" / (name + "." + fmt), result, fmt, name)
checks.append(
    "Removing a light invalidates the report and exposes unproven surfaces; restoring it passes the recheck"
)
report = {"status": "passed", "blender": bpy.app.version_string, "checks": checks}
(OUT / "blender-v050.json").write_text(json.dumps(report, indent=2))
(ROOT / "build/verification/blender-v050.json").write_text(json.dumps(report, indent=2))
(OUT / "game/cases.json").write_text(
    json.dumps(["generic_model", "generic_perimeter", "generic_lit_perimeter"])
)
print("BLENDER_V050_PASS", json.dumps(report), flush=True)
