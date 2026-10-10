"""Exercise independent perimeter UI, image/decor conversion, preview and exports."""

import json
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import minecraft_builder
from minecraft_builder import ui as model
from minecraft_builder.perimeter import blender_bridge as bridge
from minecraft_builder.perimeter import ui

OUT = ROOT / "build/perimeter"
OUT.mkdir(parents=True, exist_ok=True)
start = time.monotonic()
minecraft_builder.register()
scene = bpy.context.scene
p = scene.minecraft_perimeter
m = scene.minecraft_builder
report = {"blender": bpy.app.version_string, "checks": []}
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)

# Keep a real model preview and snapshot alive throughout perimeter edits.
m.target_version = "26.1.2"
m.width = m.height = m.depth = 4
bpy.ops.mesh.primitive_cube_add(size=2)
source = bpy.context.object
source.name = "Independent model source"
bpy.ops.minecraft_builder.capture()
bpy.ops.minecraft_builder.generate()
model_build = model.snapshot(m)
model_token = m.preview_token
model_snapshot = m.snapshot
assert p.target_version == "NONE" and not p.snapshot
p.target_version = "26.1.2"
p.search = r"minecraft:(white|black|cyan|orange|red|blue)_concrete$"
p.regex_search = True
assert bpy.ops.minecraft_builder.only_blocks(target="PERIMETER", scope="FILTERED") == {"FINISHED"}
assert len(model.chosen_blocks(p)[1]) == 6
assert not m.whitelist and m.snapshot == model_snapshot
report["checks"].append(
    "independent versions, exclusive palette rules, snapshots and model preview"
)

# Image pixels are stored bottom-to-top by Blender; adapter returns top-to-bottom.
blocks = {b.state: b for b in model.chosen_blocks(p)[1]}
colors = np.array(
    [
        blocks["minecraft:" + name + "_concrete"].rgb
        for name in ("cyan", "orange", "white", "black")
    ],
    dtype=np.uint8,
)
pixels = np.array([[colors[0], colors[1]], [colors[2], colors[3]]], dtype=np.uint8)
image = bpy.data.images.new("Perimeter orientation image", width=2, height=2, alpha=True)
rgba = np.concatenate((pixels[::-1] / 255, np.ones((2, 2, 1))), axis=2).astype(np.float32)
image.pixels.foreach_set(rgba.ravel())
image.update()
np.testing.assert_array_equal(bridge.image_pixels(image)[:, :, :3], pixels)
image.filepath_raw = str(OUT / "orientation-image.png")
image.file_format = "PNG"
image.save()
image.pack()
p.floor.image = image
p.face = "floor"
bpy.ops.minecraft_perimeter.image_size()
assert (p.width, p.depth) == (2, 2) and p.floor.fit == "PAD"
p.width = 32
p.depth = 24
p.height = 12
for name in ("floor", "north", "south", "west", "east"):
    face = getattr(p, name)
    face.image = image
    face.fit = "STRETCH"
assert bpy.ops.minecraft_perimeter.guide() == {"FINISHED"}
report["checks"].append(
    "image orientation, one-pixel-per-block dimensions and independent inside-facing wall images"
)

# Three stepped solids and a half-height top demonstrate full cubes and slabs.
bpy.ops.object.select_all(action="DESELECT")
parts = []
for number, (size, location) in enumerate(
    [
        ((8, 8, 2), (16, -12, 1)),
        ((6, 6, 2), (16, -12, 3)),
        ((4, 4, 2), (16, -12, 5)),
        ((2, 2, 0.5), (16, -12, 6.25)),
    ]
):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = "Decoration tier " + str(number + 1)
    obj.scale = size
    parts.append(obj)
    mat = bpy.data.materials.new("Tier " + str(number))
    mat.diffuse_color = (0.05, 0.5, 0.65, 1)
    mat.use_nodes = True
    mat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (
        0.05,
        0.5,
        0.65,
        1,
    )
    obj.data.materials.append(mat)
for obj in parts:
    obj.select_set(True)
