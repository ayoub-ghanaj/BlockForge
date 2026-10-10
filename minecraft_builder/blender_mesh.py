"""Blender evaluated-mesh extraction, UV sampling, and compact block previews."""

import math

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from .core.geometry import MAX_CELLS, Grid, closest_barycentric, fit_grid
from .core.palette import linear, srgb

MAX_TRIANGLES = 8_000_000
MAX_PREVIEW_FACES = 1_200_000


def extract_sources(
    objects, depsgraph, limits, preserve=True, model_up="Z", unit_grid=False, world_scale=1.0
):
    sources = []
    bounds = []
    total = 0
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
        try:
            mesh.calc_loop_triangles()
            count = len(mesh.loop_triangles)
            total += count
            if total > MAX_TRIANGLES:
                raise ValueError(
                    "Source exceeds 8 million triangles. Use a Decimate modifier or a lower-detail model."
                )
            if not count:
                continue
            vertices = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
            mesh.vertices.foreach_get("co", vertices)
            matrix = np.array(obj.matrix_world, dtype=np.float64)
            vertices = (
                vertices.reshape((-1, 3)).astype(np.float64) @ matrix[:3, :3].T + matrix[:3, 3]
            )
            vertices *= world_scale
            # Proper rotations only: the chosen source axis becomes Minecraft +Y.
            axes, signs = {
                "Z": ((0, 2, 1), (1, 1, -1)),
                "NEG_Z": ((0, 2, 1), (1, -1, 1)),
                "Y": ((0, 1, 2), (1, 1, 1)),
                "NEG_Y": ((0, 1, 2), (1, -1, -1)),
                "X": ((1, 0, 2), (-1, 1, 1)),
                "NEG_X": ((1, 0, 2), (1, -1, 1)),
            }[model_up]
            vertices = vertices[:, axes] * np.array(signs)
            if not np.isfinite(vertices).all():
                raise ValueError("The model has invalid vertex coordinates")
            triangles = np.empty(count * 3, dtype=np.int32)
            mesh.loop_triangles.foreach_get("vertices", triangles)
            triangles = triangles.reshape((-1, 3))
            loops = np.empty(count * 3, dtype=np.int32)
            mesh.loop_triangles.foreach_get("loops", loops)
            loops = loops.reshape((-1, 3))
            material_indices = np.empty(count, dtype=np.int32)
            mesh.loop_triangles.foreach_get("material_index", material_indices)
            uv_layers = {}
            for layer in mesh.uv_layers:
                values = np.empty(len(mesh.loops) * 2, dtype=np.float32)
                layer.data.foreach_get("uv", values)
                uv_layers[layer.name] = values.reshape((-1, 2))
            attributes = {}
            for attr in mesh.color_attributes:
                values = np.empty(len(attr.data) * 4, dtype=np.float32)
                attr.data.foreach_get("color", values)
                attributes[attr.name] = (attr.domain, values.reshape((-1, 4)))
            sources.append(
                {
                    "name": obj.name,
                    "vertices": vertices,
                    "triangles": triangles,
                    "loops": loops,
                    "materials": list(mesh.materials),
                    "material_indices": material_indices,
                    "uv_layers": uv_layers,
                    "active_uv": mesh.uv_layers.active.name if mesh.uv_layers.active else "",
                    "attributes": attributes,
                    "active_color": mesh.color_attributes.active_color_name,
                }
            )
            bounds.extend((vertices.min(axis=0), vertices.max(axis=0)))
        finally:
            evaluated.to_mesh_clear()
    if not sources:
        raise ValueError("Select at least one mesh containing faces")
    if unit_grid:
        low = np.floor(np.min(bounds, axis=0) + 1e-6).astype(int)
        high = np.ceil(np.max(bounds, axis=0) - 1e-6).astype(int)
        size = tuple(int(v) for v in np.maximum(1, high - low))
        if max(size) > 512 or math.prod(size) > MAX_CELLS:
            raise ValueError(
                "One decoration exceeds 512 blocks per axis or two million bounding cells; scale it down or split it into pieces"
            )
        grid = Grid(tuple(int(v) for v in low), (1, 1, 1), size)
    else:
        grid = fit_grid(bounds, limits, preserve)
    for source in sources:
        source["vertices"] = (source["vertices"] - np.array(grid.origin)) * np.array(grid.scale)
        source["bvh"] = BVHTree.FromPolygons(
            source["vertices"], source["triangles"], all_triangles=True, epsilon=0.0
        )
    return sources, grid, total


def rgb_from_linear(values):
    return tuple(max(0, min(255, round(255 * srgb(float(v))))) for v in values[:3])


