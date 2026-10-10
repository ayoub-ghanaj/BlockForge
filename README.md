# BlockForge — Minecraft Builder for Blender

Convert selected colored or UV-textured meshes into a bounded Minecraft build,
preview it in Blender, and export WorldEdit **`.schem`**, Litematica **`.litematic`**
or native Axiom **`.bp`**.

**Install:** [download the latest release](https://github.com/ayoub-ghanaj/BlockForge/releases/latest)
using Blender's **Preferences → Add-ons → Install from Disk**.
The panel is in **3D Viewport → N sidebar → Minecraft**.
For the local workspace, the ZIP is `dist/minecraft_builder-0.5.3.zip`.

Version 0.5.3 supports Hue/Saturation/Value color adjustments and Point Mapping
nodes on UV textures, including reroutes. Node controls must use constant values.
The viewport provides **Pick Block** and **Select Area (2 Clicks)** buttons; shortcuts are optional.

Version 0.5.0 adds [visible-face matching, textured previews, bulk editing and
protection rechecks](docs/FEATURES_050.md). All 51 presets use their own block assets and registries.
See [palette coverage and exclusions](docs/PALETTE_AUDIT.md). Glass, leaves and
biome-colored materials are optional; solid artwork materials remain the default.

[Step-by-step guide](QUICKSTART.md) · [Palette format](docs/PALETTES.md) ·
[Perimeter Designer](docs/PERIMETER.md) · [Live block editing](docs/LIVE_EDITING.md) ·
[Development](docs/DEVELOPMENT.md)

[Builds and releases](docs/GITHUB.md) · [GitHub Actions](https://github.com/ayoub-ghanaj/BlockForge/actions)

## Features

- Separate guided **Perimeter** tab for image floors/walls, 3D decorations,
  nine ground-cover families and version-aware lighting; independent preview and exports.
- Live block picking, add/delete/repaint, snapped dragging, coordinates and Undo/Redo
  in both workflows; optional preservation of edits on regeneration.
- Box selection, radius brushes, fill/replace/delete, copy/paste and mirroring.
- Visible-face color matching and legal directional block orientations.
- Optional textured previews from a manually imported ZIP; packed preview atlases.
- Recheck edited perimeter cover and lighting with highlighted issues.
- Clear/stained glass choices and color-matched or selected light materials.
- **Preview: 1 meter per block** checkbox, respecting Blender scene units.
- **Use only checked / Use only search results** builds an exclusive allow-list.
- Maximum width/height/depth; optional preservation of proportions.
- Full cubes, slabs and stairs, including neighbor-dependent stair corners.
- Hollow or solid builds; hollow default; shell thickness and interior material.
- Direct per-row rules, multi-selection, literal/regex search and filtered bulk actions.
- Survival obtainable material preset, categories and whitelist mode.
- Six source-up directions; export catches preview-only rotations/scaling.
- Material/image/attribute colors, perceptual matching, shape/color preference.
- One saved preview shared by all export formats; material counts as CSV.
- 51 bundled Java version presets, **1.13 through 26.3**.
- Palette JSON import/export for resource packs, new releases or modded materials.
- Offline add-on. No game-directory scanning, network requests or game changes.

New scenes require an explicit Minecraft version choice. Saved scenes retain
their version across preset updates. The export filename includes the selected version. Regenerate after changing it.

## Verification

Tested in **Blender 5.2.2 LTS** and an isolated **Minecraft Java 26.1.2** Fabric
instance with Axiom 6.0.5, Litematica 0.27.14, WorldEdit 7.4.3 and dependencies.
Tests use actual mod readers and compare 3,076 shape variants with the game.
Small exports compare every cell; the largest sparse perimeter compares every
placed block plus sampled air. Separate checks cover real viewport mouse/keyboard
edits, saved scenes, ground-cover support/collision and world block light.
These are historical acceptance results. Run the documented checks in
[DEVELOPMENT.md](docs/DEVELOPMENT.md) to verify a new checkout; CI covers Python
and Blender without launching Minecraft.

Other presets have registry/property validation; they have not each been tested
in a separately launched historical game. Blender 4.2+ is the package target;
5.2.2 is the version exercised here.

## Current boundaries

- Java Edition only. Pre-1.13 numeric schematics and Bedrock are not implemented.
- Model color matching uses full cubes, slabs and stairs. Perimeter treatments
  additionally provide specific glass and ground-cover shapes. Biome tint and
  arbitrary model block shapes are not fitted automatically.
- Bake unsupported procedural materials to a UV base-color image.
- Colors and face projections use each version's own vanilla textures. Resource
  packs may require an imported or edited color palette. Texture display imports
  affect appearance only; they do not replace palette matching colors.
- Thin or open geometry can need cleanup; inspect generated previews.
- Model limits: two million bounding cells, 512 blocks per axis, eight million
  evaluated triangles and 1.2 million preview faces. Perimeters support 64 million
  bounding cells / two million placed blocks; see the perimeter guide for limits.

## Development

`minecraft_builder/` is the installable extension. Python/NumPy are provided by
Blender. Development tests additionally use `nbtlib`; palette generation uses
Pillow. Development tools are intentionally excluded from the add-on ZIP.

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m ruff check minecraft_builder tests tools
python3 -m unittest discover -s tests -v
python3 tools/package_addon.py
```

See [DEVELOPMENT.md](docs/DEVELOPMENT.md) for the code map, formatting rules,
Blender tests, and optional Minecraft acceptance harness.

Code license: [GPL-3.0-or-later](LICENSE). Data provenance and asset boundaries are
listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). This is an independent
add-on, not an official Minecraft product.
