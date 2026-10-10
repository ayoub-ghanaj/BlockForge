"""Independent, generic fixtures for the 0.5.0 editing and appearance features."""

import copy
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from minecraft_builder import catalog
from minecraft_builder.core import bulk, texture_pack
from minecraft_builder.core.appearance import SIDES, FaceMatcher, exposed_centers
from minecraft_builder.core.editing import Editor, empty_document
from minecraft_builder.core.palette import Block, Profile
from minecraft_builder.perimeter import layout, protection


def finish(generator):
    return next(v for stage, v in generator if stage == "result")


def build(cells):
    states = list(dict.fromkeys(cells.values()))
    profile = catalog.bundled()["26.1.2"]
    blocks = {b.state.split("[")[0]: b for b in profile.blocks}
    shapes = [
        "cover" if s.endswith("_carpet") or "_button[" in s else blocks[s.split("[")[0]].shape
        for s in states
    ]
    return {
        "size": [max(p[i] for p in cells) + 1 for i in range(3)],
        "palette": states,
        "colors": [[128, 128, 128] for s in states],
        "shapes": shapes,
        "masks": [255 for s in states],
        "cells": [[*p, states.index(s)] for p, s in cells.items()],
        "version": "26.1.2",
        "data_version": profile.data_version,
    }


class FaceMatchingTests(unittest.TestCase):
    def test_orientation_matches_exposed_face_instead_of_average(self):
        red = (220, 30, 20)
        blue = (20, 30, 220)

        def faces(front):
            return tuple((s, red if s == front else blue) for s in SIDES)

        block = Block(
            "demo:panel[facing=north]",
            (70, 30, 170),
            faces=faces("north"),
            variants=(
                ("demo:panel[facing=north]", faces("north")),
                ("demo:panel[facing=east]", faces("east")),
            ),
        )
        matcher = FaceMatcher([block])
        samples = tuple((*red, 1 if s == "east" else 0) for s in SIDES)
        self.assertEqual(matcher.match(255, samples, red)[0], "demo:panel[facing=east]")
        for face in ("floor", "north", "south", "west", "east"):
            result = finish(
                layout.compose(
                    2,
                    2,
                    2,
                    {face: {"pixels": np.array([[red]], np.uint8)}},
                    [block],
                    Profile("test", 1, (block,)),
                    protection="NONE",
                    face_matching=True,
                )
            )
            if face == "west":
                self.assertEqual(result["palette"], ["demo:panel[facing=east]"])
            if face == "south":
                self.assertEqual(result["palette"], ["demo:panel[facing=north]"])

    def test_shared_faces_are_not_color_samples(self):
        full = exposed_centers(255, (0, 255, 0, 0, 0, 0))
        self.assertEqual(full[1][1], 0)
        self.assertEqual(full[0], ((0.0, 0.5, 0.5), 4))
        slab = exposed_centers(15, (0, 0, 0, 0, 0, 0))
        self.assertEqual(slab[3], ((0.5, 0.5, 0.5), 4))

    def test_all_orientation_metadata_uses_legal_reported_states(self):
        import gzip

        refs = json.loads(
            gzip.decompress(
                (Path(__file__).parent / "fixtures/minecraft-reports.json.gz").read_bytes()
            )
        )
        visuals = texture_pack.metadata()
        for version, profile in catalog.bundled().items():
            for block in profile.blocks:
                for state, faces in block.variants:
                    name, props = state[:-1].split("[", 1)
                    for pair in props.split(","):
                        key, value = pair.split("=")
                        self.assertIn(value, refs[version][name.split(":")[1]][key], state)
                    self.assertIn(state, visuals["profiles"][version])
                    self.assertEqual(set(dict(faces)), set(SIDES))


