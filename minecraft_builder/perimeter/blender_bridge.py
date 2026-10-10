"""Blender image/decor adapters and a compact surface preview for perimeters."""

import bpy
import numpy as np

from ..blender_mesh import ColorSampler, extract_sources, preview_mesh
from ..core.palette import linear
from ..core.shapes import split_state
from ..core.volume import convert
from .covers import boxes
from .layout import FACES, face_position, face_size
from .materials import emission, is_glass


def image_pixels(image):
    width, height = image.size
    if width < 1 or height < 1:
        raise ValueError("Image has no pixels: " + image.name)
    if width * height > 32_000_000:
        raise ValueError("Images are limited to 32 million source pixels; resize this image first")
    values = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(values)
    values = values.reshape(height, width, 4)[::-1].copy()
    if image.colorspace_settings.name in ("Linear", "Linear Rec.709", "Linear Rec.2020", "ACEScg"):
        rgb = values[:, :, :3]
        values[:, :, :3] = np.where(
            rgb <= 0.0031308, 12.92 * rgb, 1.055 * np.maximum(rgb, 0) ** (1 / 2.4) - 0.055
        )
    return np.rint(values * 255).clip(0, 255).astype(np.uint8)


def decorate(context, settings, blocks):
    results = []
    objects = [s.object for s in settings.sources if s.object]
    for index, obj in enumerate(objects):
        sources, grid, _ = extract_sources(
            [obj],
            context.evaluated_depsgraph_get(),
            (512, 512, 512),
            unit_grid=True,
            world_scale=context.scene.unit_settings.scale_length,
        )
        sampler = ColorSampler(sources)
        for stage, value in convert(
            sources,
            grid.size,
            blocks,
            sampler.sample,
            settings.hollow,
            settings.thickness,
            settings.shape_weight,
            face_matching=settings.face_matching,
        ):
            if stage == "result":
                results.append((value, grid.origin))
            else:
                yield "Decoration: " + obj.name, (index + value) / max(1, len(objects))
    yield "result", results


def remove_generated(token):
    if not token:
        return
    for obj in list(bpy.data.objects):
        if obj.get("minecraft_perimeter_generated") == token or obj.get("mb_edit_preview") == token:
            mesh = obj.data if obj.type == "MESH" else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh and not mesh.users:
                bpy.data.meshes.remove(mesh)
    for collection in list(bpy.data.collections):
        if collection.get("minecraft_perimeter_generated") == token and not collection.objects:
            bpy.data.collections.remove(collection)
    for material in list(bpy.data.materials):
        if (
            material.get("minecraft_perimeter_generated") == token
            or material.get("mb_edit_preview") == token
        ) and not material.users:
            bpy.data.materials.remove(material)


