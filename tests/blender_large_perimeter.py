"""Generate the requested 650 x 400 image floor through actual Blender operators."""

import json
import sys
import time
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import minecraft_builder
from minecraft_builder import live_edit
from minecraft_builder.perimeter import ui

OUT = ROOT / "build/perimeter"
minecraft_builder.register()
p = bpy.context.scene.minecraft_perimeter
p.target_version = "26.1.2"
p.project_kind = "FLOOR"
p.floor.image = bpy.data.images.load(str(OUT / "floor-650x400.png"))
assert bpy.ops.minecraft_perimeter.image_size() == {"FINISHED"}
assert (p.width, p.depth) == (650, 400)
p.search = r"minecraft:(black|white|cyan|blue|orange)_concrete$"
p.regex_search = True
bpy.ops.minecraft_builder.only_blocks(target="PERIMETER", scope="FILTERED")
start = time.monotonic()
assert bpy.ops.minecraft_perimeter.generate() == {"FINISHED"}, p.status
build = ui.snapshot(p)
assert build["size"] == [650, 2, 400] and len(build["cells"]) == 520000
reference = json.loads((OUT / "floor_650x400_glass.json").read_text())


def states(b):
    return {(x, y, z): b["palette"][i] for x, y, z, i in b["cells"]}


assert states(build) == states(reference), (
    "Loaded PNG or UI conversion differs from the core reference"
)
preview = next(
    o
    for o in bpy.context.scene.objects
    if o.get("minecraft_perimeter_generated") == p.preview_token
)
assert tuple(preview.scale) == (1, 1, 1)
assert tuple(round(v, 4) for v in preview.dimensions) == (650, 400, 1)
report = {
    "status": "passed",
    "blender": bpy.app.version_string,
    "size": build["size"],
    "blocks": len(build["cells"]),
    "preview_quads": len(preview.data.polygons),
    "seconds": round(time.monotonic() - start, 2),
    "checks": [
        "650x400 PNG loaded through Blender matches every reference block",
        "Use image size",
        "one-meter preview",
        "glass coverage",
    ],
}
start = time.monotonic()
assert bpy.ops.minecraft_builder.edit_start(target="PERIMETER") == {"FINISHED"}
report["edit_prepare_seconds"] = round(time.monotonic() - start, 2)
sections = {
    tuple(o["mb_edit_chunk_key"]): o.as_pointer()
    for o in preview.children
    if "mb_edit_chunk_key" in o
}
p.edit_position = (10, 0, 10)
p.edit_brush = "minecraft:white_concrete"
start = time.monotonic()
assert bpy.ops.minecraft_builder.edit_action(target="PERIMETER", action="REPLACE") == {
    "FINISHED"
}, p.status
report["single_edit_seconds"] = round(time.monotonic() - start, 3)
after = {
    tuple(o["mb_edit_chunk_key"]): o.as_pointer()
    for o in preview.children
    if "mb_edit_chunk_key" in o
}
report["sections_untouched"] = sum(after.get(k) == v for k, v in sections.items())
report["sections_total"] = len(sections)
report["sections_rebuilt"] = p.edit_last_chunks
assert report["sections_untouched"] >= len(sections) - 4
assert live_edit.session(bpy.context, p, "PERIMETER").cells[10, 0, 10] == "minecraft:white_concrete"
report["checks"].append(
    "One block edited in 520000-block preview; unaffected section objects preserved"
)
p.edit_selection_a = (1, 0, 1)
p.edit_selection_b = (64, 0, 64)
p.edit_brush = "minecraft:blue_concrete"
start = time.monotonic()
assert bpy.ops.minecraft_builder.bulk_edit(target="PERIMETER", action="FILL") == {"FINISHED"}, (
    p.status
)
report["bulk_4096_seconds"] = round(time.monotonic() - start, 3)
assert all(
    live_edit.session(bpy.context, p, "PERIMETER").cells[x, 0, z] == "minecraft:blue_concrete"
    for x in range(1, 65)
    for z in range(1, 65)
)
assert len(live_edit.document(p)["undo"][-1]) == 4096
assert bpy.ops.minecraft_builder.edit_action(target="PERIMETER", action="UNDO") == {"FINISHED"}
assert live_edit.session(bpy.context, p, "PERIMETER").cells[10, 0, 10] == "minecraft:white_concrete"
report["checks"].append("4096-block fill is one saved Undo step inside the 520000-block perimeter")
(OUT / "blender-large-perimeter.json").write_text(json.dumps(report, indent=2))
print("BLENDER_LARGE_PERIMETER_PASS", json.dumps(report))
