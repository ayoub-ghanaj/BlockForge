"""Compare UV mapping and adjusted texture colors against actual Cycles bakes."""

import json
import math
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy

import minecraft_builder
from minecraft_builder import ui
from minecraft_builder.blender_mesh import ColorSampler, extract_sources, rgb_from_linear

OUT = ROOT / "build/verification"
OUT.mkdir(parents=True, exist_ok=True)
bpy.context.preferences.use_preferences_save = False
minecraft_builder.register()
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_plane_add(size=2)
plane = bpy.context.object
material = bpy.data.materials.new("Adjusted UV texture")
material.use_nodes = True
plane.data.materials.append(material)
nodes = material.node_tree.nodes
links = material.node_tree.links
shader = nodes.get("Principled BSDF")
output = nodes.get("Material Output")
coords = nodes.new("ShaderNodeTexCoord")
mapping = nodes.new("ShaderNodeMapping")
reroute = nodes.new("NodeReroute")
texture = nodes.new("ShaderNodeTexImage")
adjust = nodes.new("ShaderNodeHueSaturation")
color_reroute = nodes.new("NodeReroute")
links.new(coords.outputs["UV"], mapping.inputs["Vector"])
links.new(mapping.outputs["Vector"], reroute.inputs[0])
links.new(reroute.outputs[0], texture.inputs["Vector"])
links.new(texture.outputs["Color"], adjust.inputs["Color"])
links.new(adjust.outputs["Color"], color_reroute.inputs[0])
links.new(color_reroute.outputs[0], shader.inputs["Base Color"])


def chunk(kind, data):
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


# Unequal texels exercise filtering followed by scene-linear color adjustments.
texture_path = OUT / "material-nodes-texture.png"
texture_path.write_bytes(
    b"\x89PNG\r\n\x1a\n"
    + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0))
    + chunk(
        b"IDAT",
        zlib.compress(
            b"\0"
            + bytes((128, 64, 32, 255, 32, 64, 180, 255))
            + b"\0"
            + bytes((20, 150, 70, 255, 180, 30, 90, 255))
        ),
    )
    + chunk(b"IEND", b"")
)
texture.image = bpy.data.images.load(str(texture_path), check_existing=False)
target = bpy.data.images.new("Shader reference", width=16, height=16, float_buffer=True)
target_node = nodes.new("ShaderNodeTexImage")
target_node.image = target
emission = nodes.new("ShaderNodeEmission")
links.new(color_reroute.outputs[0], emission.inputs["Color"])
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 1
scene.render.bake.margin = 0
scene.render.bake.use_clear = True
report = {"blender": bpy.app.version_string, "reference": "Cycles emission bake", "checks": []}


def compare(label):
    nodes.active = target_node
    links.new(emission.outputs[0], output.inputs["Surface"])
    assert bpy.ops.object.bake(type="EMIT") == {"FINISHED"}
    baked = list(target.pixels)
    links.new(shader.outputs[0], output.inputs["Surface"])
    sources, grid, _ = extract_sources([plane], bpy.context.evaluated_depsgraph_get(), (16, 16, 16))
    sampler = ColorSampler(sources)
    max_error = 0
    for x, y in ((2, 3), (5, 6), (9, 11), (13, 4), (7, 12)):
        u, v = (x + 0.5) / 16, (y + 0.5) / 16
        point = grid.point((2 * u - 1, 0, 1 - 2 * v))
        actual = sampler.sample(point)
        offset = 4 * (y * 16 + x)
        expected = rgb_from_linear(baked[offset : offset + 3])
        error = max(abs(a - b) for a, b in zip(actual, expected))
        assert error <= 2, (label, (u, v), actual, expected, error)
        max_error = max(max_error, error)
    report["checks"].append({"case": label, "max_rgb_error": max_error})


adjust.inputs["Value"].default_value = 2
texture.interpolation = "Closest"
compare("UV -> Point Mapping -> reroute -> image -> HSV Value 2")
texture.interpolation = "Linear"
compare("Linear texture filtering with Value 2")
adjust.inputs["Hue"].default_value = 0.7
adjust.inputs["Saturation"].default_value = 0.6
adjust.inputs["Value"].default_value = 0.8
adjust.inputs["Fac"].default_value = 0.35
compare("Hue, saturation, value and partial factor")
mapping.inputs["Location"].default_value = (0.2, -0.3, 0)
mapping.inputs["Rotation"].default_value = (0, 0, math.pi / 3)
mapping.inputs["Scale"].default_value = (1.4, 0.7, 1)
compare("Translated, rotated and scaled UVs with repeat")
adjust.inputs["Fac"].default_value = 0
compare("Zero adjustment factor")
adjust.mute = True
mapping.mute = True
compare("Muted color and mapping nodes")
adjust.mute = False
mapping.mute = False

# Unsupported dynamic controls must fail clearly instead of silently losing color.
value = nodes.new("ShaderNodeValue")
control_link = links.new(value.outputs[0], adjust.inputs["Value"])
sources, _, _ = extract_sources([plane], bpy.context.evaluated_depsgraph_get(), (16, 16, 16))
try:
    ColorSampler(sources)
    raise AssertionError("Linked HSV controls accepted")
except ValueError as exc:
    assert "linked Hue/Saturation/Value controls" in str(exc), str(exc)
links.remove(control_link)

# Exercise the real user-facing conversion with this material on a closed mesh.
plane.select_set(False)
bpy.ops.mesh.primitive_cube_add()
cube = bpy.context.object
cube.data.materials.append(material)
p = scene.minecraft_builder
p.target_version = "26.1.2"
p.width = p.height = p.depth = 8
p.color_mode = "MATERIAL"
assert bpy.ops.minecraft_builder.capture() == {"FINISHED"}
assert bpy.ops.minecraft_builder.generate() == {"FINISHED"}, p.status
build = ui.snapshot(p)
assert len(build["cells"]) == 296
assert len(build["palette"]) > 1
report["generated_blocks"] = len(build["cells"])
report["palette_states"] = len(build["palette"])
(OUT / "blender-material-nodes.json").write_text(json.dumps(report, indent=2))
print("MATERIAL_NODES_PASS", json.dumps(report))
