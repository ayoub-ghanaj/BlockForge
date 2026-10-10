"""Resolve vanilla models and measure their six orthographic surface colors.

Development only. Uses version-exact assets, model inheritance, multipart
conditions, UV crops, tint maps, model rotations, alpha layers and animation
timings. Runtime palettes contain numbers, never Minecraft textures.
"""

import json
import math
from functools import lru_cache
from io import BytesIO

import numpy as np
from PIL import Image

from minecraft_builder.core.shapes import state_mask
from tools.palette_sources import decode

SIDES = ("down", "up", "north", "south", "west", "east")
NORMALS = {
    "down": (0, -1, 0),
    "up": (0, 1, 0),
    "north": (0, 0, -1),
    "south": (0, 0, 1),
    "west": (-1, 0, 0),
    "east": (1, 0, 0),
}


class Unsupported(ValueError):
    pass


def to_linear(v):
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def to_srgb(v):
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * np.maximum(v, 0) ** (1 / 2.4) - 0.055)


def rgb(v):
    return np.clip(np.rint(to_srgb(v) * 255), 0, 255).astype(int).tolist()


def location(name):
    return name.split(":", 1)[-1]


def matches(condition, props):
    if "OR" in condition:
        return any(matches(c, props) for c in condition["OR"])
    if "AND" in condition:
        return all(matches(c, props) for c in condition["AND"])
    return all(
        props.get(k) in (str(v).lower() if isinstance(v, bool) else str(v)).split("|")
        for k, v in condition.items()
    )


def rotation(variant):
    x, y = [math.radians(-variant.get(k, 0)) for k in ("x", "y")]
    cx, sx, cy, sy = math.cos(x), math.sin(x), math.cos(y), math.sin(y)
    return np.rint(
        np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        @ np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ).astype(int)


def project(side, xyz):
    x, y, z = np.moveaxis(xyz, -1, 0)
    return {
        "down": (x, 16 - z),
        "up": (x, z),
        "north": (16 - x, 16 - y),
        "south": (x, 16 - y),
        "west": (z, 16 - y),
        "east": (16 - z, 16 - y),
    }[side]


def unproject(side, u, v, depth):
    d = np.full_like(u, depth)
    return np.stack(
        {
            "down": (u, d, 16 - v),
            "up": (u, d, v),
            "north": (16 - u, 16 - v, d),
            "south": (u, 16 - v, d),
            "west": (d, 16 - v, u),
            "east": (d, 16 - v, 16 - u),
        }[side],
        axis=-1,
    )


