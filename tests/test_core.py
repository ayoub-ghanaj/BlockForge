"""Independent NBT decoding plus palette, bounds and shape regression checks.

python -m unittest discover -s tests -v
NBT tests use nbtlib (development dependency only).
"""

import gzip
import io
import json
import math
import struct
import unittest
from pathlib import Path

import nbtlib

from minecraft_builder import catalog
from minecraft_builder.core import exporters
from minecraft_builder.core.geometry import fit_grid
from minecraft_builder.core.palette import Block, allowed_blocks, canonical_state, parse_document
from minecraft_builder.core.shapes import orientations, split_state, state_mask
from minecraft_builder.core.volume import ShapeMatcher

ROOT = Path(__file__).resolve().parents[1]


def tag_state(tag):
    return canonical_state(
        str(tag["Name"])
        + (
            "[" + ",".join(f"{k}={v}" for k, v in tag["Properties"].items()) + "]"
            if tag.get("Properties")
            else ""
        )
    )


def fixture(count):
    blocks = catalog.bundled()["26.1.2"].blocks[:count]
    states = [b.state for b in blocks]
    return {
        "size": [19, 17, 18],
        "data_version": 4790,
        "version": "26.1.2",
        "palette": states,
        "colors": [list(b.rgb) for b in blocks],
        "cells": [
            [x, y, z, (x + 19 * z + 342 * y) % count]
            for y in range(17)
            for z in range(18)
            for x in range(19)
            if (x + y + z) % 7
        ],
    }


def expected(build):
    return {(x, y, z): build["palette"][i] for x, y, z, i in build["cells"]}


