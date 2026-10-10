"""Exercise texture/attribute colors, shape fitting, rules, saved state and a cat."""

import json
import math
import struct
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from mathutils import Vector

import minecraft_builder
from minecraft_builder import ui
from minecraft_builder.blender_mesh import ColorSampler, extract_sources
from minecraft_builder.core.palette import Block, Profile, linear, profile_document
from minecraft_builder.core.shapes import state_mask

OUT = ROOT / "build/verification"
OUT.mkdir(parents=True, exist_ok=True)
start = time.monotonic()
minecraft_builder.register()
p = bpy.context.scene.minecraft_builder
p.target_version = "26.1.2"
report = {"blender": bpy.app.version_string, "checks": []}


def reset():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    p.sources.clear()
    p.width = p.height = p.depth = 8
    p.preserve = True
    p.hollow = False
    p.whitelist = False
    p.color_mode = "MATERIAL"
    p.interior_state = ""
    p.slabs = True
    p.stairs = True
    for row in p.blocks:
        row.policy = "AUTO"


def material(name, rgb):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = tuple(
        linear(c / 255) for c in rgb
    ) + (1,)
    return m


def generate():
    assert bpy.ops.minecraft_builder.capture() == {"FINISHED"}
    result = bpy.ops.minecraft_builder.generate()
    assert result == {"FINISHED"}, p.status
    return ui.snapshot(p)


reset()
bpy.ops.mesh.primitive_cube_add(size=2)
source = bpy.context.object
m = material("Texture test", (128, 128, 128))
source.data.materials.append(m)


# Encode known sRGB bytes locally; a fresh checkout must not depend on an image
# left behind by an earlier developer run.
def png_chunk(kind, data):
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


texture_bytes = (
    b"\x89PNG\r\n\x1a\n"
    + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0))
    + png_chunk(b"IDAT", zlib.compress((b"\0" + bytes((128, 64, 192, 255)) * 2) * 2))
    + png_chunk(b"IEND", b"")
)
(OUT / "texture-test.png").write_bytes(texture_bytes)
image = bpy.data.images.load(str(OUT / "texture-test.png"), check_existing=False)
node = m.node_tree.nodes.new("ShaderNodeTexImage")
node.image = image
node.interpolation = "Closest"
m.node_tree.links.new(
    node.outputs["Color"], m.node_tree.nodes.get("Principled BSDF").inputs["Base Color"]
)
sources, grid, _ = extract_sources([source], bpy.context.evaluated_depsgraph_get(), (8, 8, 8))
sample = ColorSampler(sources).sample((4, 4, 0))
assert sample == (128, 64, 192), sample
report["checks"].append({"texture_srgb": list(sample), "pixel_buffer": list(image.pixels[:4])})

# A color attribute uses linear values in Blender; verify display conversion.
attribute = source.data.color_attributes.new(name="Paint", type="FLOAT_COLOR", domain="CORNER")
for datum in attribute.data:
    datum.color = (linear(32 / 255), linear(160 / 255), linear(224 / 255), 1)
paint = m.node_tree.nodes.new("ShaderNodeVertexColor")
paint.layer_name = "Paint"
m.node_tree.links.new(
    paint.outputs["Color"], m.node_tree.nodes.get("Principled BSDF").inputs["Base Color"]
)
sources, _, _ = extract_sources([source], bpy.context.evaluated_depsgraph_get(), (8, 8, 8))
sample = ColorSampler(sources).sample((4, 4, 0))
assert sample == (32, 160, 224), sample
report["checks"].append({"color_attribute_srgb": list(sample)})

# Exact half-block geometry within fixed global bounds must produce real slabs.
reset()


def cube(name, location, scale):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    o = bpy.context.object
    o.name = name
    o.scale = scale
    return o