class ColorSampler:
    def __init__(self, sources):
        self.sources = sources
        self.materials = {}
        self.images = {}
        # Resolve graphs once and reject unsupported color chains explicitly.
        for source in sources:
            for material in source["materials"]:
                if material and material.name not in self.materials:
                    self.materials[material.name] = self.resolve_material(material)

    def resolve_material(self, material):
        if not material.use_nodes or not material.node_tree:
            return ("flat", rgb_from_linear(material.diffuse_color))
        outputs = [
            n
            for n in material.node_tree.nodes
            if n.type == "OUTPUT_MATERIAL" and n.is_active_output
        ]
        if not outputs or not outputs[0].inputs["Surface"].is_linked:
            return ("flat", rgb_from_linear(material.diffuse_color))
        node = outputs[0].inputs["Surface"].links[0].from_node
        if node.type != "BSDF_PRINCIPLED":
            raise ValueError(
                f"{material.name}: use a Principled BSDF or bake the material to a base-color texture"
            )
        socket = node.inputs["Base Color"]
        if not socket.is_linked:
            return ("flat", rgb_from_linear(socket.default_value))
        node = socket.links[0].from_node
        while node.type == "REROUTE":
            node = node.inputs[0].links[0].from_node
        if node.type == "RGB":
            return ("flat", rgb_from_linear(node.outputs[0].default_value))
        if node.type in ("VERTEX_COLOR", "ATTRIBUTE"):
            return ("attribute", getattr(node, "layer_name", getattr(node, "attribute_name", "")))
        if node.type != "TEX_IMAGE" or node.image is None:
            raise ValueError(
                f"{material.name}: bake the Base Color node chain to an image texture before converting"
            )
        if node.projection != "FLAT":
            raise ValueError(f"{material.name}: use UV image mapping or bake the material")
        uv_name = ""
        if node.inputs["Vector"].is_linked:
            uv_node = node.inputs["Vector"].links[0].from_node
            if uv_node.type == "UVMAP":
                uv_name = uv_node.uv_map
            elif (
                uv_node.type == "TEX_COORD"
                and node.inputs["Vector"].links[0].from_socket.name == "UV"
            ):
                pass
            else:
                raise ValueError(
                    f"{material.name}: bake Mapping/procedural coordinates to a UV texture"
                )
        image = node.image
        if image.source in ("TILED", "SEQUENCE", "MOVIE"):
            raise ValueError(f"{material.name}: bake tiled or animated images into one UV image")
        if image.name not in self.images:
            width, height = image.size
            if width <= 0 or height <= 0:
                raise ValueError(f"Missing texture image: {image.name}")
            pixels = np.empty(width * height * 4, dtype=np.float32)
            image.pixels.foreach_get(pixels)
            self.images[image.name] = (
                pixels.reshape((height, width, 4)),
                image.colorspace_settings.name,
                image.is_float,
            )
        return ("image", image.name, uv_name, node.extension, node.interpolation)

    def sample(self, point):
        p = Vector(point)
        best = None
        for source in self.sources:
            hit, normal, index, distance = source["bvh"].find_nearest(p)
            if hit is not None and (best is None or distance < best[0]):
                best = (distance, source, index, hit)
        if best is None:
            return (180, 180, 180)
        _, source, index, hit = best
        material_id = int(source["material_indices"][index])
        material = (
            source["materials"][material_id] if material_id < len(source["materials"]) else None
        )
        spec = self.materials[material.name] if material else ("flat", (180, 180, 180))
        if spec[0] == "flat":
            return spec[1]
        vertex_ids = source["triangles"][index]
        _, weights = closest_barycentric(tuple(hit), source["vertices"][vertex_ids])
        if spec[0] == "attribute":
            name = spec[1] or source["active_color"]
            if name not in source["attributes"]:
                raise ValueError("Missing color attribute: " + name)
            domain, values = source["attributes"][name]
            ids = vertex_ids if domain == "POINT" else source["loops"][index]
            return rgb_from_linear(np.asarray(weights) @ values[ids, :3])
        _, name, uv_name, extension, interpolation = spec
        uv_name = uv_name or source["active_uv"]
        if uv_name not in source["uv_layers"]:
            raise ValueError("Image-textured meshes need a UV map: " + source["name"])
        uv = np.asarray(weights) @ source["uv_layers"][uv_name][source["loops"][index]]
        pixels, colorspace, is_float = self.images[name]
        height, width, _ = pixels.shape
        if extension == "REPEAT":
            uv = uv - np.floor(uv)
        elif extension == "MIRROR":
            uv = 1 - np.abs((uv % 2) - 1)
        elif extension == "CLIP" and (np.any(uv < 0) or np.any(uv > 1)):
            return (0, 0, 0)
        uv = np.clip(uv, 0, 1)
        if interpolation == "Closest":
            rgb = pixels[
                min(height - 1, int(uv[1] * height)), min(width - 1, int(uv[0] * width)), :3
            ]
        else:
            fx, fy = uv * np.array([width, height]) - 0.5
            x0, y0 = math.floor(fx), math.floor(fy)
            tx, ty = fx - x0, fy - y0

            def at(x, y):
                return (
                    pixels[y % height, x % width, :3]
                    if extension == "REPEAT"
                    else pixels[max(0, min(height - 1, y)), max(0, min(width - 1, x)), :3]
                )

            rgb = (1 - ty) * ((1 - tx) * at(x0, y0) + tx * at(x0 + 1, y0)) + ty * (
                (1 - tx) * at(x0, y0 + 1) + tx * at(x0 + 1, y0 + 1)
            )
        # Byte image buffers are exposed as normalized source values. Float
        # image buffers in scene-linear spaces need display conversion.
        if colorspace in ("Linear", "Linear Rec.709", "Linear Rec.2020", "ACEScg"):
            return rgb_from_linear(rgb)
        return tuple(max(0, min(255, round(float(c) * 255))) for c in rgb)


