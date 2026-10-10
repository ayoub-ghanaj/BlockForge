"""Packed optional texture atlases for both generated and edited preview meshes."""

import hashlib
import json
import math
import tempfile
from functools import lru_cache
from pathlib import Path

import bpy
import numpy as np
from bpy.props import EnumProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from .core import texture_pack

TILE = 18  # 16 texture pixels plus a duplicated one-pixel border.
MAX_STATES = 2048


def read_png(data):
    with tempfile.TemporaryDirectory(prefix="minecraft-builder-texture-") as directory:
        path = Path(directory) / "texture.png"
        path.write_bytes(data)
        image = bpy.data.images.load(str(path), check_existing=False)
        try:
            w, h = image.size
            pixels = np.empty(w * h * 4, np.float32)
            image.pixels.foreach_get(pixels)
            return pixels.reshape(h, w, 4)[::-1].copy()
        finally:
            bpy.data.images.remove(image)


def atlas(options, states, materials):
    """Reuse packed tiles after reopening a .blend, even if the ZIP was moved."""
    epoch = options.texture_stamp + "|" + options.target_version
    old = options.texture_atlas
    if old and old.get("mb_texture_epoch") != epoch:
        old = None
    old_states = json.loads(old.get("mb_texture_states", "[]")) if old else []
    ordered = old_states + sorted(set(states) - set(old_states))
    if len(ordered) > MAX_STATES:
        raise ValueError(
            "Textured preview supports 2,048 used states; use the color preview for this palette"
        )
    if old and len(ordered) == len(old_states):
        return old, False
    mapping = texture_pack.metadata()["profiles"].get(options.target_version, {})
    recipes = texture_pack.metadata()["recipes"]
    old_pixels = None
    if old:
        old_pixels = np.empty(old.size[0] * old.size[1] * 4, np.float32)
        old.pixels.foreach_get(old_pixels)
        old_pixels = old_pixels.reshape(old.size[1], old.size[0], 4)[::-1]
    columns = max(1, math.ceil(math.sqrt(len(ordered) * 6)))
    rows = math.ceil(len(ordered) * 6 / columns)
    pixels = np.zeros((rows * TILE, columns * TILE, 4), np.float32)
    missing = set(json.loads(old.get("mb_texture_missing", "[]"))) if old else set()
    source = None
    source_error = ""
    try:
        source = texture_pack.Archive(bpy.path.abspath(options.texture_source))
        stat = Path(bpy.path.abspath(options.texture_source)).stat()
        if options.texture_file_info != f"{stat.st_size}:{stat.st_mtime_ns}":
            raise ValueError("The texture archive changed; import it again")

        @lru_cache(maxsize=512)
        def read(texture):
            data, meta = source.png(texture)
            pixels = texture_pack.first_frame(read_png(data), meta)
            # Preview tiles are 16 px. Keep at most 64 px per texture axis in
            # the cache so an HD pack cannot retain hundreds of huge buffers.
            h, w = pixels.shape[:2]
            if h > 64 or w > 64:
                y = np.minimum(h - 1, ((np.arange(min(h, 64)) + 0.5) * h / min(h, 64)).astype(int))
                x = np.minimum(w - 1, ((np.arange(min(w, 64)) + 0.5) * w / min(w, 64)).astype(int))
                pixels = pixels[y[:, None], x[None, :]].copy()
            return pixels
    except (OSError, ValueError, RuntimeError) as error:
        source_error = str(error)

        def read(texture):
            raise KeyError(texture)

    try:
        for index, state in enumerate(ordered):
            if state in old_states:
                before = old_states.index(state)
                old_columns = old.size[0] // TILE
                tiles = []
                for side in range(6):
                    y, x = divmod(before * 6 + side, old_columns)
                    tiles.append(
                        old_pixels[y * TILE + 1 : y * TILE + 17, x * TILE + 1 : x * TILE + 17]
                    )
            else:
                color = materials[state][0]
                if state in mapping:
                    tiles, absent = texture_pack.render(recipes[mapping[state]], read, color)
                    missing.update(absent)
                else:
                    tiles = np.empty((6, 16, 16, 4), np.float32)
                    tiles[:] = tuple(c / 255 for c in color) + (1,)
                    missing.add("No texture recipe: " + state)
            for side, tile in enumerate(tiles):
                y, x = divmod(index * 6 + side, columns)
                pixels[y * TILE : (y + 1) * TILE, x * TILE : (x + 1) * TILE] = np.pad(
                    tile, ((1, 1), (1, 1), (0, 0)), mode="edge"
                )
    finally:
        if source:
            source.close()
    image = bpy.data.images.new(
        "Minecraft texture preview", width=pixels.shape[1], height=pixels.shape[0], alpha=True
    )
    image.colorspace_settings.name = "sRGB"
    image.pixels.foreach_set(np.ascontiguousarray(pixels[::-1]).ravel())
    image.update()
    image.pack()
    image["mb_texture_epoch"] = epoch
    image["mb_texture_states"] = json.dumps(ordered)
    image["mb_texture_missing"] = json.dumps(sorted(missing))
    options.texture_atlas = image
    if not options.texture_material:
        options.texture_material = bpy.data.materials.new("Minecraft textured preview")
    material = options.texture_material
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image
    tex.interpolation = "Closest"
    tex.extension = "EXTEND"
    shader.inputs["Roughness"].default_value = 1
    material.node_tree.links.new(tex.outputs["Color"], shader.inputs["Base Color"])
    material.node_tree.links.new(tex.outputs["Alpha"], shader.inputs["Alpha"])
    material.node_tree.links.new(shader.outputs["BSDF"], out.inputs["Surface"])
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "DITHERED"
    else:
        material.blend_method = "BLEND"
    options.texture_status = f"{len(ordered):,} textured states; {len(missing):,} missing texture/recipe references use color fallback"
    if source_error:
        options.texture_status += "; source unavailable — kept packed tiles"
    if old and old != image and not old.users:
        bpy.data.images.remove(old)
    return image, True