class BulkTests(unittest.TestCase):
    def editor(self, limit=100, volume=512):
        e = Editor(
            build({(0, 0, 0): "minecraft:stone", (1, 0, 0): "minecraft:stone"}),
            empty_document(),
            {
                "minecraft:stone": ((100, 100, 100), "cube"),
                "minecraft:gold_block": ((240, 210, 50), "cube"),
            },
            (8, 8, 8),
            volume,
            limit,
        )
        return e

    def test_fill_copy_mirror_paste_single_undo_and_persistence(self):
        e = self.editor()
        e.change(
            {p: "minecraft:gold_block" for p in bulk.positions((0, 1, 0), (2, 1, 1), e.limits)}
        )
        before = e.result()
        clip = bulk.copy(e.cells, (0, 0, 0), (2, 1, 1), e.limits)
        changes = bulk.paste(clip, (4, 0, 3), e.cells, e.limits, mirror="X")
        e.change(changes)
        self.assertEqual(len(e.document["undo"]), 2)
        self.assertEqual(e.cells[6, 0, 3], "minecraft:stone")
        e.undo()
        self.assertEqual(e.result(), before)
        e.undo(True)
        restored = Editor(e.build, e.document, e.materials, e.limits, e.volume_limit)
        self.assertEqual(restored.result(), e.result())

    def test_whole_operation_limits_are_atomic_and_move_at_capacity_works(self):
        e = self.editor(limit=3)
        before = copy.deepcopy((e.cells, e.document))
        with self.assertRaises(ValueError):
            e.change({(2, 0, 0): "minecraft:stone", (3, 0, 0): "minecraft:stone"})
        self.assertEqual((e.cells, e.document), before)
        e = self.editor(volume=20)
        before = copy.deepcopy((e.cells, e.document))
        with self.assertRaises(ValueError):
            e.change({(5, 0, 0): "minecraft:stone", (0, 0, 5): "minecraft:stone"})
        self.assertEqual((e.cells, e.document), before)
        e = self.editor(limit=2)
        e.change({(0, 0, 0): None, (7, 0, 0): "minecraft:stone"})
        self.assertEqual(len(e.cells), 2)

    def test_paste_does_not_silently_overwrite_and_mirrors_stair_state(self):
        e = self.editor()
        clip = bulk.copy(e.cells, (0, 0, 0), (1, 0, 0), e.limits)
        e.change({(0, 0, 0): "minecraft:gold_block"})
        with self.assertRaises(ValueError):
            bulk.paste(clip, (0, 0, 0), e.cells, e.limits)
        with self.assertRaises(ValueError):
            bulk.paste(clip, (7, 0, 0), e.cells, e.limits)
        state = "minecraft:oak_stairs[facing=east,half=bottom,shape=inner_left,waterlogged=false]"
        self.assertIn("facing=west", bulk.mirrored_state(state, "X"))
        self.assertIn("shape=inner_right", bulk.mirrored_state(state, "X"))
        self.assertIn("half=top", bulk.mirrored_state(state, "Y"))
        self.assertEqual(len(list(bulk.brush_positions((3, 3, 3), 1, e.limits))), 7)