class Assets:
    def __init__(self, source):
        self.source = source
        self.files = source["files"]
        self.used = set()
        # Instance-local caches release old version assets between profiles.
        self.read = lru_cache(None)(self._read)
        self.model = lru_cache(None)(self._model)
        self.texture = lru_cache(None)(self._texture)

    def _read(self, path):
        self.used.add(path)
        return decode(self.files[path])

    def _model(self, name):
        if name.startswith("builtin/"):
            raise Unsupported("entity_renderer")
        data = json.loads(self.read("assets/minecraft/models/" + location(name) + ".json"))
        parent = self.model(data["parent"]) if data.get("parent") else {}
        return {
            **parent,
            **data,
            "textures": {**parent.get("textures", {}), **data.get("textures", {})},
        }

    def _texture(self, name):
        path = "assets/minecraft/textures/" + location(name) + ".png"
        image = np.asarray(Image.open(BytesIO(self.read(path))).convert("RGBA"), dtype=float) / 255
        meta = (
            json.loads(self.read(path + ".mcmeta")).get("animation")
            if path + ".mcmeta" in self.files
            else None
        )
        if meta is None:
            return image
        h, w = image.shape[:2]
        fw = meta.get("width", w)
        fh = meta.get("height", fw)
        count = (w // fw) * (h // fh)
        frames = meta.get("frames", list(range(count)))
        colors = []
        weights = []
        for frame in frames:
            index = frame.get("index") if isinstance(frame, dict) else frame
            weight = (
                frame.get("time", meta.get("frametime", 1))
                if isinstance(frame, dict)
                else meta.get("frametime", 1)
            )
            y, x = divmod(index, w // fw)
            part = image[y * fh : (y + 1) * fh, x * fw : (x + 1) * fw]
            if part.shape != (fh, fw, 4):
                raise ValueError("Invalid animation frame " + path)
            alpha = part[:, :, 3:4]
            colors.append(np.concatenate((to_linear(part[:, :, :3]) * alpha, alpha), axis=2))
            weights.append(weight)
        avg = np.average(colors, axis=0, weights=weights)
        alpha = avg[:, :, 3:4]
        return np.concatenate((to_srgb(avg[:, :, :3] / np.maximum(alpha, 1e-12)), alpha), axis=2)

    def tint(self, name):
        fixed = {"spruce_leaves": 0x619961, "birch_leaves": 0x80A755, "mangrove_leaves": 0x92C648}
        if name in fixed:
            n = fixed[name]
            return np.array([(n >> 16) & 255, (n >> 8) & 255, n & 255]) / 255
        kind = "foliage" if name.endswith("_leaves") else "grass" if name == "grass_block" else None
        if not kind:
            raise Unsupported("unsupported_tint")
        image = Image.open(
            BytesIO(self.read("assets/minecraft/textures/colormap/" + kind + ".png"))
        ).convert("RGB")
        # Plains reference: temperature .8, downfall .4. Biome-dependent colors
        # stay opt-in; a schematic does not force the destination biome.
        return np.array(image.getpixel((int((1 - 0.8) * 255), int((1 - 0.8 * 0.4) * 255)))) / 255

    def parts(self, name, props):
        block = json.loads(self.read("assets/minecraft/blockstates/" + name + ".json"))
        if "variants" in block:
            for key, part in block["variants"].items():
                if matches(dict(p.split("=") for p in key.split(",")) if key else {}, props):
                    return [part]
            raise ValueError("No matching default variant: " + name)
        if "multipart" in block:
            return [
                part["apply"] for part in block["multipart"] if matches(part.get("when", {}), props)
            ]
        raise Unsupported("no_model")

    def sample(self, model, face, element, side, name):
        texture = face["texture"]
        seen = set()
        while (
            isinstance(texture, dict)
            or texture.startswith("#")
            or texture in model.get("textures", {})
        ):
            # A descriptor's sprite can itself be another texture reference.
            if isinstance(texture, dict):
                texture = texture["sprite"]
                continue
            if texture in seen:
                raise ValueError("Texture reference cycle")
            seen.add(texture)
            texture = model["textures"][texture.removeprefix("#")]
        tex = self.texture(texture)
        a = np.asarray(element["from"])
        b = np.asarray(element["to"])
        points = np.array([a, b])
        uu, vv = project(side, points)
        rect = (uu.min(), vv.min(), uu.max(), vv.max())
        u, v = np.meshgrid(np.arange(16) + 0.5, np.arange(16) + 0.5)
        mask = (u >= rect[0]) & (u < rect[2]) & (v >= rect[1]) & (v < rect[3])
        if not mask.any():
            return None
        s = (u - rect[0]) / (rect[2] - rect[0])
        t = (v - rect[1]) / (rect[3] - rect[1])
        for _ in range(face.get("rotation", 0) // 90):
            s, t = t, 1 - s
        uv = face.get("uv", rect)
        tx = np.floor((uv[0] + s * (uv[2] - uv[0])) * tex.shape[1] / 16).astype(int) % tex.shape[1]
        ty = np.floor((uv[1] + t * (uv[3] - uv[1])) * tex.shape[0] / 16).astype(int) % tex.shape[0]
        pixels = tex[ty, tx].copy()
        if "tintindex" in face:
            pixels[:, :, :3] *= self.tint(name)
        pixels[:, :, :3] = to_linear(pixels[:, :, :3]) * pixels[:, :, 3:4]
        pixels[~mask] = 0
        axis = int(np.argmax(np.abs(NORMALS[side])))
        positive = max(NORMALS[side]) == 1
        depth = (b if positive else a)[axis]
        return pixels, unproject(side, u, v, depth), mask

    def measure(self, name, props, kind, state, verify_shape=True):
        parts = self.parts(name, props)
        if not parts:
            raise Unsupported("no_model")
        geometry = np.zeros((16, 16, 16), dtype=bool)
        boundary = np.zeros((6, 16, 16), dtype=bool)
        fragments = []
        tinted = False
        for group in parts:
            options = group if isinstance(group, list) else [group]
            # Weighted random variants normally differ only in orientation.
            # Average their projected surfaces instead of choosing one texture.
            group_images = []
            weights = []
            for option in options:
                model = self.model(option["model"])
                elements = model.get("elements", [])
                if not elements:
                    raise Unsupported("entity_renderer")
                transform = rotation(option)
                layers = []
                for element in elements:
                    if "rotation" in element and verify_shape:
                        raise Unsupported("rotated_element")
                    bounds = (np.array([element["from"], element["to"]]) - 8) @ transform.T + 8
                    lo = np.ceil(bounds.min(axis=0)).astype(int)
                    hi = np.floor(bounds.max(axis=0)).astype(int)
                    if np.any(lo < 0) or np.any(hi > 16):
                        raise Unsupported("outside_cell")
                    geometry[lo[0] : hi[0], lo[1] : hi[1], lo[2] : hi[2]] = True
                    for side, face in element.get("faces", {}).items():
                        tinted |= "tintindex" in face
                        result = self.sample(model, face, element, side, name)
                        if result is None:
                            continue
                        pixels, points, mask = result
                        norm = tuple(transform @ NORMALS[side])
                        dest = next(s for s, n in NORMALS.items() if n == norm)
                        points = (points - 8) @ transform.T + 8
                        u, v = project(dest, points)
                        xx = np.clip(u.astype(int), 0, 15)
                        yy = np.clip(v.astype(int), 0, 15)
                        rendered = np.zeros((16, 16, 4))
                        rendered[yy[mask], xx[mask]] = pixels[mask]
                        depth = float((points @ norm)[mask].mean())
                        if abs(depth - (16 if max(norm) == 1 else 0)) < 1e-6:
                            boundary[SIDES.index(dest), yy[mask], xx[mask]] = True
                        layers.append((dest, depth, rendered))
                group_images.append(layers)
                weights.append(option.get("weight", 1))
            if len(options) == 1:
                fragments.extend(group_images[0])
            else:
                # Each alternative is a complete instance of the same part.
                weighted = np.average(
                    [self.composite(layers) for layers in group_images], axis=0, weights=weights
                )
                for i, side in enumerate(SIDES):
                    depth = max(
                        (d for layers in group_images for s, d, _ in layers if s == side), default=0
                    )
                    fragments.append((side, depth, weighted[i]))
        # Multipart mushrooms are six zero-thickness faces of a closed cube.
        # Mangrove roots use interior crossed planes but have a full-cell shape;
        # this explicit adapter is also checked against the real game shapes.
        if kind == "cube" and (boundary.all() or name == "mangrove_roots"):
            geometry[:] = True
        expected = state_mask(state, kind)
        actual = 0
        for y in range(2):
            for z in range(2):
                for x in range(2):
                    cells = geometry[x * 8 : (x + 1) * 8, y * 8 : (y + 1) * 8, z * 8 : (z + 1) * 8]
                    if verify_shape and cells.any() and not cells.all():
                        raise Unsupported("unsupported_shape")
                    if cells.all():
                        actual |= 1 << (x + 2 * z + 4 * y)
        if verify_shape and actual != expected:
            raise Unsupported("unsupported_shape")
        images = self.composite(fragments)
        colors = {}
        means = []
        transparent = False
        for side, image in zip(SIDES, images):
            alpha = image[:, :, 3]
            total = alpha.sum()
            if total < 1e-9:
                if verify_shape:
                    raise Unsupported("invisible_surface")
                continue
            color = image[:, :, :3].sum(axis=(0, 1)) / total
            colors[side] = rgb(color)
            means.append(color)
            # Cube surface coverage is full. Stair/slab silhouettes naturally
            # contain uncovered pixels and must not be called transparent.
            transparent |= (
                bool((alpha < 0.999).any())
                if kind == "cube"
                else bool(((alpha > 0) & (alpha < 0.999)).any())
            )
        flags = []
        if transparent:
            flags.append("transparent")
        if tinted:
            flags.append("biome_tinted")
        return rgb(np.mean(means, axis=0)), colors, flags

    @staticmethod
    def composite(fragments):
        result = np.zeros((6, 16, 16, 4))
        for side, depth, pixels in sorted(fragments, key=lambda f: f[1]):
            index = SIDES.index(side)
            alpha = pixels[:, :, 3:4]
            result[index] = pixels + result[index] * (1 - alpha)
        return result