def make_preview(context, build, token, real_scale=True):
    """Show surface pixels, decoration geometry and translucent protective caps.

    Floor/wall back faces and hidden interior cube faces are omitted from this
    display mesh. Export files retain complete blocks and hollow air semantics.
    """
    info = build["perimeter"]
    width, depth, height = (info[k] for k in ("width", "depth", "height"))
    offset = info.get("origin", [0, 0, 0])
    cells = {(x, y, z): i for x, y, z, i in build["cells"]}
    vertices = []
    faces = []
    material_ids = []
    surface_positions = set()

    def quad(points, index):
        if len(faces) >= 1_500_000:
            raise ValueError("Perimeter preview is too detailed; reduce dimensions")
        start = len(vertices)
        vertices.extend((x - 1, 1 - z, y - 1) for x, y, z in points)
        faces.append((start, start + 1, start + 2, start + 3))
        material_ids.append(index)

    for face in info["faces"]:
        fw, fh = face_size(face, width, depth, height)
        for row in range(fh):
            for column in range(fw):
                x, y, z = face_position(face, column, row, width, depth, height)
                index = cells[x - offset[0], y - offset[1], z - offset[2]]
                surface_positions.add((x - offset[0], y - offset[1], z - offset[2]))
                if face == "floor":
                    points = (
                        (x, y + 1, z),
                        (x, y + 1, z + 1),
                        (x + 1, y + 1, z + 1),
                        (x + 1, y + 1, z),
                    )
                elif face == "north":
                    points = (
                        (x, y, z + 1),
                        (x + 1, y, z + 1),
                        (x + 1, y + 1, z + 1),
                        (x, y + 1, z + 1),
                    )
                elif face == "south":
                    points = ((x + 1, y, z), (x, y, z), (x, y + 1, z), (x + 1, y + 1, z))
                elif face == "west":
                    points = (
                        (x + 1, y, z + 1),
                        (x + 1, y, z),
                        (x + 1, y + 1, z),
                        (x + 1, y + 1, z + 1),
                    )
                else:
                    points = ((x, y, z), (x, y, z + 1), (x, y + 1, z + 1), (x, y + 1, z))
                quad(points, index)
        yield "Preview: " + face, 0.7 + 0.05 * FACES.index(face)
    # Glass is displayed as caps so the artwork remains easy to inspect.
    cover_state = info["protection"].get("cover_state")
    for (x, y, z), index in cells.items():
        if is_glass(build["palette"][index]) or build["palette"][index] == cover_state:
            x += offset[0]
            y += offset[1]
            z += offset[2]
            for x0, y0, z0, x1, y1, z1 in boxes(build["palette"][index]):
                quad(
                    (
                        (x + x0, y + y1, z + z0),
                        (x + x0, y + y1, z + z1),
                        (x + x1, y + y1, z + z1),
                        (x + x1, y + y1, z + z0),
                    ),
                    index,
                )
    # Include corner posts and lights added above partial shapes as well as meshes.
    deco = {
        p: i
        for p, i in cells.items()
        if p not in surface_positions
        and not is_glass(build["palette"][i])
        and build["palette"][i] != cover_state
    }
    # Bucket decorations into 16-block regions for bounded preview memory. Half
    # faces across region edges can be duplicated internally, never in exports.
    buckets = {}
    for pos, index in deco.items():
        buckets.setdefault(tuple(v // 16 for v in pos), []).append((pos, index))
    for key, entries in buckets.items():
        origin = tuple(v * 16 for v in key)
        sub = {
            "size": [16, 16, 16],
            "palette": build["palette"],
            "masks": build["masks"],
            "cells": [[*(pos[i] - origin[i] for i in range(3)), index] for pos, index in entries],
        }
        for stage, value in preview_mesh(sub):
            if stage != "result":
                continue
            verts, polys, mats = value
            base = len(vertices)
            vertices.extend(
                (
                    x + origin[0] + offset[0] - 1,
                    y - origin[2] - offset[2] + 1,
                    z + origin[1] + offset[1] - 1,
                )
                for x, y, z in verts
            )
            faces.extend(tuple(base + i for i in face) for face in polys)
            material_ids.extend(mats)
        if len(faces) > 1_500_000:
            raise ValueError(
                "Perimeter preview is too detailed; reduce decoration detail or dimensions"
            )
    mesh = bpy.data.meshes.new("Perimeter surfaces")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("Perimeter Preview", mesh)
    obj["minecraft_perimeter_generated"] = token
    collection = bpy.data.collections.new("Perimeter Preview")
    collection["minecraft_perimeter_generated"] = token
    context.scene.collection.children.link(collection)
    collection.objects.link(obj)
    for state, color in zip(build["palette"], build["colors"]):
        material = bpy.data.materials.new("Perimeter " + split_state(state)[0].split(":")[-1])
        material.use_nodes = True
        material["minecraft_perimeter_generated"] = token
        shader = material.node_tree.nodes.get("Principled BSDF")
        rgba = tuple(linear(v / 255) for v in color) + (1,)
        material.diffuse_color = rgba
        shader.inputs["Base Color"].default_value = rgba
        if is_glass(state):
            shader.inputs["Alpha"].default_value = 0.18
            material.diffuse_color = rgba[:3] + (0.18,)
            if hasattr(material, "surface_render_method"):
                material.surface_render_method = "DITHERED"
            elif hasattr(material, "blend_method"):
                material.blend_method = "BLEND"
        if emission(state):
            shader.inputs["Emission Color"].default_value = rgba
            shader.inputs["Emission Strength"].default_value = 0.5
        mesh.materials.append(material)
    mesh.polygons.foreach_set("material_index", material_ids)
    scale = (1 if real_scale else min(1, 20 / max(width, depth))) / max(
        1e-9, context.scene.unit_settings.scale_length
    )
    obj.scale = (scale,) * 3
    obj.location = ((width + 8) / context.scene.unit_settings.scale_length, 0, 0)
    obj["perimeter_preview_width"] = width
    obj["perimeter_preview_depth"] = depth
    obj["perimeter_basis"] = [v for row in obj.matrix_basis.to_3x3() for v in row]
    yield "result", obj


def create_guide(context, options):
    remove_generated(options.guide_token)
    token = options.guide_token = "perimeter-guide-" + context.scene.name
    width, depth, height = options.width, options.depth, options.height
    unit = 1 / max(1e-9, context.scene.unit_settings.scale_length)
    verts = [
        (x * unit, -z * unit, y * unit) for y in (0, height) for z in (0, depth) for x in (0, width)
    ]
    edges = [
        (0, 1),
        (1, 3),
        (3, 2),
        (2, 0),
        (4, 5),
        (5, 7),
        (7, 6),
        (6, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ]
    mesh = bpy.data.meshes.new("Perimeter Guide")
    mesh.from_pydata(verts, edges, [])
    obj = bpy.data.objects.new("Perimeter Guide — decorations inside", mesh)
    obj["minecraft_perimeter_generated"] = token
    context.scene.collection.objects.link(obj)
    obj.show_in_front = True
    obj.hide_render = True
    obj.hide_select = True
    obj.color = (0.15, 0.65, 1, 1)
    return obj
