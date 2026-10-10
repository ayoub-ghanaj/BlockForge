# Palette audit — 0.4.0

Audited 47,572 block registry entries across all **51 stable Java releases
from 1.13 through 26.3**, current on 2026-10-03. Each ID has an explicit
outcome. There are **51 distinct newly supported IDs**, appearing in 1,984
additional version/material pairs. No previously included palette IDs were removed.

## Sources and method

- [Mojang release manifest](https://piston-meta.mojang.com/mc/game/version_manifest_v2.json): version coverage.
- [mcmeta](https://github.com/misode/mcmeta): tagged vanilla block registries, properties, models, textures and tint maps for 1.14 onward.
- [minecraft-data](https://github.com/PrismarineJS/minecraft-data): 1.13 registry/state data; Mojang SHA1-verified client assets supply its original textures.
- [Minecraft Wiki block list](https://minecraft.wiki/w/Java_Edition_data_values/Blocks): supplementary ID/name reference; per-version generated data is the primary source.
- [1.19.3](https://www.minecraft.net/fr-fr/article/minecraft-java-edition-1-19-3), [1.20.3](https://www.minecraft.net/en-us/article/minecraft-java-edition-1-20-3) and [1.21.2](https://www.minecraft.net/nl-nl/article/minecraft-java-edition-1-21-2) official notes: experimental availability gates.

Models resolve inheritance, boolean/OR/AND multipart conditions, weighted
variants, texture descriptors, UV cropping, face rotations and alpha layers.
Animation frames are averaged with their duration weights in linear light.
Grass/foliage use a Plains reference or fixed species tint. Source URLs and
hashes are committed in `tests/fixtures/palette-asset-sources.json.gz`.
Full audit outcomes are in `tests/fixtures/palette-coverage.json.gz`.

## Coverage by version

**Optional** is included in the palette total but disabled by default.
**Cover only** counts blocks available in Perimeter protection but not in
the artwork palette. **Remaining** includes technical/experimental IDs,
fluids, plants, entity renderers and shapes needing another geometry adapter.
Each linked CSV lists every registry ID, its outcome, cover role and available color.

| Java | Registry | Before | Palette | Added | Optional | Cover only | Remaining |
|---|---:|---:|---:|---:|---:|---:|---:|
| [26.3](palette-audit/26.3.csv) | 1286 | 573 | 624 | 51 | 47 | 75 | 587 |
| [26.2](palette-audit/26.2.csv) | 1196 | 502 | 550 | 48 | 44 | 72 | 574 |
| [26.1.2](palette-audit/26.1.2.csv) | 1168 | 481 | 529 | 48 | 44 | 72 | 567 |
| [26.1.1](palette-audit/26.1.1.csv) | 1168 | 481 | 529 | 48 | 44 | 72 | 567 |
| [26.1](palette-audit/26.1.csv) | 1168 | 481 | 529 | 48 | 44 | 72 | 567 |
| [1.21.11](palette-audit/1.21.11.csv) | 1166 | 481 | 529 | 48 | 44 | 72 | 565 |
| [1.21.10](palette-audit/1.21.10.csv) | 1166 | 481 | 529 | 48 | 44 | 72 | 565 |
| [1.21.9](palette-audit/1.21.9.csv) | 1166 | 481 | 529 | 48 | 44 | 72 | 565 |
| [1.21.8](palette-audit/1.21.8.csv) | 1105 | 481 | 529 | 48 | 44 | 72 | 504 |
| [1.21.7](palette-audit/1.21.7.csv) | 1105 | 481 | 529 | 48 | 44 | 72 | 504 |
| [1.21.6](palette-audit/1.21.6.csv) | 1105 | 481 | 529 | 48 | 44 | 72 | 504 |
| [1.21.5](palette-audit/1.21.5.csv) | 1104 | 481 | 529 | 48 | 44 | 72 | 503 |
| [1.21.4](palette-audit/1.21.4.csv) | 1095 | 481 | 529 | 48 | 44 | 72 | 494 |
| [1.21.3](palette-audit/1.21.3.csv) | 1084 | 467 | 514 | 47 | 43 | 69 | 501 |
| [1.21.2](palette-audit/1.21.2.csv) | 1084 | 467 | 514 | 47 | 43 | 69 | 501 |
| [1.21.1](palette-audit/1.21.1.csv) | 1060 | 467 | 514 | 47 | 43 | 69 | 477 |
| [1.21](palette-audit/1.21.csv) | 1060 | 467 | 514 | 47 | 43 | 69 | 477 |
| [1.20.6](palette-audit/1.20.6.csv) | 1060 | 440 | 479 | 39 | 35 | 61 | 520 |
| [1.20.5](palette-audit/1.20.5.csv) | 1060 | 440 | 479 | 39 | 35 | 61 | 520 |
| [1.20.4](palette-audit/1.20.4.csv) | 1058 | 440 | 479 | 39 | 35 | 61 | 518 |
| [1.20.3](palette-audit/1.20.3.csv) | 1058 | 440 | 479 | 39 | 35 | 61 | 518 |
| [1.20.2](palette-audit/1.20.2.csv) | 1003 | 440 | 479 | 39 | 35 | 61 | 463 |
| [1.20.1](palette-audit/1.20.1.csv) | 1003 | 440 | 479 | 39 | 35 | 61 | 463 |
| [1.20](palette-audit/1.20.csv) | 1003 | 440 | 479 | 39 | 35 | 61 | 463 |
| [1.19.4](palette-audit/1.19.4.csv) | 998 | 423 | 460 | 37 | 34 | 55 | 483 |
| [1.19.3](palette-audit/1.19.3.csv) | 972 | 423 | 460 | 37 | 34 | 55 | 457 |
| [1.19.2](palette-audit/1.19.2.csv) | 933 | 423 | 460 | 37 | 34 | 55 | 418 |
| [1.19.1](palette-audit/1.19.1.csv) | 933 | 423 | 460 | 37 | 34 | 55 | 418 |
| [1.19](palette-audit/1.19.csv) | 933 | 423 | 460 | 37 | 34 | 55 | 418 |
| [1.18.2](palette-audit/1.18.2.csv) | 898 | 405 | 440 | 35 | 32 | 52 | 406 |
| [1.18.1](palette-audit/1.18.1.csv) | 898 | 405 | 440 | 35 | 32 | 52 | 406 |
| [1.18](palette-audit/1.18.csv) | 898 | 405 | 440 | 35 | 32 | 52 | 406 |
| [1.17.1](palette-audit/1.17.1.csv) | 898 | 405 | 440 | 35 | 32 | 52 | 406 |
| [1.17](palette-audit/1.17.csv) | 898 | 405 | 440 | 35 | 32 | 52 | 406 |
| [1.16.5](palette-audit/1.16.5.csv) | 763 | 336 | 368 | 32 | 29 | 52 | 343 |
| [1.16.4](palette-audit/1.16.4.csv) | 763 | 336 | 368 | 32 | 29 | 52 | 343 |
| [1.16.3](palette-audit/1.16.3.csv) | 763 | 336 | 368 | 32 | 29 | 52 | 343 |
| [1.16.2](palette-audit/1.16.2.csv) | 763 | 336 | 368 | 32 | 29 | 52 | 343 |
| [1.16.1](palette-audit/1.16.1.csv) | 763 | 336 | 368 | 32 | 29 | 52 | 343 |
| [1.16](palette-audit/1.16.csv) | 763 | 336 | 368 | 32 | 29 | 52 | 343 |
| [1.15.2](palette-audit/1.15.2.csv) | 680 | 293 | 325 | 32 | 29 | 44 | 311 |
| [1.15.1](palette-audit/1.15.1.csv) | 680 | 293 | 325 | 32 | 29 | 44 | 311 |
| [1.15](palette-audit/1.15.csv) | 680 | 293 | 325 | 32 | 29 | 44 | 311 |
| [1.14.4](palette-audit/1.14.4.csv) | 676 | 290 | 321 | 31 | 28 | 44 | 311 |
| [1.14.3](palette-audit/1.14.3.csv) | 676 | 290 | 321 | 31 | 28 | 44 | 311 |
| [1.14.2](palette-audit/1.14.2.csv) | 676 | 290 | 321 | 31 | 28 | 44 | 311 |
| [1.14.1](palette-audit/1.14.1.csv) | 676 | 290 | 321 | 31 | 28 | 44 | 311 |
| [1.14](palette-audit/1.14.csv) | 676 | 290 | 321 | 31 | 28 | 44 | 311 |
| [1.13.2](palette-audit/1.13.2.csv) | 598 | 253 | 284 | 31 | 28 | 44 | 270 |
| [1.13.1](palette-audit/1.13.1.csv) | 593 | 253 | 284 | 31 | 28 | 44 | 265 |
| [1.13](palette-audit/1.13.csv) | 593 | 253 | 284 | 31 | 28 | 44 | 265 |

## Confirmed corrections

- Added red/brown mushroom blocks and mushroom stems to every supported release.
- Added chiseled bookshelves from 1.20 onward, not the experimental 1.19.x registrations.
- Added optional glass/stained glass, ice, leaves, grass, beacon, slime/honey and copper grates where released.
- Replaced the shared newest-version color source with each version’s own assets, including older textures.
- Ground covers now use version-specific textures instead of generic gray/dye colors.
- Excluded experimental copper trapdoors before 1.21 and preserved the pre-existing bamboo sapling classification.
- Tinted glass blocks lighting paths even though it is visually transparent.

## Scope and checks

Windows Blender 5.2.2 verifies the optional checkbox, exclusive palette,
generation and reload behavior in both workflows. Java 26.1.2 verifies
**2,853 exact shape volumes**, all **19,872 cells** through each of Axiom,
Litematica and WorldEdit, and all cells after placement. The gallery has
**529 palette materials**, a support platform and sealed water beneath
live coral. Runtime checks were not repeated in 51 separate game versions.

The initial shape audit caught cactus: its texture planes span a cell but
its actual selection shape is inset. It remains excluded. Old skull models
are renderer placeholders and are also excluded. Powder snow is not a solid
building surface. Bedrock, reinforced deepslate and command/technical blocks
remain deliberate exclusions; use a custom palette when appropriate.

The swatch is a representative color, not a photorealistic renderer.
Lighting, biome, transparency/background, material aging and block updates
can change the result. Live coral requires water; ice can melt. Per-face
colors are recorded, but conversion still matches the combined representative
color. Lever cover color uses its texture projection; its angled handle is
not a separate exact geometry adapter. Pre-1.13 and Bedrock remain unsupported.