low = cube("Half-height source", (0.5, 0.5, 0.25), (1, 1, 0.5))
high = cube("Extent marker", (2.5, 0.5, 0.5), (1, 1, 1))
bpy.ops.object.select_all(action="DESELECT")
low.select_set(True)
high.select_set(True)
p.width = 3
p.height = 1
p.depth = 1
p.whitelist = True
for row in p.blocks:
    if row.state.split("[")[0] in (
        "minecraft:stone",
        "minecraft:stone_slab",
        "minecraft:stone_stairs",
    ):
        row.policy = "ALLOW"
build = generate()
assert any("slab" in s for s in build["palette"]), build["palette"]
report["checks"].append({"slab_fit": build["palette"]})

# All eight stair orientations are fitted through the actual Blender sampler.
from minecraft_builder.core.shapes import stair_mask

for facing in ("north", "east", "south", "west"):
    for half in ("bottom", "top"):
        reset()
        pieces = []
        mask = stair_mask(facing, half)
        for y in range(2):
            for z in range(2):
                for x in range(2):
                    if mask & (1 << (x + 2 * z + 4 * y)):
                        pieces.append(
                            cube(
                                "Stair octant",
                                ((x + 0.5) / 2, -(z + 0.5) / 2, (y + 0.5) / 2),
                                (0.5, 0.5, 0.5),
                            )
                        )
        bpy.ops.object.select_all(action="DESELECT")
        for obj in pieces:
            obj.select_set(True)
        p.width = p.height = p.depth = 1
        p.whitelist = True
        for row in p.blocks:
            if row.state.split("[")[0] in (
                "minecraft:stone",
                "minecraft:stone_slab",
                "minecraft:stone_stairs",
            ):
                row.policy = "ALLOW"
        build = generate()
        assert len(build["cells"]) == 1
        state = build["palette"][build["cells"][0][3]]
        assert "stairs" in state and state_mask(state, "stairs") == mask, (facing, half, state)
report["checks"].append({"stair_orientations_fitted": 8})

# Blacklist/whitelist and stale-preview protection in Blender's real operators.
reset()
bpy.ops.mesh.primitive_cube_add()
p.whitelist = True
for row in p.blocks:
    if row.state == "minecraft:blue_wool":
        row.policy = "ALLOW"
build = generate()
assert build["palette"] == ["minecraft:blue_wool"]
p.width = 9
try:
    ui.snapshot(p)
    raise AssertionError("Stale preview accepted")
except ValueError:
    pass
report["checks"].append({"whitelist_and_stale_preview": "passed"})

# Add a modded material through the optional palette file workflow.
custom = Profile("Custom test", 4790, (Block("example:blue_block", (1, 2, 200)),))
path = OUT / "custom-palette.json"
path.write_text(json.dumps(profile_document(custom)))
assert bpy.ops.minecraft_builder.import_palette(filepath=str(path)) == {"FINISHED"}
assert p.target_version == "Custom test" and p.blocks[0].state == "example:blue_block"
p.target_version = "26.1.2"
report["checks"].append({"palette_import": "passed"})

# A closed, colored cat assembled from separate meshes tests volume union.
reset()
orange = material("Cat warm coat", (191, 106, 47))
cream = material("Cat cream", (237, 210, 161))
dark = material("Cat dark", (26, 25, 24))
pink = material("Cat nose", (181, 93, 97))
green = material("Cat eyes", (113, 161, 58))
parts = []


