# Data and asset provenance

Minecraft Builder's original code is licensed under GPL-3.0-or-later; see
[LICENSE](LICENSE). That license does not grant rights to Minecraft, mod binaries,
resource packs, or models imported by a user.

## Bundled reference data

`minecraft_builder/data/` contains versioned block identifiers, legal states,
measured colors, cover information, and numeric geometry/texture-mapping recipes.
It contains no vanilla texture image files or game binaries.

- Modern registry reports and asset inputs come from
  [misode/mcmeta](https://github.com/misode/mcmeta), which documents their origin
  in Mojang's data generator and public APIs. No blanket GPL license is claimed
  over the underlying Minecraft content.
- Java 1.13 registry/property inputs also use
  [PrismarineJS/minecraft-data](https://github.com/PrismarineJS/minecraft-data).
  Its README declares MIT and notes that some source data has upstream terms.
- Texture measurements for older versions use explicit, hash-verified Mojang
  client downloads during development. These archives remain in local caches.

Per-version URLs and hashes are recorded in
`tests/fixtures/minecraft-reports-sources.json` and
`tests/fixtures/palette-asset-sources.json.gz`. See
[the palette audit](docs/PALETTE_AUDIT.md) for how inputs are processed.

Minecraft content remains subject to the
[Minecraft EULA](https://www.minecraft.net/en-us/eula) and applicable
[usage guidelines](https://www.minecraft.net/en-us/usage-guidelines).

## Examples and tests

The three images in `examples/perimeter-art/` were generated for this project;
their creation notes are stored in `PROMPTS.md`. They are provided with this
project under GPL-3.0-or-later. The other generic test images and meshes are
created by test code.

The ZIPs in `tests/fixtures/releases/` contain earlier versions of this project's
GPL add-on for upgrade regression tests. They are not game or mod distributions.

Local imported cat/skull models, packed vanilla-texture scenes, and their result
archives are excluded from the public source tree and release assets. Importing
an image or resource pack can pack its pixels into a saved Blender scene; check
the source asset's terms before sharing that scene.

Minecraft Builder is an independent project and is not affiliated with Mojang,
Microsoft, Blender, WorldEdit, Litematica, or Axiom.