def apply_mesh(obj, options, target, cells, materials, textured):
    mesh = obj.data
    n = len(mesh.polygons)
    if not n:
        return
    centers = np.empty(n * 3, np.float32)
    normals = np.empty(n * 3, np.float32)
    mesh.polygons.foreach_get("center", centers)
    mesh.polygons.foreach_get("normal", normals)
    centers = centers.reshape(-1, 3)[:, [0, 2, 1]] * np.array([1, 1, -1])
    normals = normals.reshape(-1, 3)[:, [0, 2, 1]] * np.array([1, 1, -1])
    if target == "PERIMETER":
        centers += 1
    positions = np.floor(centers - normals * 1e-4).astype(int)
    states = [cells.get(tuple(pos)) for pos in positions]
    if any(s is None for s in states):
        raise ValueError("Preview geometry no longer matches its blocks; regenerate")
    if not textured:
        from .live_edit import render_material

        unique = list(dict.fromkeys(states))
        indices = {s: i for i, s in enumerate(unique)}
        mesh.materials.clear()
        for state in unique:
            mesh.materials.append(render_material(options, state, materials[state]))
        mesh.polygons.foreach_set("material_index", [indices[s] for s in states])
        return
    image = options.texture_atlas
    ordered = json.loads(image["mb_texture_states"])
    indices = {s: i for i, s in enumerate(ordered)}
    columns = image.size[0] // TILE
    coords = np.empty(len(mesh.vertices) * 3, np.float32)
    mesh.vertices.foreach_get("co", coords)
    coords = coords.reshape(-1, 3)[:, [0, 2, 1]] * np.array([1, 1, -1])
    if target == "PERIMETER":
        coords += 1
    loops = np.empty(len(mesh.loops), np.int32)
    mesh.loops.foreach_get("vertex_index", loops)
    starts = np.empty(n, np.int32)
    counts = np.empty(n, np.int32)
    mesh.polygons.foreach_get("loop_start", starts)
    mesh.polygons.foreach_get("loop_total", counts)
    face_ids = np.repeat(np.arange(n), counts)
    local = (coords[loops] - positions[face_ids]) * 16
    faces = np.abs(normals).argmax(axis=1) * 2 + (
        normals[np.arange(n), np.abs(normals).argmax(axis=1)] > 0
    )
    side_names = ("west", "east", "down", "up", "north", "south")
    uv = np.empty((len(loops), 2), np.float32)
    for direction, side in enumerate(side_names):
        selected = np.flatnonzero(faces[face_ids] == direction)
        if not len(selected):
            continue
        u, v = texture_pack.project(side, local[selected])
        side_index = texture_pack.SIDES.index(side)
        slots = np.array([indices[states[i]] * 6 + side_index for i in face_ids[selected]])
        uv[selected, 0] = ((slots % columns) * TILE + 1 + u) / image.size[0]
        uv[selected, 1] = 1 - ((slots // columns) * TILE + 1 + v) / image.size[1]
    layer = mesh.uv_layers.get("Minecraft block textures") or mesh.uv_layers.new(
        name="Minecraft block textures"
    )
    layer.data.foreach_set("uv", uv.ravel())
    mesh.uv_layers.active = layer
    mesh.materials.clear()
    mesh.materials.append(options.texture_material)
    mesh.polygons.foreach_set("material_index", np.zeros(n, np.int32))
    mesh.update()


def refresh(context, options, target, editor=None, objects=None):
    from .live_edit import root_object, session

    root = root_object(context, options, target)
    if not root:
        return
    if editor is None:
        editor = session(context, options, target)
    rebuilt = False
    if options.texture_preview:
        if not options.texture_source and not options.texture_atlas:
            raise ValueError("Import a texture/resource ZIP first")
        _, rebuilt = atlas(options, set(editor.cells.values()), editor.materials)
    meshes = [root, *root.children] if objects is None or rebuilt else objects
    for obj in meshes:
        if obj.type == "MESH" and not obj.get("mb_protection_overlay"):
            apply_mesh(
                obj, options, target, editor.cells, editor.materials, options.texture_preview
            )


class MB_OT_texture_import(bpy.types.Operator, ImportHelper):
    bl_idname = "minecraft_builder.import_textures"
    bl_label = "Import Preview Textures"
    bl_description = "Read only the ZIP/JAR you select. Textures affect display; color matching uses the selected palette"
    filter_glob: StringProperty(default="*.zip;*.jar", options={"HIDDEN"})
    target: EnumProperty(items=[("MODEL", "Model", ""), ("PERIMETER", "Perimeter", "")])

    def execute(self, context):
        from .ui import palette_settings

        options = palette_settings(context, self.target)
        try:
            path = Path(self.filepath)
            if path.stat().st_size > 512 * 1024 * 1024:
                raise ValueError("Choose an archive smaller than 512 MiB")
            archive = texture_pack.Archive(path)
            archive.close()
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            stat = path.stat()
            options.texture_source = str(path)
            options.texture_stamp = digest
            options.texture_file_info = f"{stat.st_size}:{stat.st_mtime_ns}"
            previous = options.texture_atlas
            options.texture_atlas = None
            options.texture_preview = True
            if options.snapshot:
                refresh(context, options, self.target)
            else:
                options.texture_status = "Textures selected; generate a preview to display them"
            if previous and not previous.users:
                bpy.data.images.remove(previous)
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class MB_OT_texture_refresh(bpy.types.Operator):
    bl_idname = "minecraft_builder.refresh_textures"
    bl_label = "Apply Preview Display"
    target: EnumProperty(items=[("MODEL", "Model", ""), ("PERIMETER", "Perimeter", "")])

    def execute(self, context):
        from .ui import palette_settings

        try:
            refresh(context, palette_settings(context, self.target), self.target)
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


def draw(box, options, target):
    box = box.box()
    box.label(text="Preview appearance")
    box.prop(options, "texture_preview")
    box.operator("minecraft_builder.import_textures", icon="FILE_FOLDER").target = target
    if options.snapshot:
        box.operator("minecraft_builder.refresh_textures", icon="FILE_REFRESH").target = target
    if options.texture_preview:
        box.label(text="Use Material Preview shading: Z, M.")
        box.label(text="Pack textures; vanilla shape / first frame.")
        box.label(text="Matching still uses your selected color palette.")
        if options.texture_status:
            box.label(text=options.texture_status)


CLASSES = (MB_OT_texture_import, MB_OT_texture_refresh)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
