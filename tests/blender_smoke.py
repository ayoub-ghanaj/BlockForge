"""Run with Blender --background --factory-startup --python this_file."""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy

import minecraft_builder
from minecraft_builder import ui

OUT = ROOT / "build" / "verification"
OUT.mkdir(parents=True, exist_ok=True)
start = time.monotonic()
minecraft_builder.register()
p = bpy.context.scene.minecraft_builder
p.target_version = "26.1.2"
assert len(p.blocks) > 450, len(p.blocks)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_cube_add(size=2)
source = bpy.context.object
source.name = "Smoke source cube"
mat = bpy.data.materials.new("Red source")
mat.use_nodes = True
mat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (
    0.65,
    0.03,
    0.015,
    1,
)
source.data.materials.append(mat)
p.width = p.height = p.depth = 8
p.hollow = True
assert bpy.ops.minecraft_builder.capture() == {"FINISHED"}
assert bpy.ops.minecraft_builder.generate() == {"FINISHED"}, p.status
build = ui.snapshot(p)
assert build["size"] == [8, 8, 8], build["size"]
assert len(build["cells"]) == 8**3 - 6**3, len(build["cells"])
assert source.name in bpy.data.objects
for kind in ("schem", "litematic", "bp"):
    assert bpy.ops.minecraft_builder.export(
        filepath=str(OUT / ("cube_hollow." + kind)), format=kind
    ) == {"FINISHED"}
(OUT / "cube_hollow.json").write_text(json.dumps(build), encoding="utf-8")
p.hollow = False
assert bpy.ops.minecraft_builder.generate() == {"FINISHED"}, p.status
solid = ui.snapshot(p)
assert len(solid["cells"]) == 512, len(solid["cells"])
assert len([o for o in bpy.data.objects if o.get("minecraft_builder_preview")]) == 1
assert source.name in bpy.data.objects
report = {
    "blender": bpy.app.version_string,
    "preset": p.target_version,
    "palette_entries": len(p.blocks),
    "hollow_blocks": len(build["cells"]),
    "solid_blocks": len(solid["cells"]),
    "seconds": round(time.monotonic() - start, 2),
}
(OUT / "blender-smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print("BLENDER_SMOKE_PASS", json.dumps(report))
minecraft_builder.unregister()
