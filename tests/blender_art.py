"""Generated artwork and dry-cover acceptance examples via the Blender UI."""

import json
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import minecraft_builder
from minecraft_builder.perimeter import covers, ui

OUT = ROOT / "build/art-tests"
OUT.mkdir(parents=True, exist_ok=True)
start = time.monotonic()
minecraft_builder.register()
scene = bpy.context.scene
p = scene.minecraft_perimeter
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
p.target_version = "26.1.2"
p.width = 16
p.depth = 10
p.height = 5
p.project_kind = "FLOOR"
report = {"blender": bpy.app.version_string, "cases": []}
cases = []


def save(name, render=False):
    build = ui.snapshot(p)
    (OUT / (name + ".json")).write_text(json.dumps(build, separators=(",", ":")))
    for fmt in ("schem", "litematic", "bp"):
        assert bpy.ops.minecraft_perimeter.export(
            filepath=str(OUT / (name + "." + fmt)), format=fmt
        ) == {"FINISHED"}
    cases.append(name)
    report["cases"].append(
        {
            "name": name,
            "size": build["size"],
            "blocks": len(build["cells"]),
            "cover": build["perimeter"]["protection"].get("cover_state"),
            "lights": build["perimeter"]["protection"]["light_blocks"],
        }
    )
    if not render:
        return
    root = next(
        o for o in scene.objects if o.get("minecraft_perimeter_generated") == p.preview_token
    )
    if scene.camera:
        bpy.data.objects.remove(scene.camera, do_unlink=True)
    center = Vector(root.location) + Vector(
        (p.width / 2, -p.depth / 2, p.height / 3 if p.project_kind != "FLOOR" else 0)
    )
    location = center + Vector((p.width * 0.38, -p.depth * 0.65, max(p.width, p.depth) * 1.0))
    if p.project_kind == "WALL":
        center = Vector(root.location) + Vector((p.width / 2, 0, p.height / 2))
        location = center + Vector((p.width * 0.1, -p.width, 0.3 * p.height))
    bpy.ops.object.camera_add(location=location)
    camera = bpy.context.object
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(p.width, p.depth) * (1.25 if p.project_kind == "WALL" else 1.75)
    scene.camera = camera
    scene.view_settings.view_transform = "Standard"
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "FLAT"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_shadows = False
    scene.display.shading.show_cavity = True
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.filepath = str(OUT / (name + ".png"))
    bpy.ops.render.render(write_still=True)
    p.step = 5
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            area.spaces.active.region_3d.view_location = center
            area.spaces.active.region_3d.view_distance = max(p.width, p.depth) * 1.6
            area.spaces.active.region_3d.view_rotation = camera.rotation_euler.to_quaternion()
            area.spaces.active.clip_end = 5000
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / (name + ".blend")))


# Every dry cover style gets a real mod-reader and spawning fixture.
for kind, _, _ in covers.KINDS:
    p.cover_kind = kind
    if kind == "GLASS":
        p.glass_material = "minecraft:cyan_stained_glass"
    if kind == "BUTTON":
        p.cover_material = "minecraft:stone_button[face=floor,facing=north,powered=false]"
    assert bpy.ops.minecraft_perimeter.generate() == {"FINISHED"}, p.status
    save("cover_" + kind.lower())

art = ROOT / "examples/perimeter-art"
p.width = 96
p.depth = 64
p.height = 12
p.cover_kind = "GLASS"
p.glass_material = "minecraft:glass"
p.floor.image = bpy.data.images.load(str(art / "cosmic-compass.png"))
p.floor.image.pack()
p.floor.fit = "STRETCH"
assert bpy.ops.minecraft_perimeter.generate() == {"FINISHED"}
save("cosmic_compass_floor", True)

p.project_kind = "WALL"
p.width = 192
p.depth = 1
p.height = 64
p.cover_kind = "BUTTON"
p.north.image = bpy.data.images.load(str(art / "floating-islands.png"))
p.north.image.pack()
p.north.fit = "FIT"
assert bpy.ops.minecraft_perimeter.generate() == {"FINISHED"}
save("floating_islands_wall", True)

p.project_kind = "PERIMETER"
p.width = 96
p.depth = 64
p.height = 12
p.cover_kind = "BUTTON"
p.protection = "BOTH"
p.light_material = "AUTO"
p.floor.image = bpy.data.images.load(str(art / "koi-pond.png"))
p.floor.image.pack()
p.floor.fit = "FILL"
for face in ("north", "south", "west", "east"):
    getattr(p, face).image = bpy.data.images["floating-islands.png"]
    getattr(p, face).fit = "FILL"
assert bpy.ops.minecraft_perimeter.generate() == {"FINISHED"}
save("koi_pond_perimeter", True)
assert len(ui.snapshot(p)["perimeter"]["protection"]["light_materials"]) > 1, (
    "Color-matched lights should use multiple materials"
)

# Explicit lights are preserved and old versions request the historical threshold.
p.project_kind = "FLOOR"
p.width = 32
p.depth = 32
p.protection = "LIGHTS"
p.light_material = "minecraft:sea_lantern"
assert bpy.ops.minecraft_perimeter.generate() == {"FINISHED"}
new = ui.snapshot(p)
assert new["perimeter"]["protection"]["light_threshold"] == 1
assert set(new["perimeter"]["protection"]["light_materials"]) == {"minecraft:sea_lantern"}
save("sea_lantern_modern")
p.target_version = "1.17"
assert p.light_material == "minecraft:sea_lantern"
assert bpy.ops.minecraft_perimeter.generate() == {"FINISHED"}
old = ui.snapshot(p)
assert old["perimeter"]["protection"]["light_threshold"] == 8
assert (
    new["perimeter"]["protection"]["light_blocks"] < old["perimeter"]["protection"]["light_blocks"]
)
report["version_lighting"] = {
    "modern_lights": new["perimeter"]["protection"]["light_blocks"],
    "old_lights": old["perimeter"]["protection"]["light_blocks"],
}
report.update(status="passed", seconds=round(time.monotonic() - start, 2))
(OUT / "cases.json").write_text(json.dumps(cases))
(OUT / "blender-art-tests.json").write_text(json.dumps(report, indent=2))
print("BLENDER_ART_TESTS_PASS", json.dumps(report))