def read_schem(data):
    root = nbtlib.File.parse(io.BytesIO(gzip.decompress(data)))
    palette = {int(v): str(k) for k, v in root["Palette"].items()}
    values = []
    value = shift = 0
    for signed in root["BlockData"]:
        byte = int(signed) & 255
        value |= (byte & 127) << shift
        if byte & 128:
            shift += 7
        else:
            values.append(value)
            value = shift = 0
    sx, sy, sz = map(int, (root["Width"], root["Height"], root["Length"]))
    assert len(values) == sx * sy * sz
    return {
        (i % sx, i // (sx * sz), (i // sx) % sz): palette[v]
        for i, v in enumerate(values)
        if palette[v] != "minecraft:air"
    }


def read_litematic(data):
    root = nbtlib.File.parse(io.BytesIO(gzip.decompress(data)))
    region = root["Regions"]["Build"]
    palette = [tag_state(v) for v in region["BlockStatePalette"]]
    sx, sy, sz = (int(region["Size"][axis]) for axis in ("x", "y", "z"))
    bits = max(2, math.ceil(math.log2(len(palette))))
    # One concatenated bitstream, deliberately independent of the writer's word loop.
    stream = int.from_bytes(
        b"".join((int(v) & ((1 << 64) - 1)).to_bytes(8, "little") for v in region["BlockStates"]),
        "little",
    )
    result = {}
    for i in range(sx * sy * sz):
        state = palette[(stream >> (i * bits)) & ((1 << bits) - 1)]
        if state != "minecraft:air":
            result[i % sx, i // (sx * sz), (i // sx) % sz] = state
    return result


def read_bp(data, size):
    stream = io.BytesIO(data)

    def integer():
        return struct.unpack(">I", stream.read(4))[0]

    assert integer() == 0x0AE5BB36
    header = nbtlib.File.parse(io.BytesIO(stream.read(integer())))
    png = stream.read(integer())
    assert png.startswith(b"\x89PNG")
    root = nbtlib.File.parse(io.BytesIO(gzip.decompress(stream.read(integer()))))
    assert not stream.read()
    result = {}
    seen = set()
    for section in root["BlockRegion"]:
        base = [int(section[k]) * 16 for k in ("X", "Y", "Z")]
        container = section["BlockStates"]
        palette = [tag_state(t) for t in container["palette"]]
        bits = max(4, math.ceil(math.log2(len(palette))))
        for i in range(4096):
            word, slot = divmod(i, 64 // bits)
            index = (
                0
                if len(palette) == 1
                else (int(container["data"][word]) >> (slot * bits)) & ((1 << bits) - 1)
            )
            state = palette[index]
            pos = (base[0] + i % 16, base[1] + i // 256, base[2] + (i // 16) % 16)
            inside = all(pos[k] < size[k] for k in range(3))
            if inside:
                assert state != "minecraft:void_air"
                seen.add(pos)
                if state != "minecraft:air":
                    result[pos] = state
            else:
                assert state == "minecraft:void_air"
    assert len(seen) == math.prod(size)
    assert int(header["BlockCount"]) == len(result)
    return result


class ExportTests(unittest.TestCase):
    def test_three_readers_and_long_boundaries(self):
        for count in (1, 4, 17, 40, 260):
            with self.subTest(palette=count):
                build = fixture(count)
                want = expected(build)
                exporters.validate_build(build)
                self.assertEqual(read_schem(exporters.schematic(build, "Test", "")), want)
                self.assertEqual(read_litematic(exporters.litematic(build, "Test", "")), want)
                self.assertEqual(
                    read_bp(exporters.blueprint(build, "Test", ""), build["size"]), want
                )

    def test_bad_coordinates_fail(self):
        build = fixture(1)
        build["cells"].append([19, 0, 0, 0])
        with self.assertRaises(ValueError):
            exporters.validate_build(build)

    def test_duplicate_cells_fail(self):
        build = fixture(1)
        build["cells"].append(build["cells"][0])
        with self.assertRaises(ValueError):
            exporters.validate_build(build)

    def test_export_profile_mismatch(self):
        build = fixture(1)
        profile = catalog.bundled()["26.1.2"]
        exporters.validate_profile(build, profile)
        build["palette"] = ["minecraft:poplar_planks"]
        with self.assertRaisesRegex(ValueError, "outside Minecraft"):
            exporters.validate_profile(build, profile)
        build = fixture(1)
        build["data_version"] = 5023
        with self.assertRaisesRegex(ValueError, "version differs"):
            exporters.validate_profile(build, profile)
        build = fixture(1)
        build["version"] = "26.3"
        with self.assertRaisesRegex(ValueError, "version differs"):
            exporters.validate_profile(build, profile)


class PaletteTests(unittest.TestCase):
    def test_all_bundled_states_match_version_reports(self):
        with gzip.open(ROOT / "tests/fixtures/minecraft-reports.json.gz", "rt") as stream:
            references = json.load(stream)
        for version, profile in catalog.bundled().items():
            reports = references[version]
            for block in profile.blocks:
                for state, _ in orientations(block):
                    name, props = split_state(state)
                    name = name.split(":")[1]
                    with self.subTest(version=version, state=state):
                        self.assertTrue(name in reports, "Unknown block: " + name)
                        valid = reports[name]
                        self.assertEqual(set(props), set(valid))
                        for k, v in props.items():
                            self.assertIn(v, valid[k])

    def test_experimental_and_technical_blocks_excluded(self):
        for version, forbidden in [
            ("1.19.4", "minecraft:cherry_planks"),
            ("1.20.4", "minecraft:tuff_bricks"),
            ("1.21.3", "minecraft:pale_oak_planks"),
            ("26.1.2", "minecraft:test_block"),
        ]:
            self.assertFalse(
                any(b.state.split("[")[0] == forbidden for b in catalog.bundled()[version].blocks)
            )

    def test_blacklist_wins_and_empty_whitelist_rejected(self):
        a = Block("minecraft:stone", (100, 100, 100))
        b = Block("minecraft:sand", (200, 190, 150), gravity=True)
        with self.assertRaises(ValueError):
            allowed_blocks([a, b], [a.state], [a.state])
        with self.assertRaises(ValueError):
            allowed_blocks([a, b], [])
        self.assertEqual(allowed_blocks([a, b]), [a])

    def test_palette_validation(self):
        doc = {
            "schema_version": 1,
            "profiles": [
                {
                    "id": "Custom",
                    "data_version": 4790,
                    "blocks": [{"state": "minecraft:stone", "rgb": [128, 128, 128]}],
                }
            ],
        }
        self.assertIn("Custom", parse_document(doc))
        for key, value in [
            ("rgb", [256, 0, 0]),
            ("state", "minecraft:stone[foo=1,foo=2]"),
            ("shape", "arbitrary"),
        ]:
            altered = json.loads(json.dumps(doc))
            altered["profiles"][0]["blocks"][0][key] = value
            with self.assertRaises(ValueError):
                parse_document(altered)


class ShapeTests(unittest.TestCase):
    def test_exact_shapes_are_selected(self):
        blocks = [
            Block("minecraft:stone", (128, 128, 128)),
            Block(
                "minecraft:stone_slab[type=bottom,waterlogged=false]", (128, 128, 128), shape="slab"
            ),
            Block(
                "minecraft:stone_stairs[facing=north,half=bottom,shape=straight,waterlogged=false]",
                (128, 128, 128),
                shape="stairs",
            ),
        ]
        matcher = ShapeMatcher(blocks)
        for block in blocks:
            for state, mask in orientations(block):
                chosen, material = matcher.match(mask, (128, 128, 128))
                self.assertEqual(state_mask(chosen, material.shape), mask)

    def test_fit_respects_bounds_and_aspect(self):
        grid = fit_grid([(10, -4, 2), (12, 0, 3)], (20, 20, 20), True)
        self.assertEqual(tuple(grid.size), (10, 20, 5))
        with self.assertRaises(ValueError):
            fit_grid([(0, 0, 0), (1, 1, 1)], (512, 512, 512), False)


if __name__ == "__main__":
    unittest.main()
