"""Coverage regressions, optional-choice policy and independent synthetic assets."""

import base64
import gzip
import io
import json
import unittest
from pathlib import Path

from PIL import Image

from minecraft_builder import catalog
from minecraft_builder.core.palette import allowed_blocks, parse_document, profile_document
from tools.build_palettes import release_enabled
from tools.palette_assets import Assets

ROOT = Path(__file__).resolve().parents[1]


class CoverageTests(unittest.TestCase):
    def test_every_registry_id_has_an_audited_outcome(self):
        audit = json.loads(
            gzip.decompress((ROOT / "tests/fixtures/palette-coverage.json.gz").read_bytes())
        )
        refs = json.loads(
            gzip.decompress((ROOT / "tests/fixtures/minecraft-reports.json.gz").read_bytes())
        )
        self.assertEqual(set(audit), set(catalog.bundled()))
        for version, profile in catalog.bundled().items():
            row = audit[version]
            self.assertEqual(set(row["decisions"]), set(refs[version]), version)
            self.assertFalse(row["errors"], version)
            included = {
                n for n, status in row["decisions"].items() if status in ("included", "optional")
            }
            self.assertEqual(
                included, {b.state.split("[")[0].split(":")[1] for b in profile.blocks}, version
            )
            self.assertEqual(row["data_version"], profile.data_version)

    def test_multipart_materials_are_present_in_the_right_releases(self):
        for version, profile in catalog.bundled().items():
            names = {b.state.split("[")[0].split(":")[1] for b in profile.blocks}
            self.assertTrue(
                {"brown_mushroom_block", "red_mushroom_block", "mushroom_stem"} <= names, version
            )
            self.assertEqual(
                "chiseled_bookshelf" in names,
                tuple(map(int, version.split("."))) >= (1, 20),
                version,
            )
            self.assertFalse(any(n.endswith(("_head", "_skull")) for n in names), version)
            self.assertNotIn("powder_snow", names)

    def test_optional_colors_are_off_by_default_and_roundtrip(self):
        profile = catalog.bundled()["26.1.2"]

        def names(blocks):
            return {block.state.split("[")[0] for block in blocks}

        self.assertNotIn("minecraft:glass", names(allowed_blocks(profile.blocks)))
        self.assertNotIn("minecraft:grass_block", names(allowed_blocks(profile.blocks)))
        self.assertIn("minecraft:glass", names(allowed_blocks(profile.blocks, allow_special=True)))
        self.assertIn(
            "minecraft:grass_block", names(allowed_blocks(profile.blocks, allow_special=True))
        )
        self.assertEqual(parse_document(profile_document(profile))[profile.id], profile)

    def test_experimental_covers_are_not_offered_early(self):
        from minecraft_builder.perimeter.covers import choices

        for version in (
            "1.19.3",
            "1.19.4",
            "1.20.3",
            "1.20.4",
            "1.20.5",
            "1.20.6",
            "1.21.2",
            "1.21.3",
        ):
            for kind in ("TRAPDOOR", "BUTTON", "LEAVES", "PLATE"):
                for block in choices(catalog.bundled()[version], kind):
                    self.assertTrue(
                        release_enabled(block.state.split("[")[0].split(":")[1], version),
                        block.state,
                    )

    def test_tinted_glass_does_not_transmit_protection_light(self):
        from minecraft_builder.perimeter.covers import blocks_light
        from minecraft_builder.perimeter.layout import lit_path

        self.assertTrue(lit_path((2, 0, 0), (0, 0, 0), {(1, 0, 0): 0}, ["minecraft:glass"]))
        self.assertFalse(lit_path((2, 0, 0), (0, 0, 0), {(1, 0, 0): 0}, ["minecraft:tinted_glass"]))
        self.assertTrue(blocks_light("minecraft:tinted_glass"))


class AssetReaderTests(unittest.TestCase):
    def fixture(self, model, texture, blockstate=None, extra=None):
        data = {
            "assets/minecraft/models/block/test.json": json.dumps(model).encode(),
            "assets/minecraft/blockstates/test.json": json.dumps(
                blockstate or {"variants": {"": {"model": "block/test"}}}
            ).encode(),
        }
        out = io.BytesIO()
        texture.save(out, format="PNG")
        data["assets/minecraft/textures/block/test.png"] = out.getvalue()
        data.update(extra or {})
        return Assets({"files": {p: base64.b64encode(v).decode() for p, v in data.items()}})

    def cube(self):
        return {
            "textures": {"all": {"sprite": "#base"}, "base": "block/test"},
            "elements": [
                {
                    "from": [0, 0, 0],
                    "to": [16, 16, 16],
                    "faces": {
                        s: {"texture": "#all"}
                        for s in ("up", "down", "east", "west", "north", "south")
                    },
                }
            ],
        }

    def test_descriptor_aliases_and_boolean_multipart(self):
        a = self.fixture(
            self.cube(),
            Image.new("RGBA", (16, 16), (32, 96, 160, 255)),
            {"multipart": [{"when": {"present": True}, "apply": {"model": "block/test"}}]},
        )
        color, faces, flags = a.measure("test", {"present": "true"}, "cube", "minecraft:test")
        self.assertEqual(color, [32, 96, 160])
        self.assertFalse(flags)
        self.assertEqual(set(map(tuple, faces.values())), {(32, 96, 160)})

    def test_uv_crop_ignores_unused_texture_pixels(self):
        model = self.cube()
        for face in model["elements"][0]["faces"].values():
            face["uv"] = [0, 0, 8, 16]
        tex = Image.new("RGBA", (16, 16), "blue")
        tex.paste((255, 0, 0, 255), (0, 0, 8, 16))
        color, _, _ = self.fixture(model, tex).measure("test", {}, "cube", "minecraft:test")
        self.assertEqual(color, [255, 0, 0])

    def test_animation_duration_and_transparent_overlay(self):
        tex = Image.new("RGBA", (16, 32), "blue")
        tex.paste((255, 0, 0, 255), (0, 0, 16, 16))
        meta = {"animation": {"frames": [{"index": 0, "time": 1}, {"index": 1, "time": 3}]}}
        a = self.fixture(
            self.cube(),
            tex,
            extra={"assets/minecraft/textures/block/test.png.mcmeta": json.dumps(meta).encode()},
        )
        color, _, _ = a.measure("test", {}, "cube", "minecraft:test")
        # Independent linear-light weighted red/blue expectation.
        expected = [
            round(255 * (1.055 * x ** (1 / 2.4) - 0.055)) if x else 0 for x in (0.25, 0, 0.75)
        ]
        self.assertEqual(color, expected)
        a = self.fixture(self.cube(), Image.new("RGBA", (16, 16), (40, 80, 120, 128)))
        color, _, flags = a.measure("test", {}, "cube", "minecraft:test")
        self.assertEqual(color, [40, 80, 120])
        self.assertEqual(flags, ["transparent"])


if __name__ == "__main__":
    unittest.main()
