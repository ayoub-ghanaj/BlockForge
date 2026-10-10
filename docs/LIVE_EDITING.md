# Edit blocks in the preview

Install 0.5.1 and generate a Model or Perimeter preview first. The **Minecraft**
tab has a **Live block editing** panel. The separate **Perimeter** tab shows the
same controls in **Step 5 / Preview**. Each workflow keeps its own edits.

## Mouse tools

Use Blender **Object Mode**, enable block editing, then click **Pick Block**.
Move the pointer into the 3D view and click a block.

For a first edit: click **Pick Block**, click the block, then move to the sidebar. The
picked coordinates stay selected. Choose a **Brush block**, then click **Repaint**,
or click **Delete**. You can use the panel while the viewport tool stays active.
Move back into the viewport and press **Esc** to finish the tool. The panel shows
whether the tool is active or stopped. **Pick Block**, **Select Area (2 Clicks)**
or **Start / Resume Current Tool** starts it again. Keyboard shortcuts below work
only while this tool is active and the pointer is over the 3D view.

For several blocks: click **Select Area (2 Clicks)**, click two opposite corner
blocks, choose **Brush block**, then **Repaint blocks**. **Fill box** also fills air;
**Delete blocks** clears the selection. No V/B/C keys are needed for this flow.

| Key | Left mouse action |
|---|---|
| V | Pick a block and its material. |
| A | Add the brush block against the clicked face, or at the cursor's height. |
| R | Repaint the clicked block with the brush material. |
| D | Delete the clicked block. |
| G | Drag a picked block across the grid; release to place. Scroll changes height. |
| B / C | Mark selection corner A / B at the picked cursor position. |
| Ctrl+Z / Ctrl+Shift+Z | Undo / redo a block edit. |
| Esc / right mouse | Finish the viewport tool. |

Middle mouse remains available for orbiting. Enable **Pick through glass** to edit
artwork beneath the cover; turn it off to pick the glass itself. Slabs and stairs
are picked by their shape. Add and Move reject occupied destinations; use Repaint
to replace a block. Pick a different source if the drag destination is occupied.

## Brush and exact placement

Use the searchable **Brush block** field. The brush respects the selected artwork
palette; picked perimeter treatment materials can also be reused. Choose a slab
half or stair half/facing when needed. Stair corners update with their neighbors.

The three **Block coordinates** are Minecraft **X, Y up, Z**:

- Model coordinates begin at 0 inside the selected width/height/depth bounds.
- Perimeter interior is X=1…width, Z=1…length, floor Y=0. Decorations start above
  it at Y=1. Outer walls occupy X=0/width+1 or Z=0/length+1. These coordinates
  remain stable even when the export is trimmed to a floor or single wall.

Enter coordinates, then use **Pick at cursor**, **Add here**, **Repaint**,
**Delete**, or **Move picked block here**. Alternatively, click **Select cursor
(G to drag)**, use Blender's normal G movement, then click a placement action.
The cursor snaps to the containing block cell. The source meshes are unchanged.

## Save, regenerate and export

**Keep edits on regenerate** is checked by default. Regeneration reapplies your
saved edits at their grid coordinates. Unavailable materials or positions outside
new dimensions are skipped and reported, but retained so you can restore them by
returning to the old settings. Uncheck it to discard edits on the next generation.

**Clear edits** returns to generated blocks and is undoable. **Undo edit / Redo
edit** retain up to 100 actions / 500,000 change entries and survive saving/reopening
the `.blend`. A bulk operation is one action; the last large action remains undoable.
Regeneration starts a fresh edit history. The saved base and edits are combined
for WorldEdit, Litematica, Axiom and material counts.

Use these tools for block changes; moving or deleting preview section objects in
ordinary Blender Edit/Object Mode does not change the saved Minecraft build.
Change model orientation on the source or with Model up direction, then regenerate.

Enabling editing first prepares sections of the preview. Subsequent edits rebuild
only nearby sections. The **1 meter per block** checkbox and scene units also
apply to the cursor and edited geometry.

Use **Box selection and bulk edits** for fill/repaint/delete/replace, copying,
pasting and mirroring. Use **Brush radius** for spherical add/repaint/delete.
The [0.5.0 guide](FEATURES_050.md) explains selection coordinates, overlap rules
and limits. Manual changes also update an imported textured preview.

After manual perimeter changes, run **Check Current Protection** in Step 5.
It checks the edited grid and highlights unproven light, uncovered surfaces and
unsupported covers. The check is conservative and does not simulate world-specific
or special mob mechanics.

## Reproduce an editing example

Run `tests/blender_editing.py` in a fresh Blender process as described in
[DEVELOPMENT.md](DEVELOPMENT.md). It generates editable fixtures and all three
export formats under `build/live-edit/`. The test uses generated geometry and
does not need an imported model.