def ellipsoid(name, loc, scale, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=16, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    obj.data.materials.append(mat)
    parts.append(obj)
    return obj


ellipsoid("Body", (0, 0, 1.75), (0.95, 0.75, 1.4), orange)
ellipsoid("Chest", (0, -0.54, 1.95), (0.65, 0.28, 0.95), cream)
ellipsoid("Head", (0, -0.12, 3.5), (1.05, 0.8, 0.95), orange)
for x in (-0.63, 0.63):
    ellipsoid("Paw", (x, -0.54, 0.28), (0.38, 0.55, 0.28), cream)
    ellipsoid("Eye", (x * 0.69, -0.82, 3.72), (0.19, 0.08, 0.23), green)
    ellipsoid("Pupil", (x * 0.69, -0.883, 3.73), (0.065, 0.035, 0.17), dark)
    ellipsoid("Muzzle", (x * 0.29, -0.83, 3.3), (0.29, 0.16, 0.2), cream)
    bpy.ops.mesh.primitive_cone_add(
        vertices=3,
        radius1=0.55,
        radius2=0,
        depth=1.05,
        location=(x, 0, 4.38),
        rotation=(0, 0, math.pi / 2),
    )
    obj = bpy.context.object
    obj.name = "Ear"
    obj.data.materials.append(orange)
    parts.append(obj)
ellipsoid("Nose", (0, -0.994, 3.42), (0.15, 0.08, 0.1), pink)
for i in range(7):
    t = i / 6
    ellipsoid("Tail", (0.75 + 0.8 * t, 0.42 + 0.35 * t, 0.42 + 1.4 * t), (0.23, 0.25, 0.31), orange)
bpy.ops.object.select_all(action="DESELECT")
for obj in parts:
    obj.select_set(True)
bpy.context.view_layer.objects.active = parts[0]
p.width = 32
p.height = 40
p.depth = 28
p.hollow = True
p.build_name = "Blender Cat"
p.author = "Minecraft Builder"
build = generate()
assert all(build["size"][i] <= [32, 40, 28][i] for i in range(3))
assert len(build["cells"]) > 500
assert any(s == "slab" for s in build["shapes"]) and any(s == "stairs" for s in build["shapes"]), (
    set(build["shapes"])
)
for kind in ("schem", "litematic", "bp"):
    assert bpy.ops.minecraft_builder.export(filepath=str(OUT / ("cat." + kind)), format=kind) == {
        "FINISHED"
    }
(OUT / "cat.json").write_text(json.dumps(build), encoding="utf-8")
bpy.ops.minecraft_builder.materials(filepath=str(OUT / "cat-materials.csv"))
report["cat"] = {
    "dimensions": build["size"],
    "blocks": len(build["cells"]),
    "states": len(build["palette"]),
    "shapes": {
        kind: sum(build["shapes"][i] == kind for *_, i in build["cells"])
        for kind in ("cube", "slab", "stairs")
    },
}

# Render an artifact with the source and generated preview side by side.
scene = bpy.context.scene
preview = next(o for o in scene.objects if o.get("minecraft_builder_preview") == p.preview_token)
for obj in scene.objects:
    obj.select_set(False)
preview.select_set(True)
bpy.context.view_layer.objects.active = preview
scene.render.engine = "CYCLES"
scene.cycles.samples = 24
scene.cycles.use_denoising = True
scene.world.color = (0.18, 0.18, 0.18)
bpy.ops.object.camera_add(location=(10, -16, 10))
camera = bpy.context.object
target = Vector((2.05, 0, 2.5))
camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
camera.data.type = "ORTHO"
camera.data.ortho_scale = 10.5
scene.camera = camera
for loc, power, size in [((2, -7, 10), 1800, 7), ((-5, 2, 7), 1200, 5), ((7, 5, 7), 1500, 4)]:
    bpy.ops.object.light_add(type="AREA", location=loc)
    light = bpy.context.object
    light.data.energy = power
    light.data.shape = "DISK"
    light.data.size = size
    light.rotation_euler = (target - light.location).to_track_quat("-Z", "Y").to_euler()
floor = cube("Presentation floor", (2, 0, -0.1), (30, 30, 0.15))
floor.data.materials.append(material("Floor", (40, 48, 61)))
scene.render.resolution_x = 1400
scene.render.resolution_y = 900
scene.render.resolution_percentage = 100
scene.render.filepath = str(OUT / "cat-preview.png")
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "cat-example.blend"))
# Keep the illustrative render local; CI exercises the geometry and exports above.
if bpy.app.binary_path:
    bpy.ops.render.render(write_still=True)
report["seconds"] = round(time.monotonic() - start, 2)
(OUT / "blender-integration.json").write_text(json.dumps(report, indent=2))
print("BLENDER_INTEGRATION_PASS", json.dumps(report))