FACE_CORNERS = (
    ((-1, 0, 0), ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0))),
    ((1, 0, 0), ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1))),
    ((0, -1, 0), ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1))),
    ((0, 1, 0), ((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0))),
    ((0, 0, -1), ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0))),
    ((0, 0, 1), ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))),
)


def preview_mesh(build):
    fine = np.full(tuple(v * 2 for v in build["size"]), -1, dtype=np.int32)
    for x, y, z, index in build["cells"]:
        mask = build["masks"][index]
        for oy in range(2):
            for oz in range(2):
                for ox in range(2):
                    if mask & (1 << (ox + 2 * oz + 4 * oy)):
                        fine[x * 2 + ox, y * 2 + oy, z * 2 + oz] = index
    occupied = fine >= 0
    vertices = []
    faces = []
    material_ids = []
    for axis_face, (delta, corners) in enumerate(FACE_CORNERS):
        neighbor = np.roll(occupied, tuple(-d for d in delta), axis=(0, 1, 2))
        axis = next(i for i, d in enumerate(delta) if d)
        boundary = [slice(None)] * 3
        boundary[axis] = -1 if delta[axis] > 0 else 0
        neighbor[tuple(boundary)] = False
        coords = np.argwhere(occupied & ~neighbor)
        if len(faces) + len(coords) > MAX_PREVIEW_FACES:
            raise ValueError("Preview exceeds 1.2 million faces; reduce the target dimensions")
        for x, y, z in coords:
            start = len(vertices)
            for ox, oy, oz in corners:
                # Rotate Minecraft Y-up into Blender Z-up; positive determinant.
                vertices.append(((int(x) + ox) / 2, -(int(z) + oz) / 2, (int(y) + oy) / 2))
            faces.append((start, start + 1, start + 2, start + 3))
            material_ids.append(int(fine[x, y, z]))
        yield "Building preview", 0.95 + 0.045 * (axis_face + 1) / 6
    yield "result", (vertices, faces, material_ids)


def install_preview(context, build, mesh_data, grid, token):
    vertices, faces, material_ids = mesh_data
    mesh = bpy.data.meshes.new("Minecraft Blocks")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("Minecraft Preview", mesh)
    obj["minecraft_builder_preview"] = token
    collection = bpy.data.collections.new("Minecraft Builder Preview")
    collection["minecraft_builder_preview"] = token
    context.scene.collection.children.link(collection)
    collection.objects.link(obj)
    mats = {}
    for color in build["colors"]:
        key = tuple(color)
        if key not in mats:
            mat = bpy.data.materials.new("MC " + "".join(f"{v:02X}" for v in color))
            mat["minecraft_builder_preview"] = token
            rgba = tuple(linear(v / 255) for v in color) + (1.0,)
            mat.diffuse_color = rgba
            mat.use_nodes = True
            mat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = rgba
            mesh.materials.append(mat)
            mats[key] = len(mesh.materials) - 1
    palette_materials = [mats[tuple(c)] for c in build["colors"]]
    mesh.polygons.foreach_set("material_index", [palette_materials[i] for i in material_ids])
    inv = tuple(1 / s for s in grid.scale)
    obj["minecraft_builder_fit_scale"] = (inv[0], inv[2], inv[1])
    real_scale = context.scene.minecraft_builder.preview_real_scale
    meters = 1 / max(1e-9, context.scene.unit_settings.scale_length)
    obj.scale = (
        (meters, meters, meters) if real_scale else tuple(obj["minecraft_builder_fit_scale"])
    )
    obj.location = (
        grid.origin[0] + build["size"][0] * inv[0] * 1.15,
        -grid.origin[2],
        grid.origin[1],
    )
    obj["dimensions_blocks"] = build["size"]
    obj["minecraft_builder_basis"] = [v for row in obj.matrix_basis.to_3x3() for v in row]
    return obj
