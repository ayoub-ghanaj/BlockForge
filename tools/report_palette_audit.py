"""Publish human-readable coverage tables from the tested audit records."""

import csv
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from minecraft_builder.catalog import bundled
from minecraft_builder.perimeter.covers import KINDS, choices


def main():
    audit = json.loads(
        gzip.decompress((ROOT / "tests/fixtures/palette-coverage.json.gz").read_bytes())
    )
    folder = ROOT / "docs/palette-audit"
    folder.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Palette audit — 0.4.0",
        "",
        "Audited 47,572 block registry entries across all **51 stable Java releases",
        "from 1.13 through 26.3**, current on 2026-10-03. Each ID has an explicit",
        "outcome. There are **51 distinct newly supported IDs**, appearing in 1,984",
        "additional version/material pairs. No previously included palette IDs were removed.",
        "",
        "## Sources and method",
        "",
        "- [Mojang release manifest](https://piston-meta.mojang.com/mc/game/version_manifest_v2.json): version coverage.",
        "- [mcmeta](https://github.com/misode/mcmeta): tagged vanilla block registries, properties, models, textures and tint maps for 1.14 onward.",
        "- [minecraft-data](https://github.com/PrismarineJS/minecraft-data): 1.13 registry/state data; Mojang SHA1-verified client assets supply its original textures.",
        "- [Minecraft Wiki block list](https://minecraft.wiki/w/Java_Edition_data_values/Blocks): supplementary ID/name reference; per-version generated data is the primary source.",
        "- [1.19.3](https://www.minecraft.net/fr-fr/article/minecraft-java-edition-1-19-3), [1.20.3](https://www.minecraft.net/en-us/article/minecraft-java-edition-1-20-3) and [1.21.2](https://www.minecraft.net/nl-nl/article/minecraft-java-edition-1-21-2) official notes: experimental availability gates.",
        "",
        "Models resolve inheritance, boolean/OR/AND multipart conditions, weighted",
        "variants, texture descriptors, UV cropping, face rotations and alpha layers.",
        "Animation frames are averaged with their duration weights in linear light.",
        "Grass/foliage use a Plains reference or fixed species tint. Source URLs and",
        "hashes are committed in `tests/fixtures/palette-asset-sources.json.gz`.",
        "Full audit outcomes are in `tests/fixtures/palette-coverage.json.gz`.",
        "",
        "## Coverage by version",
        "",
        "**Optional** is included in the palette total but disabled by default.",
        "**Cover only** counts blocks available in Perimeter protection but not in",
        "the artwork palette. **Remaining** includes technical/experimental IDs,",
        "fluids, plants, entity renderers and shapes needing another geometry adapter.",
        "Each linked CSV lists every registry ID, its outcome, cover role and available color.",
        "",
        "| Java | Registry | Before | Palette | Added | Optional | Cover only | Remaining |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for version, p in bundled().items():
        row = audit[version]
        blocks = {b.state.split("[")[0].split(":")[1]: b for b in p.blocks}
        covers = {}
        for kind, _, _ in KINDS:
            for b in choices(p, kind):
                covers[b.state.split("[")[0].split(":")[1]] = kind
        cover_only = set(covers) - set(blocks)
        with (folder / (version + ".csv")).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(
                (
                    "Block ID",
                    "Artwork outcome",
                    "Perimeter cover",
                    "RGB",
                    "Shape",
                    "Optional appearance",
                )
            )
            for name, status in sorted(row["decisions"].items()):
                b = blocks.get(name)
                writer.writerow(
                    (
                        "minecraft:" + name,
                        status,
                        covers.get(name, ""),
                        " ".join(map(str, b.rgb)) if b else "",
                        b.shape if b else "",
                        ";".join(b.appearance) if b else "",
                    )
                )
        remaining = row["registry_blocks"] - len(blocks) - len(cover_only)
        lines.append(
            f"| [{version}](palette-audit/{version}.csv) | {row['registry_blocks']} | {row['previous_palette']} | {len(blocks)} | {len(row['added'])} | {row['counts'].get('optional', 0)} | {len(cover_only)} | {remaining} |"
        )
    lines += [
        "",
        "## Confirmed corrections",
        "",
        "- Added red/brown mushroom blocks and mushroom stems to every supported release.",
        "- Added chiseled bookshelves from 1.20 onward, not the experimental 1.19.x registrations.",
        "- Added optional glass/stained glass, ice, leaves, grass, beacon, slime/honey and copper grates where released.",
        "- Replaced the shared newest-version color source with each version’s own assets, including older textures.",
        "- Ground covers now use version-specific textures instead of generic gray/dye colors.",
        "- Excluded experimental copper trapdoors before 1.21 and preserved the pre-existing bamboo sapling classification.",
        "- Tinted glass blocks lighting paths even though it is visually transparent.",
        "",
        "## Scope and checks",
        "",
        "Windows Blender 5.2.2 verifies the optional checkbox, exclusive palette,",
        "generation and reload behavior in both workflows. Java 26.1.2 verifies",
        "**2,853 exact shape volumes**, all **19,872 cells** through each of Axiom,",
        "Litematica and WorldEdit, and all cells after placement. The gallery has",
        "**529 palette materials**, a support platform and sealed water beneath",
        "live coral. Runtime checks were not repeated in 51 separate game versions.",
        "",
        "The initial shape audit caught cactus: its texture planes span a cell but",
        "its actual selection shape is inset. It remains excluded. Old skull models",
        "are renderer placeholders and are also excluded. Powder snow is not a solid",
        "building surface. Bedrock, reinforced deepslate and command/technical blocks",
        "remain deliberate exclusions; use a custom palette when appropriate.",
        "",
        "The swatch is a representative color, not a photorealistic renderer.",
        "Lighting, biome, transparency/background, material aging and block updates",
        "can change the result. Live coral requires water; ice can melt. Per-face",
        "colors are recorded, but conversion still matches the combined representative",
        "color. Lever cover color uses its texture projection; its angled handle is",
        "not a separate exact geometry adapter. Pre-1.13 and Bedrock remain unsupported.",
        "",
    ]
    (ROOT / "docs/PALETTE_AUDIT.md").write_text("\n".join(lines), encoding="utf-8")
    print("Wrote", len(audit), "complete block listings and coverage summary")


if __name__ == "__main__":
    main()