# Include a real partial material so the half-height cap fits as slabs.
slab = next(r for r in p.blocks if r.state.startswith("minecraft:prismarine_slab["))
slab.policy = "ALLOW"
bpy.context.view_layer.update()
assert bpy.ops.minecraft_perimeter.decorations(action="ADD") == {"FINISHED"}
assert len(p.sources) == 4
p.hollow = False
cases = []
for treatment in ("NONE", "GLASS", "LIGHTS", "BOTH"):
    p.protection = treatment
    assert bpy.ops.minecraft_perimeter.generate() == {"FINISHED"}, p.status
    build = ui.snapshot(p)
    assert build["perimeter"]["decorations"]
    assert any(shape == "slab" for shape in build["shapes"]), build["shapes"]
    assert (
        model.snapshot(m) == model_build
        and m.snapshot == model_snapshot
        and m.preview_token == model_token
    )
    preview = next(
        o for o in scene.objects if o.get("minecraft_perimeter_generated") == p.preview_token
    )
    assert tuple(preview.scale) == (1, 1, 1)
    cells = build["cells"]
    p.preview_real_scale = False
    assert abs(preview.scale.x - 20 / 32) < 1e-5 and ui.snapshot(p)["cells"] == cells
    p.preview_real_scale = True
    assert (
        len([o for o in scene.objects if o.get("minecraft_perimeter_generated") == p.preview_token])
        == 1
    )
    name = "perimeter_" + treatment.lower()
    cases.append(name)
    p.build_name = name
    (OUT / (name + ".json")).write_text(json.dumps(build))
    for fmt in ("schem", "litematic", "bp"):
        assert bpy.ops.minecraft_perimeter.export(
            filepath=str(OUT / (name + "." + fmt)), format=fmt
        ) == {"FINISHED"}
    report["checks"].append(
        treatment
        + ": mesh decorations, slab fitting, preview scaling, three exports and model isolation"
    )

# Test scaled scene units with the same physical source geometry.
for obj in parts:
    obj.location *= 100
    obj.scale *= 100
scene.unit_settings.scale_length = 0.01
bpy.context.view_layer.update()
assert bpy.ops.minecraft_perimeter.generate() == {"FINISHED"}
assert ui.snapshot(p)["cells"] == cells
preview = next(
    o for o in scene.objects if o.get("minecraft_perimeter_generated") == p.preview_token
)
assert all(abs(s - 100) < 1e-3 for s in preview.scale)
for obj in parts:
    obj.location /= 100
    obj.scale /= 100
scene.unit_settings.scale_length = 1
bpy.context.view_layer.update()
assert bpy.ops.minecraft_perimeter.generate() == {"FINISHED"}
report["checks"].append(
    "centimeter scenes retain the same Minecraft cells and one-meter physical preview"
)

p.width += 1
try:
    ui.snapshot(p)
    raise AssertionError("Stale perimeter could be exported")
except ValueError as error:
    assert "settings changed" in str(error)
p.width -= 1
model.snapshot(m)
ui.snapshot(p)
report["checks"].append("perimeter changes invalidate only perimeter exports")

# Save a useful example focused on the independent perimeter preview.
p.step = 5
preview = next(
    o for o in scene.objects if o.get("minecraft_perimeter_generated") == p.preview_token
)
bpy.ops.object.select_all(action="DESELECT")
preview.select_set(True)
bpy.context.view_layer.objects.active = preview
for obj in scene.objects:
    if obj != preview:
        obj.hide_render = True
bpy.ops.object.camera_add(location=(65, -45, 35))
camera = bpy.context.object
target = Vector((56, -12, 3))
camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = camera
camera.data.type = "ORTHO"
camera.data.ortho_scale = 48
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "MATERIAL"
scene.display.shading.show_shadows = True
scene.display.shading.show_cavity = True
scene.render.resolution_x = 1200
scene.render.resolution_y = 900
scene.render.resolution_percentage = 100
scene.render.filepath = str(OUT / "perimeter-preview.png")
# The standalone bpy runner has no display for the optional Workbench image.
if bpy.app.binary_path:
    bpy.ops.render.render(write_still=True)
for area in bpy.context.screen.areas if bpy.context.screen else ():
    if area.type == "VIEW_3D":
        area.spaces.active.region_3d.view_location = target
        area.spaces.active.region_3d.view_distance = 55
        area.spaces.active.region_3d.view_rotation = camera.rotation_euler.to_quaternion()
        area.spaces.active.clip_end = 5000
        area.spaces.active.show_region_ui = True
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "perimeter-example.blend"))
bpy.ops.wm.open_mainfile(filepath=str(OUT / "perimeter-example.blend"))
p = bpy.context.scene.minecraft_perimeter
m = bpy.context.scene.minecraft_builder
assert ui.snapshot(p)["cells"] == cells and model.snapshot(m) == model_build
report["checks"].append("saved Blender project retains independent snapshots and settings")
(OUT / "cases.json").write_text(json.dumps(cases))
report.update(status="passed", seconds=round(time.monotonic() - start, 2))
(OUT / "blender-perimeter.json").write_text(json.dumps(report, indent=2))
print("BLENDER_PERIMETER_PASS", json.dumps(report))
