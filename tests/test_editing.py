import unittest

from minecraft_builder.core.editing import Editor, empty_document, ray_pick

MATERIALS = {
    "minecraft:red_wool": ((180, 40, 35), "cube"),
    "minecraft:blue_wool": ((50, 55, 150), "cube"),
    "minecraft:oak_slab[type=bottom,waterlogged=false]": ((160, 130, 80), "slab"),
}


def editor():
    build = {
        "size": [3, 3, 3],
        "palette": ["minecraft:red_wool"],
        "colors": [[180, 40, 35]],
        "shapes": ["cube"],
        "masks": [255],
        "version": "26.1.2",
        "data_version": 4790,
        "cells": [[0, 0, 0, 0], [1, 0, 0, 0]],
        "warnings": [],
    }
    return Editor(build, empty_document(), MATERIALS, (8, 8, 8), 512)


class EditTests(unittest.TestCase):
    def test_add_delete_replace_move_undo_redo_and_persistence(self):
        e = editor()
        e.change({(0, 0, 0): "minecraft:blue_wool"})
        e.change({(1, 0, 0): None, (2, 2, 2): "minecraft:red_wool"})
        self.assertNotIn((1, 0, 0), e.cells)
        self.assertEqual(e.cells[0, 0, 0], "minecraft:blue_wool")
        e.undo()
        self.assertIn((1, 0, 0), e.cells)
        self.assertNotIn((2, 2, 2), e.cells)
        e.undo(True)
        self.assertIn((2, 2, 2), e.cells)
        restored = Editor(e.build, e.document, MATERIALS, e.limits, 512)
        self.assertEqual(restored.result(), e.result())
        with self.assertRaises(ValueError):
            e.change({(8, 0, 0): "minecraft:red_wool"})

    def test_half_block_picking_and_normals(self):
        e = editor()
        e.change({(1, 1, 1): "minecraft:oak_slab[type=bottom,waterlogged=false]"})
        hit = ray_pick(e.cells, e.materials, e.limits, (1.25, 4, 1.25), (0, -1, 0))
        self.assertEqual(hit[:2], ((1, 1, 1), (0, 1, 0)))
        self.assertIsNone(ray_pick(e.cells, e.materials, e.limits, (-1, 1.75, 1.25), (1, 0, 0)))
        self.assertEqual(
            ray_pick(e.cells, e.materials, e.limits, (-1, 1.25, 1.25), (1, 0, 0))[:2],
            ((1, 1, 1), (-1, 0, 0)),
        )

    def test_changed_dimensions_skip_but_retain_edits(self):
        e = editor()
        e.change({(7, 0, 0): "minecraft:blue_wool"})
        small = Editor(e.build, e.document, MATERIALS, (3, 3, 3), 512)
        self.assertEqual(small.skipped, ["7,0,0"])
        self.assertIn("7,0,0", small.document["patches"])
        small.change({(7, 0, 0): "@generated"})
        self.assertFalse(small.document["patches"])
        small.undo()
        self.assertIn("7,0,0", small.document["patches"])
        self.assertEqual(small.skipped, ["7,0,0"])

    def test_undo_restores_expanded_bounds(self):
        e = editor()
        e.change({(0, 0, 0): "minecraft:blue_wool"})
        before = e.result()
        e.change({(7, 0, 0): "minecraft:blue_wool"})
        self.assertEqual(e.result()["size"], [8, 3, 3])
        e.undo()
        self.assertEqual(e.result()["size"], before["size"])


if __name__ == "__main__":
    unittest.main()
