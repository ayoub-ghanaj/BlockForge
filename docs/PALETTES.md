# Palette files and version updates

The add-on loads bundled numeric palettes and optional **UTF-8 JSON** files.
Import never examines the Minecraft installation or downloads textures.

Choose **Import palette** in the Minecraft sidebar. A custom profile appears in
the Minecraft version selector. Importing the same profile ID replaces that
profile; to make a variant, use a distinct ID such as `26.1.2 - My resource pack`.
Imported profiles are stored in the scene and saved with the `.blend`.

## Minimal example

A ready-to-import copy is in [examples/palette-26.1.2.json](../examples/palette-26.1.2.json).

```json
{
  "schema_version": 1,
  "profiles": [
    {
      "id": "26.1.2 - Custom stone",
      "data_version": 4790,
      "blocks": [
        {"state": "minecraft:stone", "rgb": [128, 128, 128], "shape": "cube", "category": "Stone"},
        {"state": "minecraft:stone_slab[type=bottom,waterlogged=false]", "rgb": [128, 128, 128], "shape": "slab", "category": "Stone"},
        {"state": "minecraft:stone_stairs[facing=north,half=bottom,shape=straight,waterlogged=false]", "rgb": [128, 128, 128], "shape": "stairs", "category": "Stone"}
      ]
    }
  ]
}
```

`rgb` is a representative **sRGB** color, three integers from 0 to 255.
`state` is a namespaced block ID and its default properties. State names and
properties must exist in the target version. The importer validates structure
and syntax; custom mod IDs cannot be checked against an installation it never reads.

## How sizes work

Minecraft's grid is always one block per cell. Geometry comes from `shape`:

| Shape | Geometry chosen by the converter |
|---|---|
| `cube` | Full 1 × 1 × 1 cell |
| `slab` | Bottom or top half of a cell |
| `stairs` | Four directions, bottom/top, neighbor-resolved corners |

No pixel size needs to be imported. The Blender model is fitted to your chosen
block limits, sampled at half-block resolution, and compared with those shapes.
Setting a modded block's shape means it must obey the same state and geometry
conventions. Other custom shapes need an adapter; labeling them `cube` does not
make the game render them as cubes.

## How colors are obtained

- **Bundled presets:** a development tool uses each release's own vanilla assets,
  resolving model inheritance, multipart conditions, texture descriptors, UV
  crops, rotations, transparent layers and animation timing. It averages the six
  projected faces in linear light and stores numeric sRGB records. No textures
  are included in the add-on.
- **Imported palette:** colors are supplied by the JSON file. They are not
  inferred from the block name or from your local game.
- **Your source model:** the converter samples UV image colors, flat Principled
  colors or color attributes, then compares them to eligible block colors in
  OKLab space. The shape slider controls the geometry/color tradeoff.
- **Manual edits:** edit a block's color swatch, then export the allowed palette.

The file can optionally include `gravity: true` and a `faces` object with
`up/down/north/south/east/west` RGB triples. Falling materials are excluded unless
enabled in the UI. **Match visible block faces** uses these face colors; disabling
it uses representative `rgb`. The optional `variants` array supplies legal rotated
states and their world-oriented face colors:

```json
{"state":"minecraft:oak_log[axis=y]","rgb":[109,85,50],
 "variants":[{"state":"minecraft:oak_log[axis=x]",
 "faces":{"up":[109,85,50],"down":[109,85,50],"north":[109,85,50],
          "south":[109,85,50],"east":[151,121,73],"west":[151,121,73]}}]}
```

The example numbers are illustrative; exported bundled presets contain measured
colors. Variants must use the same block ID, with at most 48 variants per record.
The importer validates syntax, not custom mod semantics. Omitting variants retains
the original default cube state and standard slab/stair orientations.

Optional `appearance` flags are `transparent` and `biome_tinted`. Such blocks are
excluded until **Allow glass / biome colors** is checked, even when explicitly
included in a whitelist. Grass and biome-tinted foliage use a Plains reference;
spruce, birch and mangrove use their fixed foliage tints. Transparency averages
visible texture color without imposing a background. These choices remain
approximations of the destination world's lighting, biome and neighboring blocks.
Leaves use `persistent=true` to prevent decay.

## Updating a Minecraft release

1. Run `python tools/palette_sources.py` to fetch compact per-version block assets
   and generated reports into the ignored development cache. It checks the official
   release list and reports missing version presets. It never opens the user's game.
2. Run `python tools/build_palettes.py`, `python tools/build_cover_presets.py`,
   then `python tools/build_visual_metadata.py` to add directional face colors
   and numeric texture recipes. The final step must follow base palette generation.
   Unknown asset failures stop the build. Every registry ID has an explicit audit
   outcome; experimental blocks stay unavailable before their normal release.
3. Run offline tests and Blender integration checks. For new shapes, use
   `tools/prepare_palette_verification.py` and the real Minecraft verifier.
4. Bundle the new preset in an add-on update, or distribute it as a small JSON.

Existing saved snapshots retain their original version and block states. A
version change requires regenerating the preview. This avoids silently changing
an old build when installing a palette update.

## Survival material preset

The built-in **Survival obtainable** button sets Include/Exclude rules and enables
whitelist mode. It excludes infested blocks, budding amethyst, suspicious sand/
gravel, petrified oak slabs and technical/creative-only materials. On 1.13 presets,
it also excludes smooth full blocks whose normal smelting recipes arrived in 1.14.
Rare resources and Silk Touch materials remain eligible. Modded namespaces are
excluded until you explicitly include them. This is a material filter; it does
not simulate survival placement costs, water requirements or block updates.

Maintenance references: Mojang's [18w43 changelog](https://feedback.minecraft.net/hc/en-us/articles/360018363512-Minecraft-Java-Edition-Snapshot-18W43C)
for smooth-block recipes, and [amethyst shard guide](https://www.minecraft.net/fr-fr/article/taking-inventory--amethyst-shard)
for budding amethyst's collection restriction. Review the exclusion rules when
adding versions; normal survival excludes command access and bug exploits.

## Validation limits

Files: 16 MiB maximum, 256 profiles, 10,000 blocks per profile, 200,000 entries
total. Duplicate states, malformed properties, air color choices and invalid RGB
values are rejected. Supported bundled era starts at Java 1.13; this release does
not implement the older numeric-ID `.schematic` adapter.

Reference data: [mcmeta](https://github.com/misode/mcmeta),
[minecraft-data](https://github.com/PrismarineJS/minecraft-data).
All 51 presets now use version-exact vanilla assets, including the older pre-1.14
texture style. Sources, hashes, counts and exclusions are recorded in the
[palette audit](PALETTE_AUDIT.md). Custom shapes such as doors, fences, plants and
entity-rendered blocks still need geometry adapters; their absence is explicit.
