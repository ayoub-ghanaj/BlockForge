# Perimeter Designer

Install **Minecraft Builder 0.5.1**, then open the 3D Viewport, press **N**, and
choose the separate **Perimeter** tab. Its settings, block list, preview and
exports belong to this workflow. Model conversion stays in the **Minecraft** tab.

## Six steps

1. **Size** — choose the destination Minecraft version and a floor, single wall,
   or full perimeter. Enter interior width, length and wall height in blocks.
   **Create / Update Perimeter Guide** draws the space for your decorations.
2. **Images and materials** — select Floor, North, South, West or East. Enable
   the surfaces you want and choose an image for each. With no image, the surface
   uses the plain/padding color. Wall images face inward. Flip controls adjust
   their orientation. **Use Image Size** gives one image pixel per block.
   Choose blocks with **Use only checked**, **Use only search results**, direct
   Include/Exclude rules, or **Survival obtainable**. Images use full cubes;
   enabled slabs/stairs can be used by decorations.
3. **3D decorations** — select mesh objects and click **Add selected meshes**.
   Position them inside the guide: Blender X is width, -Y is length, +Z is up.
   One meter of source geometry becomes one Minecraft block. The optional
   **Fit Decorations to Center** button moves and scales the listed objects to
   the entered decoration dimensions; Blender Undo restores those transforms.
   Choose hollow/solid, shell thickness, slabs, stairs and shape preference.
4. **Cover and lighting** — choose Ground cover (default), Lighting, both, or None.
   Covers include glass, buttons, carpet, bottom slabs, closed bottom trapdoors,
   persistent leaves, rails, pressure plates and levers. The material menu follows
   the chosen Minecraft version. Glass offers clear glass and all 16 stained colors.
   Buttons/rails/plates/levers need a sturdy top; honey and leaves cannot support
   them. Unsupported choices are rejected with alternatives. Bottom slabs/stairs already
   lack a full spawnable top. Leaves remain persistent. Rails can automatically
   change orientation when neighboring rails are placed in Minecraft.
   Lighting can match the artwork color using several level-15 materials, or use
   your selected block, including sea lanterns, glowstone, shroomlights, froglights,
   jack o'lanterns and crying obsidian when available in the selected version.
   Treatment materials are separate choices from the artwork allow-list.
5. **Preview** — generate, inspect, and regenerate after changing images, meshes
   or settings. The preview appears beside the guide. **Preview: 1 meter per block**
   is enabled by default. Disable it for a compact display. The checkbox changes
   display scale, not the exported dimensions. Glass is drawn as translucent caps;
   flat image faces omit hidden/back faces. Exports contain complete blocks.
6. **Export** — choose WorldEdit `.schem`, Litematica `.litematic`, or Axiom `.bp`.
   All three use the same saved perimeter. Export a CSV for the block counts.

Large previews can take a minute. Esc cancels between stages. Export keeps the
previous completed preview if generation fails. Blender scene units are honored;
after changing the scene's unit scale, regenerate or toggle the preview checkbox.

## Image sizing

| Option | Behavior |
|---|---|
| Stretch | Resize independently in each direction to cover the surface. |
| Fit + pad | Keep proportions and fill unused space with the padding color. |
| Fill + crop | Keep proportions, cover the surface, crop the overflow. |
| Crop at 1:1 | Keep one pixel per block; center and crop, padding if smaller. |
| Pad at 1:1 | Center at one pixel per block; reject images larger than the surface. |

Transparent image pixels blend with the plain/padding color. **Match visible block
faces** uses top colors for floors and inward-face colors for walls, selecting
legal orientations. The optional texture importer adds textured display without
changing the palette or export. See [appearance and editing](FEATURES_050.md).

An exact **650×400 floor** exports as 650×1×400, or **650×2×400 with glass**.
A **600×64 single wall** exports as 600×64×1 without protection. Full perimeter
dimensions describe the interior: a 650×400 interior with 64-high walls and
glass occupies **652×66×402** including outside walls, floor and cover.

## Protection and limits

Lighting targets block light **at least 1 for Java 1.18+**, or **at least 8 for
older presets**. It considers existing emitters and clear paths around decorations,
then replaces some art pixels with chosen light blocks. Partial shapes may gain a
light above. Color matching uses multiple lights rather than always glowstone.
For one 32×32 test design, modern rules required 4 added sea lanterns; the same
image with the 1.17 rule required 30. Counts depend on the image and geometry.

The modern darkness rule follows the [Mojang 1.18 generation changes](https://www.minecraft.net/en-us/article/new-world-generation-java-available-testing).
Light alone does not stop slime-chunk spawning. Use a ground cover for that
surface. The game tests check valid support and both zombie/slime ground placement
with collision; this is not a promise about every mob, spawner or raid mechanic.
Water, farmland and dirt-path conversion are not treatment options in this release.

Use [live block editing](LIVE_EDITING.md) in Step 5 for manual corrections. After
adding, moving or deleting blocks, run **Check Current Protection**. Enable
**Require dry ground protection** for cover checks; disable it for lighting alone. The report
counts all issues and outlines up to 10,000 problem cells. Edits and regeneration
invalidate the previous check. It reports conservative light coverage and supported
ground protection, without changing any blocks or simulating world-specific spawns.
The lever preview approximates its base/handle; exported block states are exact.

- Width/length: up to 2,048; wall height: up to 256.
- At most 64 million bounding cells and two million placed blocks, including cover.
- Each decoration: at most 512 blocks per axis / two million bounding cells.
- Preview: at most 1.5 million faces. Source image: at most 32 million pixels.
- Closed meshes give the most reliable decoration volume. Inspect thin/open geometry.
- Java 1.13+ palettes; only Java 26.1.2 has actual game/mod checks in this release.

## Reproduce an example

Run `tests/blender_perimeter.py` in a fresh Blender process, following
[DEVELOPMENT.md](DEVELOPMENT.md). It generates small floor/wall fixtures,
decorations, and all three export formats under `build/perimeter/`.

`tests/blender_art.py` optionally uses the three generated input images in
`examples/perimeter-art/` to exercise floor, wall, and combined layouts.
Their provenance is recorded alongside the images. Generated scenes and reports
stay in ignored local output directories.