class ProtectionTests(unittest.TestCase):
    def check(self, cells, cover=True, version="26.1.2"):
        return finish(protection.check(build(cells), catalog.bundled()[version], cover))

    def test_edited_cover_hole_is_found_and_repair_clears_it(self):
        cells = {(x, 0, z): "minecraft:stone" for x in range(3) for z in range(3)}
        cells.update({(x, 1, z): "minecraft:glass" for x in range(3) for z in range(3)})
        good = self.check(cells)
        self.assertEqual(good["issue_count"], 0)
        self.assertEqual(good["covered"], 9)
        del cells[1, 1, 1]
        bad = self.check(cells)
        self.assertEqual(bad["uncovered"], 1)
        self.assertEqual(bad["unproven_light"], 1)
        cells[1, 1, 1] = "minecraft:glass"
        self.assertEqual(self.check(cells)["issue_count"], 0)

    def test_lighting_proof_changes_with_version_and_light_removal(self):
        cells = {(x, 0, 0): "minecraft:stone" for x in range(12)}
        cells[0, 0, 0] = "minecraft:sea_lantern"
        modern = self.check(cells, False)
        old = self.check(cells, False, "1.17")
        self.assertEqual(modern["unproven_light"], 0)
        self.assertGreater(old["unproven_light"], 0)
        self.assertEqual(self.check(cells, True)["uncovered"], 12)
        cells[0, 0, 0] = "minecraft:stone"
        self.assertEqual(self.check(cells, False)["unproven_light"], 12)

    def test_supported_bottom_slab_cover_and_floating_button(self):
        self.assertEqual(
            self.check(
                {
                    (0, 0, 0): "minecraft:stone",
                    (0, 1, 0): "minecraft:stone_slab[type=bottom,waterlogged=false]",
                }
            )["issue_count"],
            0,
        )
        button = "minecraft:stone_button[face=floor,facing=north,powered=false]"
        result = self.check({(0, 0, 0): "minecraft:stone", (2, 2, 2): button})
        self.assertEqual(result["unsupported_covers"], 1)

    def test_support_exceptions_match_game_probes(self):
        from minecraft_builder.perimeter import covers

        button = "minecraft:stone_button[face=floor,facing=north,powered=false]"
        leaf = "minecraft:oak_leaves[distance=7,persistent=true,waterlogged=false]"
        for support in (
            leaf,
            "minecraft:honey_block",
            "minecraft:stone_slab[type=bottom,waterlogged=false]",
        ):
            shape = "slab" if "_slab[" in support else "cube"
            self.assertFalse(covers.supported(button, support, shape))
            self.assertTrue(covers.supported("minecraft:red_carpet", support, shape))
            result = self.check({(0, 0, 0): support, (0, 1, 0): button})
            self.assertEqual(result["unsupported_covers"], 1)
            self.assertEqual(result["covered"], 0)
        for support in (
            "minecraft:stone",
            "minecraft:glass",
            "minecraft:tinted_glass",
            "minecraft:ice",
            "minecraft:slime_block",
            "minecraft:soul_sand",
        ):
            self.assertTrue(covers.supported(button, support))
        profile = catalog.bundled()["26.1.2"]
        honey = next(b for b in profile.blocks if b.state == "minecraft:honey_block")
        with self.assertRaisesRegex(ValueError, "sturdy support"):
            finish(
                layout.compose(
                    2,
                    2,
                    1,
                    {"floor": {}},
                    [honey],
                    profile,
                    cover_kind="BUTTON",
                    cover_state=button,
                )
            )


class TextureTests(unittest.TestCase):
    def test_archive_rejects_traversal_duplicates_and_oversized_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pack.zip"
            out = io.BytesIO()
            Image.new("RGBA", (16, 16), "red").save(out, format="PNG")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("assets/minecraft/textures/../escape.png", out.getvalue())
            with self.assertRaises(ValueError):
                texture_pack.Archive(path)
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("assets/example/textures/block/custom.png", out.getvalue())
            reader = texture_pack.Archive(path)
            self.assertEqual(reader.png("example:block/custom")[0], out.getvalue())
            reader.close()

    def test_texture_projection_uv_rotation_tint_and_missing_fallback(self):
        pixels = np.ones((16, 16, 4), np.float32)
        pixels[:8, :, :3] = [1, 0, 0]
        pixels[8:, :, :3] = [0, 0, 1]
        quad = {
            "side": "north",
            "from": [0, 0, 0],
            "to": [16, 16, 16],
            "uv": [0, 0, 16, 16],
            "rotation": 0,
            "texture": "demo:block/asymmetric",
            "tint": [1, 1, 1],
        }
        tiles, missing = texture_pack.render([[{"y": 90, "quads": [quad]}]], lambda _: pixels)
        self.assertFalse(missing)
        # A north-facing model rotated clockwise around Y points east.
        i = texture_pack.SIDES.index("east")
        self.assertGreater(tiles[i, :8, :, 0].mean(), 0.99)
        self.assertGreater(tiles[i, 8:, :, 2].mean(), 0.99)
        quad["uv"] = [0, 0, 16, 8]
        quad["tint"] = [0.5, 1, 1]
        tiles, _ = texture_pack.render([[{"quads": [quad]}]], lambda _: pixels)
        self.assertAlmostEqual(float(tiles[2, :, :, 0].mean()), 0.5, places=4)

        def missing_texture(_):
            raise KeyError("absent")

        tiles, missing = texture_pack.render([[{"quads": [quad]}]], missing_texture, (120, 100, 80))
        self.assertEqual(missing, {"demo:block/asymmetric"})


if __name__ == "__main__":
    unittest.main()
