# Install and try Minecraft Builder

## Install in Blender

1. Download `minecraft_builder-0.5.3.zip` from [Releases](https://github.com/ayoub-ghanaj/BlockForge/releases/latest), or build it locally in `dist/`. **Keep it zipped.**
2. Open **Edit → Preferences → Add-ons**.
3. Open the small **▼ menu at the top right → Install from Disk**.
4. Choose the ZIP and enable **Minecraft Builder** if it is not already enabled.
5. Return to the 3D Viewport. Press **N**, then click the **Minecraft** tab.

Before updating, save your .blend. Install the new ZIP and restart Blender.
Version 0.3.1 fixes cached modules from older disabled installations that caused
missing `palette_settings` / `edit_enabled` errors in the live editor. Existing
scenes keep their selected Minecraft version. Choose the version matching your
destination world and regenerate after changing it.

After upgrading to 0.5.0, click **Reload Block Preset** in each workflow to load
the expanded palette, version-specific face colors and orientations, then regenerate. Include/Exclude
rules are preserved. **Allow glass / biome colors** enables optional materials;
leave it unchecked for the default solid palette. Biome colors use a Plains
reference; transparent colors depend on the background in Minecraft.

New scenes enable **Match visible block faces**. Existing scenes keep their old
average-matching setting until you enable it. See [the 0.5.0 guide](docs/FEATURES_050.md)
for texture import, box selection, radius brushes and protection rechecking.

Tested with Blender **5.2.2 LTS**. The package targets Blender 4.2 and newer;
4.2 has not been separately runtime-tested.

## Convert a model

1. Import your model normally, for example **File → Import → Wavefront (.obj)**.
   Include its `.mtl` and texture images in the same source folder.
2. Select all the model's mesh parts, or select their parent.
3. In the Minecraft sidebar, click **Use Selected Model**.
   **Model up direction** defaults to Blender **+Z**. For an upside-down source,
   choose **−Z (flip upside down)**, or rotate the source model before generating.
   The generated preview stands upright along Blender Z; Minecraft uses Y up.
4. Choose a **Minecraft Java version** matching the destination world.
5. Enter maximum **Width (X), Height (Y), Depth (Z)** in Minecraft blocks.
   Start around 48–64 blocks. **Keep proportions** preserves the model's shape,
   so one or two actual dimensions may be smaller than the limits.
6. Leave **Hollow build** enabled for a shell, or disable it for a solid build.
   Slabs and stairs are enabled by default.
7. Search the block list and change the rule directly on each row:
   - **Auto**: eligible normally.
   - **Include**: included when whitelist mode is enabled.
   - **Exclude**: never used.
   Enable **Only use explicitly allowed blocks** for a restricted palette.
   Tick several row checkboxes, set **Apply rules to → Checked blocks**, then
   click **Include**, **Exclude**, or **Reset**. **Select all results** checks
   everything matching the current search/category; **Clear** clears all checks.
   Choose **Filtered results** to apply rules directly to the search results,
   or **Entire palette** to apply a rule to every block.
   Enable **Regex** for patterns such as `wool|concrete` or
   `minecraft:(red|blue)_wool$`. Invalid expressions show an error without
   changing rules. Search and checkboxes alone do not restrict the build.
   **Survival obtainable** applies a whitelist excluding unavailable materials.
   It includes rare materials and ones requiring Silk Touch; it is not a cheap
   materials preset. Custom mod blocks need manual inclusion. **All materials**
   resets the rules and disables whitelist mode.
8. Click **Generate Block Preview**. A Minecraft mesh appears beside the source.
   **Esc** cancels generation. The original mesh remains available.
   Enable **Preview: 1 meter per block** in Size and structure for physical scale.
   It changes only the displayed scale and honors Blender scene units.
9. Inspect the preview. Change size, palette or the **Prefer shape** slider and
   regenerate as needed. For optional textures, use **Import Preview Textures**,
   select a complete resource ZIP/JAR, enable **Use Minecraft textures** and
   **Apply Preview Display**. Press **Z → Material Preview** to see them.
10. Under **Export preview**, choose **WorldEdit**, **Litematica**, or **Axiom**.
    The target version is shown beside export, and the suggested filename
    includes `-mc26.1.2`. You can also export a material-count CSV.

Always regenerate after editing the source geometry or material. Export writes
the saved preview, ensuring the three formats describe the same build.
Rotate the **source** or change **Model up direction**, then regenerate. Rotating
only the block preview does not update its saved Minecraft data; export now
catches that situation. Moving a preview beside its source is fine.

To allow only a few materials, check their rows and click **Use only checked**.
Or enter a search/regex and click **Use only search results**. These buttons both
replace the allow-list and enable whitelist mode in one action.

## Design a perimeter

Use the separate **N sidebar → Perimeter** tab. Follow **Size → Images and
materials → 3D decorations → Cover and lighting → Preview → Export**.
See [the full perimeter guide](docs/PERIMETER.md). Its one-meter preview checkbox
is enabled by default.

## Edit individual preview blocks

After generating, open **Live block editing** in the Minecraft tab, or Perimeter
**Step 5**. Enable block editing, then click **Pick Block** and click the block.
For multiple blocks, click **Select Area (2 Clicks)** and click two opposite
corners. Choose a brush and **Repaint blocks**, **Fill box**, or **Delete blocks**.
The panel shows active/stopped state. In the active viewport tool, optional keys
V pick, A add, R repaint, D delete, and G drag/move. Scroll while dragging changes height.
Ctrl+Z / Ctrl+Shift+Z undo/redo block edits; Esc finishes the tool.
The panel also offers exact coordinates and a cursor you can move with Blender G.
**Keep edits on regenerate** controls whether changes survive regeneration.
All three exports include the edits. See [the editor guide](docs/LIVE_EDITING.md).

## Open an export in Minecraft

Use a Minecraft instance with the matching version and the relevant mod. Copy
exports to that instance's format folder:

- Litematica: `schematics/`.
- WorldEdit: `config/worldedit/schematics/`.
- Axiom: `config/axiom/blueprints/`.

Choose the destination Minecraft version before generating. If the game version
changes, regenerate the build; renaming the export or changing its data-version
number cannot replace unavailable blocks.

In Litematica, open its **M** menu → **Load Schematics**, select the file, then
create a placement. In WorldEdit, use `//schem load` and `//paste` in a Creative
world with commands enabled.

In Axiom, press **Right Shift**, then **Windows → Blueprint Browser**. Open
the folder where you copied the blueprint, or enable **Search inside Folders**.
Clear search/tag filters and click Refresh after exporting a new file. Axiom
uses the exported **Build name** for its display/search (the default is
“Minecraft build”); renaming the `.bp` file does not change that name. Click the
blueprint to load the clipboard, then **Ctrl+V** to position it and **Enter** to
confirm. See the [official browser guide](https://axiomdocs.moulberry.com/editor/windows/blueprints.html).

A few kilobytes can be normal for a compressed small build. Each Minecraft
instance has its own export folders.

## Palette updates and limits

Bundled presets cover **51 Java releases, 1.13 through 26.3**. Pre-1.13 numeric
schematics and Bedrock are not supported in this release. Future/new block sets
can be added through an add-on update or **Import palette** JSON. A sample JSON
and schema guide are in `docs/PALETTES.md`.

The add-on never scans or changes your Minecraft installation. UV image textures,
flat Principled colors and color attributes are supported. UV textures can pass
through reroutes, Point Mapping nodes, and Hue/Saturation/Value adjustments;
mapping and adjustment controls must have constant, unlinked values. Bake complex
procedural materials to a base-color image first. Open or very thin meshes can
need inspection or repair. Current limits: 512 blocks per axis, two million
bounding cells, eight million evaluated source triangles, 1.2 million preview
faces. Use a Decimate modifier on oversized source meshes.
