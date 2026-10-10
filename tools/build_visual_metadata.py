"""Derive per-state colors and texture-mapping recipes from audited asset caches.

Ships numeric geometry, texture identifiers and tint values, never image pixels.
No network or Minecraft installation access. Run after build_palettes.py.
"""

import gzip
import hashlib
import json
import sys
from itertools import product
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from minecraft_builder.core.palette import parse_document
from minecraft_builder.core.shapes import orientations, split_state, with_properties
from tools.palette_assets import Assets, project
from tools.palette_sources import load


def encode(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def recipe(assets, name, props):
    groups = []
    for group in assets.parts(name, props):
        options = []
        for option in group if isinstance(group, list) else [group]:
            model = assets.model(option["model"])
            quads = []
            for element in model.get("elements", []):
                for side, face in element.get("faces", {}).items():
                    texture = face["texture"]
                    seen = set()
                    while (
                        isinstance(texture, dict)
                        or texture.startswith("#")
                        or texture in model.get("textures", {})
                    ):
                        if isinstance(texture, dict):
                            texture = texture["sprite"]
                            continue
                        if texture in seen:
                            raise ValueError("Texture cycle")
                        seen.add(texture)
                        texture = model["textures"][texture.removeprefix("#")]
                    if ":" not in texture:
                        texture = "minecraft:" + texture
                    a, b = element["from"], element["to"]
                    u, v = project(side, np.array([a, b]))
                    rect = [float(u.min()), float(v.min()), float(u.max()), float(v.max())]
                    if rect[0] == rect[2] or rect[1] == rect[3]:
                        continue
                    quads.append(
                        {
                            "side": side,
                            "from": a,
                            "to": b,
                            "uv": face.get("uv", rect),
                            "rotation": face.get("rotation", 0),
                            "texture": texture,
                            "tint": assets.tint(name).tolist()
                            if "tintindex" in face
                            else [1, 1, 1],
                        }
                    )
            options.append(
                {
                    "x": option.get("x", 0),
                    "y": option.get("y", 0),
                    "uvlock": option.get("uvlock", False),
                    "weight": option.get("weight", 1),
                    "quads": quads,
                }
            )
        groups.append(options)
    return groups


def main():
    path = ROOT / "minecraft_builder/data/bundled.json.gz"
    data = json.loads(gzip.decompress(path.read_bytes()))
    parsed = parse_document(data)
    covers = json.loads(gzip.decompress((path.parent / "covers.json.gz").read_bytes()))
    recipes = {}
    profiles = {}
    measures = {}
    count = 0
    for raw in data["profiles"]:
        version = raw["id"]
        source = load(version)
        assets = Assets(source)
        mapping = {}
        hashes = {}

        def get(state, kind, measure=True):
            name, props = split_state(state)
            name = name.split(":")[1]
            visual = recipe(assets, name, props)
            ident = hashlib.sha256(encode(visual)).hexdigest()[:24]
            recipes[ident] = visual
            mapping[state] = ident
            if not measure:
                return
            textures = {q["texture"] for group in visual for opt in group for q in opt["quads"]}
            tex_hash = []
            for texture in sorted(textures):
                ns, loc = texture.split(":")
                p = f"assets/{ns}/textures/{loc}.png"
                if p not in hashes:
                    hashes[p] = hashlib.sha256(
                        assets.read(p)
                        + (assets.read(p + ".mcmeta") if p + ".mcmeta" in assets.files else b"")
                    ).hexdigest()
                tex_hash.append(hashes[p])
            key = (ident, tuple(tex_hash), kind)
            if key not in measures:
                measures[key] = assets.measure(name, props, kind, state)[1]
            return measures[key]

        for entry, block in zip(raw["blocks"], parsed[version].blocks):
            name, props = split_state(block.state)
            registry = source["blocks"][name.split(":")[1]][0]
            if block.shape == "cube":
                keys = [k for k in ("axis", "facing") if k in props and k in registry]
                states = (
                    [
                        with_properties(block.state, **dict(zip(keys, values)))
                        for values in product(*(registry[k] for k in keys))
                    ]
                    if keys
                    else [block.state]
                )
            else:
                states = [s for s, _ in orientations(block)]
            entry.pop("variants", None)
            variants = []
            for state in sorted(states):
                faces = get(state, block.shape)
                variants.append({"state": state, "faces": faces})
                if block.shape == "stairs":
                    for corner in ("inner_left", "inner_right", "outer_left", "outer_right"):
                        get(with_properties(state, shape=corner), block.shape, False)
            if len(states) > 1:
                entry["variants"] = variants
            count += len(states)
        for row in covers[version]["blocks"]:
            if row["state"] not in mapping:
                get(row["state"], "cover", False)
        profiles[version] = mapping
        print(
            version,
            len(mapping),
            "display states;",
            len(measures),
            "unique color projections",
            flush=True,
        )
    parse_document(data)
    path.write_bytes(gzip.compress(encode(data), mtime=0))
    target = path.parent / "visuals.json.gz"
    target.write_bytes(
        gzip.compress(
            encode({"schema_version": 1, "profiles": profiles, "recipes": recipes}), mtime=0
        )
    )
    print(
        "Wrote",
        count,
        "matching states and",
        len(recipes),
        "display recipes;",
        target.stat().st_size,
        "bytes",
        flush=True,
    )


if __name__ == "__main__":
    main()
