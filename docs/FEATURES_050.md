# Appearance and editing in 0.5.1

These features work on arbitrary models and perimeter designs. The example box,
tapered mesh, cat and skull are test fixtures; no conversion rule uses their names.

## Match visible faces

Enable **Match visible block faces** in either workflow, then regenerate.
The model converter samples the exposed sides of each fitted block. It compares
their colors with the chosen Minecraft version's per-face colors and can rotate
directional blocks, such as logs, into a legal state. Hidden shared faces do not
influence the match. Floors use the top face; image walls use the inward face.

New scenes enable this option. Existing saved scenes keep average-color matching
until you enable it. After upgrading, use **Reload Block Preset** to load the new
orientation metadata; palette rules are retained. Editing a block's color swatch
overrides all its face colors. Shape and color are still a compromise at block
resolution; this does not bake arbitrary procedural Blender materials.

## Optional texture display

1. Generate a Model or Perimeter preview.
2. Open its preview texture controls and click **Import Preview Textures**.
3. Explicitly select a ZIP containing `assets/minecraft/textures/…` PNG files,
   such as a complete resource pack. A manually selected vanilla client JAR also
   works. The add-on never searches your game directories.
4. Enable **Use Minecraft textures**, then **Apply Preview Display**.
5. In the viewport, press **Z → Material Preview** to see the textures.
   Uncheck the option and apply again for the fast numeric-color view.

Each workflow has its own display settings. Texture changes do not change the
saved blocks or exports. Matching still uses the selected numeric palette; import
a custom palette JSON if you want matching colors for a different resource pack.

The preview atlas is packed when saving the `.blend`. Existing tiles work when
the original ZIP is unavailable. Adding a previously unused block may require
that ZIP again. Missing textures use the block's numeric color and are reported;
a partial resource pack is not automatically combined with your game assets.

Preview limits: 16-pixel tiles, first animation frame, a deterministic variant,
Plains reference biome tint, and the bundled cube/slab/stair/cover geometry.
Custom resource-pack model geometry, connected textures, shaders and live biome
simulation are not reproduced. Archives are limited to 512 MiB on disk and
256 MiB of relevant texture entries, with at most 2,048 used states per atlas.
The extension ZIP contains numeric recipes and colors, without Minecraft images.

## Edit whole areas

In the Minecraft tab or Perimeter Step 5, enable block editing, then click
**Select Area (2 Clicks)**. Click the first corner block in the viewport, then
the opposite corner block. The box is selected; both corner cells are included.
Choose **Brush block**, then **Repaint blocks** to recolor existing blocks, or
**Fill box** to fill everything including air. **Undo edit** reverses the action.

**Pick Block** starts picking without a shortcut. The panel shows whether the
viewport tool is active or stopped. **Esc** finishes it; either button starts it
again. Use Blender **Object Mode**. Move the pointer into the 3D view to click.
The Tool menu and **Start / Resume Current Tool** activate add/delete/drag modes.
V/B/C remain optional shortcuts while the viewport tool is active: V switches to
Pick, and B/C mark the current cursor as corners. They are not global shortcuts.
Exact coordinates and **Use cursor as corner** buttons are also available.

- **Fill** fills the box, including air, with the brush block.
- **Repaint** changes only occupied cells; **Delete** clears the box.
- **Replace matching blocks in box** changes only the selected source material.
- **Copy** saves the box contents. Move the cursor, then **Paste**: the cursor is
  the minimum X/Y/Z corner of the pasted box.
- **Mirror** reflects the selected box in place. The mirror-axis option also
  applies to Paste. Stairs/slabs and directional states are reflected too.
- Paste rejects overlapping occupied destinations unless **Overwrite on paste** is checked.
  **Paste empty cells** also clears destination cells corresponding to empty source cells.
- Set **Brush radius** above zero for a spherical Add/Repaint/Delete brush.
  Add fills empty cells; Repaint changes occupied cells.

One action is one **Undo edit**, including a bulk change. Limits are 262,144 cells
per action, radius 16, and a history of at most 100 actions / 500,000 change entries.
The last large action remains undoable. Invalid sizes/materials reject the entire
operation. Existing build and preview limits still apply. All exports include edits.
See [live editing](LIVE_EDITING.md) for dragging and saved-edit behavior.

## Recheck edited protection

In Perimeter Step 5, click **Check Current Protection** after edits. Leave
**Require dry ground protection** checked when checking ground protection independent of
lighting; disable it for a lighting-only check. The report counts uncovered
surfaces, unproven light and unsupported covers. Orange outlines identify issues
(first 10,000 highlighted; totals include all issues). This action changes no blocks.

Removing a light or cover can invalidate the original design. An edit or
regeneration clears the previous check; changed settings require regeneration.
Fix the highlighted cells, then check again. The current check is saved in the
Blender scene and included in the internal export evidence.

Light checks use conservative clear paths and known emitters: at least 1 for
Java 1.18+, 8 for older presets. They can report light as unproven where the actual
world has a more complex light path. Buttons/rails/plates/levers require a sturdy
top; honey and leaves do not provide one, while carpet has looser support rules.
The generator rejects unsupported cover choices and suggests alternatives.

This checks the edited block grid, not the world biome, slime-chunk location,
spawners, raids or every mob mechanic. Light alone is not slime-chunk protection.
Actual game checks used Java 26.1.2, zombie/slime ground placement plus collision,
and block-light samples; other versions have offline data validation.

## Try the examples

Run `tests/blender_v050.py` as described in [DEVELOPMENT.md](DEVELOPMENT.md).
It creates a directional model, an edited floor, procedural test textures,
and matching exports under `build/v050/`. Open `generic-feature-examples.blend`
with the add-on enabled and use the Minecraft and Perimeter tabs independently.
The textures are generated by the test; no Minecraft texture archive is required.
