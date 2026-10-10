"""Perimeter image geometry and streaming export regressions."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
from test_core import expected, fixture, read_bp, read_litematic, read_schem

from minecraft_builder import catalog
from minecraft_builder.core.palette import Block
from minecraft_builder.perimeter import layout, streaming
from minecraft_builder.perimeter.materials import emission

RED = (177, 46, 38)
BLUE = (53, 57, 157)
BLOCKS = (Block("minecraft:red_wool", RED), Block("minecraft:blue_wool", BLUE))
PROFILE = catalog.bundled()["26.1.2"]


def compose(*args, **kwargs):
    for stage, value in layout.compose(*args, **kwargs):
        if stage == "result":
            return value
    raise AssertionError("No perimeter result")


class PerimeterTests(unittest.TestCase):
    def test_streaming_readers_and_long_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            for count in (1, 4, 17, 260):
                build = fixture(count)
                want = expected(build)
                for kind, reader in [
                    ("schem", read_schem),
                    ("litematic", read_litematic),
                    ("bp", lambda d: read_bp(d, build["size"])),
                ]:
                    path = Path(directory) / ("test." + kind)
                    streaming.write(path, build, kind)
                    self.assertEqual(reader(path.read_bytes()), want)

    def test_streaming_crosses_chunks(self):
        build = fixture(17)
        build["size"] = [130, 7, 130]
        build["cells"] = [[0, 0, 0, 0], [15, 2, 129, 16], [129, 6, 129, 7], [129, 0, 0, 4]]
        with tempfile.TemporaryDirectory() as directory:
            for kind, reader in [
                ("schem", read_schem),
                ("litematic", read_litematic),
                ("bp", lambda d: read_bp(d, build["size"])),
            ]:
                path = Path(directory) / ("test." + kind)
                streaming.write(path, build, kind)
                self.assertEqual(reader(path.read_bytes()), expected(build))

    def test_large_sparse_bounds_do_not_allocate_dense_volume(self):
        build = fixture(1)
        build["size"] = [652, 67, 402]
        build["cells"] = [[1, 0, 1, 0], [650, 65, 400, 0]]
        streaming.validate(build)
        dense = streaming.DenseChunks(build)
        self.assertLess(dense.positions.nbytes + dense.values.nbytes, 100)
        self.assertEqual(sum(len(c) for c in dense), 652 * 67 * 402)
        self.assertEqual(sum(int(c.sum()) for c in dense), 2)

    def test_sizing_options(self):
        pixels = np.array([[RED, BLUE]], dtype=np.uint8)
        np.testing.assert_array_equal(layout.fit_image(pixels, 2, 1), pixels)
        fit = layout.fit_image(pixels, 2, 3, "FIT", (0, 0, 0))
        np.testing.assert_array_equal(fit[1], pixels[0])
        self.assertFalse(fit[0].any())
        self.assertFalse(fit[2].any())
        stretch = layout.fit_image(pixels, 2, 3, "STRETCH")
        for row in stretch:
            np.testing.assert_array_equal(row, pixels[0])
        fill = layout.fit_image(pixels, 2, 3, "FILL")
        self.assertTrue(fill.any())
        crop = layout.fit_image(np.tile(pixels, (3, 2, 1)), 2, 1, "CROP")
        self.assertEqual(crop.shape, (1, 2, 3))
        with self.assertRaises(ValueError):
            layout.fit_image(pixels, 1, 1, "PAD")
        padded = layout.fit_image(pixels, 4, 3, "PAD", (0, 0, 0))
        np.testing.assert_array_equal(padded[1, 1:3], pixels[0])

    def test_inside_wall_orientation_and_exact_palette(self):
        pixels = np.array([[RED, BLUE], [BLUE, RED]], dtype=np.uint8)
        faces = {f: {"pixels": pixels, "mode": "STRETCH"} for f in layout.FACES}
        build = compose(2, 2, 2, faces, BLOCKS, PROFILE, background=BLUE, protection="NONE")
        cells = expected(build)
        for face in layout.FACES:
            for row in range(2):
                for col in range(2):
                    pos = layout.face_position(face, col, row, 2, 2, 2)
                    self.assertEqual(
                        cells[pos], "minecraft:red_wool" if row == col else "minecraft:blue_wool"
                    )
        self.assertEqual(set(build["palette"]), {"minecraft:red_wool", "minecraft:blue_wool"})

    def test_glass_covers_floor_wall_and_decoration_tops(self):
        decoration = {
            "palette": ["minecraft:blue_wool"],
            "colors": [BLUE],
            "shapes": ["cube"],
            "cells": [[0, 0, 0, 0], [0, 1, 0, 0]],
        }
        build = compose(
            4,
            4,
            4,
            {"floor": {}},
            BLOCKS,
            PROFILE,
            protection="GLASS",
            decorations=[(decoration, (1, 0, 1))],
        )
        cells = expected(build)
        self.assertEqual(cells[1, 3, 1], "minecraft:glass")
        self.assertEqual(cells[0, 1, 0], "minecraft:glass")
        self.assertEqual(cells[1, 1, 1], "minecraft:blue_wool")
        self.assertEqual(build["perimeter"]["protection"]["glass_blocks"], 16)

    def test_lights_cover_uneven_exposed_surfaces(self):
        decoration = {
            "palette": ["minecraft:blue_wool"],
            "colors": [BLUE],
            "shapes": ["cube"],
            "cells": [[x, y, z, 0] for x in range(3) for y in range(6) for z in range(3)],
        }
        build = compose(
            18,
            12,
            8,
            {"floor": {}, "north": {}},
            BLOCKS,
            PROFILE,
            protection="LIGHTS",
            decorations=[(decoration, (4, 0, 3))],
        )
        states = build["palette"]
        cells = {(x, y, z): i for x, y, z, i in build["cells"]}
        lights = [p for p, i in cells.items() if emission(states[i])]
        self.assertTrue(lights)
        for target in build["perimeter"]["protection"]["light_checks"]:
            self.assertTrue(
                any(
                    sum(abs(a - b) for a, b in zip(source, target))
                    <= emission(states[cells[source]]) - 1
                    and layout.lit_path(tuple(target), source, cells, states)
                    for source in lights
                ),
                target,
            )
        self.assertTrue(build["warnings"])

    def test_version_aware_light_spacing_and_materials(self):
        old = compose(
            50,
            50,
            8,
            {"floor": {}},
            BLOCKS,
            catalog.bundled()["1.17"],
            protection="LIGHTS",
            light_state="minecraft:sea_lantern",
        )
        new = compose(
            50,
            50,
            8,
            {"floor": {}},
            BLOCKS,
            PROFILE,
            protection="LIGHTS",
            light_state="minecraft:sea_lantern",
        )
        self.assertEqual(old["perimeter"]["protection"]["light_threshold"], 8)
        self.assertEqual(new["perimeter"]["protection"]["light_threshold"], 1)
        self.assertLess(
            new["perimeter"]["protection"]["light_blocks"],
            old["perimeter"]["protection"]["light_blocks"] / 2,
        )
        self.assertIn("minecraft:sea_lantern", new["palette"])
        self.assertNotIn("minecraft:glowstone", new["palette"])
        glass = compose(
            4, 4, 4, {"floor": {}}, BLOCKS, PROFILE, glass_state="minecraft:blue_stained_glass"
        )
        self.assertIn("minecraft:blue_stained_glass", glass["palette"])
        self.assertNotIn("minecraft:glass", glass["palette"])

    def test_out_of_bounds_decoration_fails(self):
        decoration = {
            "palette": ["minecraft:blue_wool"],
            "colors": [BLUE],
            "shapes": ["cube"],
            "cells": [[0, 0, 0, 0]],
        }
        with self.assertRaisesRegex(ValueError, "leaves the interior"):
            compose(4, 4, 4, {"floor": {}}, BLOCKS, PROFILE, decorations=[(decoration, (10, 0, 0))])

    def test_single_wall_keeps_requested_image_width(self):
        build = compose(600, 400, 64, {"north": {}}, BLOCKS, PROFILE, protection="NONE")
        self.assertEqual(build["size"], [600, 64, 1])
        self.assertEqual(len(build["cells"]), 600 * 64)
        floor = compose(650, 400, 64, {"floor": {}}, BLOCKS, PROFILE, protection="GLASS")
        self.assertEqual(floor["size"], [650, 2, 400])


if __name__ == "__main__":
    unittest.main()
