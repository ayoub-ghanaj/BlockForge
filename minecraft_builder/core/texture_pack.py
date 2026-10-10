"""Explicit archive reads and orthographic texture recipes; no game discovery."""

import gzip
import json
import math
import re
import struct
import zipfile
from functools import lru_cache
from pathlib import Path

import numpy as np

SIDES = ("down", "up", "north", "south", "west", "east")
NORMALS = {
    "down": (0, -1, 0),
    "up": (0, 1, 0),
    "north": (0, 0, -1),
    "south": (0, 0, 1),
    "west": (-1, 0, 0),
    "east": (1, 0, 0),
}


@lru_cache(maxsize=1)
def metadata():
    return json.loads(
        gzip.decompress((Path(__file__).resolve().parents[1] / "data/visuals.json.gz").read_bytes())
    )


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


def rotation(option):
    x, y = (math.radians(-option.get(k, 0)) for k in ("x", "y"))
    cx, sx, cy, sy = math.cos(x), math.sin(x), math.cos(y), math.sin(y)
    return np.rint(
        np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        @ np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ).astype(int)


class Archive:
    def __init__(self, path):
        self.zip = zipfile.ZipFile(path)
        self.files = {}
        total = 0
        for item in self.zip.infolist():
            if not re.fullmatch(
                r"assets/[a-z0-9_.-]+/textures/[a-z0-9_./-]+\.png(?:\.mcmeta)?", item.filename
            ):
                continue
            if ".." in item.filename.split("/"):
                continue
            if item.filename in self.files:
                self.close()
                raise ValueError("Duplicate texture path in archive")
            total += item.file_size
            if (
                item.file_size > 16 * 1024 * 1024
                or total > 256 * 1024 * 1024
                or len(self.files) >= 16384
            ):
                self.close()
                raise ValueError("Texture archive exceeds the 256 MiB / 16,384-file preview budget")
            self.files[item.filename] = item
        if not any(p.endswith(".png") for p in self.files):
            self.close()
            raise ValueError("No assets/<namespace>/textures/*.png files found")

    def close(self):
        self.zip.close()

    def png(self, texture):
        ns, path = texture.split(":", 1)
        name = f"assets/{ns}/textures/{path}.png"
        if name not in self.files:
            raise KeyError(texture)
        data = self.zip.read(self.files[name])
        if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
            raise ValueError("Invalid PNG texture: " + texture)
        width, height = struct.unpack(">II", data[16:24])
        if not width or not height or width * height > 16_000_000:
            raise ValueError("Texture exceeds 16 million pixels: " + texture)
        meta = (
            json.loads(self.zip.read(self.files[name + ".mcmeta"]))
            if name + ".mcmeta" in self.files
            else {}
        )
        return data, meta


def first_frame(pixels, meta):
    animation = meta.get("animation")
    if animation is None:
        return pixels
    h, w = pixels.shape[:2]
    fw = animation.get("width", w)
    fh = animation.get("height", fw)
    if type(fw) is not int or type(fh) is not int or not 0 < fw <= w or not 0 < fh <= h:
        raise ValueError("Invalid animation frame size")
    frames = animation.get("frames", [0])
    frame = frames[0] if frames else 0
    index = frame.get("index") if isinstance(frame, dict) else frame
    if type(index) is not int or not 0 <= index < (w // fw) * (h // fh):
        raise ValueError("Invalid animation frame index")
    y, x = divmod(index, w // fw)
    return pixels[y * fh : (y + 1) * fh, x * fw : (x + 1) * fw]


def render(recipe, read_texture, fallback=(180, 180, 180)):
    """Six 16-pixel face projections. Weighted random variants use one sample.

    These texture projections decorate the supported cube/slab/stair geometry;
    they do not add custom resource-pack model geometry or animate textures.
    """
    result = np.zeros((6, 16, 16, 4), np.float32)
    fragments = []
    missing = set()
    u, v = np.meshgrid(np.arange(16) + 0.5, np.arange(16) + 0.5)
    for group in recipe:
        option = max(group, key=lambda o: o.get("weight", 1))
        matrix = rotation(option)
        for face in option["quads"]:
            side = face["side"]
            a = np.array(face["from"])
            b = np.array(face["to"])
            pu, pv = project(side, np.array([a, b]))
            rect = (pu.min(), pv.min(), pu.max(), pv.max())
            mask = (u >= rect[0]) & (u < rect[2]) & (v >= rect[1]) & (v < rect[3])
            if not mask.any():
                continue
            axis = int(np.argmax(np.abs(NORMALS[side])))
            depth = (b if max(NORMALS[side]) == 1 else a)[axis]
            points = (unproject(side, u, v, depth) - 8) @ matrix.T + 8
            normal = tuple(matrix @ NORMALS[side])
            dest = next(s for s, n in NORMALS.items() if n == normal)
            du, dv = project(dest, points)
            try:
                tex = read_texture(face["texture"])
            except KeyError:
                missing.add(face["texture"])
                tex = np.array([[(*[c / 255 for c in fallback], 1)]], np.float32)
            s = (u - rect[0]) / (rect[2] - rect[0])
            t = (v - rect[1]) / (rect[3] - rect[1])
            if option.get("uvlock"):
                # Keep world-facing UV orientation while rotating the model.
                s = du / 16
                t = dv / 16
            for _ in range(face.get("rotation", 0) // 90):
                s, t = t, 1 - s
            uv = face["uv"]
            tx = (
                np.floor((uv[0] + s * (uv[2] - uv[0])) * tex.shape[1] / 16).astype(int)
                % tex.shape[1]
            )
            ty = (
                np.floor((uv[1] + t * (uv[3] - uv[1])) * tex.shape[0] / 16).astype(int)
                % tex.shape[0]
            )
            pixels = tex[ty, tx].copy()
            pixels[:, :, :3] *= face.get("tint", [1, 1, 1])
            pixels[:, :, :3] = (
                np.where(
                    pixels[:, :, :3] <= 0.04045,
                    pixels[:, :, :3] / 12.92,
                    ((pixels[:, :, :3] + 0.055) / 1.055) ** 2.4,
                )
                * pixels[:, :, 3:4]
            )
            layer = np.zeros((16, 16, 4), np.float32)
            xx = np.clip(du.astype(int), 0, 15)
            yy = np.clip(dv.astype(int), 0, 15)
            layer[yy[mask], xx[mask]] = pixels[mask]
            fragments.append((dest, float((points @ normal)[mask].mean()), layer))
    for side, depth, pixels in sorted(fragments, key=lambda row: row[1]):
        i = SIDES.index(side)
        result[i] = pixels + result[i] * (1 - pixels[:, :, 3:4])
    alpha = result[:, :, :, 3:4]
    rgb = result[:, :, :, :3] / np.maximum(alpha, 1e-12)
    result[:, :, :, :3] = np.where(
        rgb <= 0.0031308, rgb * 12.92, 1.055 * np.maximum(rgb, 0) ** (1 / 2.4) - 0.055
    )
    return result, missing
