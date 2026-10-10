# Development and testing

Use Python 3.11 or newer for development. Blender supplies NumPy when running the
installed add-on; the other dependencies below are for tests and palette tools.

```sh
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\Scripts\activate
python -m pip install -r requirements-dev.txt
python -m ruff format --check minecraft_builder tests tools
python -m ruff check minecraft_builder tests tools
python -m unittest discover -s tests -v
python tools/package_addon.py
```

Run `python -m ruff format minecraft_builder tests tools` before committing Python
changes. Keep behavior changes separate from formatting when possible. Preserve
Blender property names, operator IDs, saved snapshot fields, and export ordering:
existing scenes and upgrade tests depend on them.

## Code map

| Area | Responsibility |
| --- | --- |
| `core/palette.py` | Validated profiles and color matching |
| `core/geometry.py`, `core/volume.py`, `core/shapes.py` | Bounds, voxelization, and block shapes |
| `core/exporters.py`, `core/nbt.py` | File formats and atomic model exports |
| `core/editing.py`, `core/bulk.py` | Saved overrides, undo/redo, selection, and clipboard operations |
| `blender_mesh.py`, `ui.py` | Blender model sampling, preview generation, and sidebar controls |
| `live_edit.py` | Editing sessions, local mesh updates, and viewport input |
| `perimeter/` | Image surfaces, decorations, covers, lighting, and streamed exports |
| `textured_preview.py`, `core/texture_pack.py` | Explicit texture imports and packed preview atlases |

Minecraft `(x, y, z)` maps to Blender `(x, -z, y)`. Builds use nonnegative local
coordinates. Perimeters retain a separate canonical origin when trimming empty
bounds. Changing only the preview transform must not change exported block data.

## Blender checks

Run each script in a fresh process, with an installed Blender executable:

```sh
blender --background --factory-startup --disable-autoexec --python-exit-code 1 --python tests/blender_smoke.py
blender --background --factory-startup --disable-autoexec --python-exit-code 1 --python tests/blender_controls.py
blender --background --factory-startup --disable-autoexec --python-exit-code 1 --python tests/blender_v050.py
```

Other coverage includes `blender_palette.py`, `blender_editing.py`,
`blender_perimeter.py`, and `blender_versions.py`. Build the ZIP before running
`blender_install.py` or `blender_upgrade.py`. Upgrade fixtures in
`tests/fixtures/releases/` are this project's earlier GPL add-ons.

The CI runner uses the official `bpy==5.2.2` Python package through
`tools/run_blender_ci.py`. The minimum manifest version is Blender 4.2; that does
not imply every Blender version has been tested.

`tests/blender_edit_events.py` tests real mouse and keyboard events. Run it in a
separate foreground Blender process with `--factory-startup --enable-event-simulate`.
It exits its own process after saving a report. Do not run it in an active work
session. Reports and generated scenes are written under ignored `build/` and
`.testing/` directories.

## Minecraft and palette checks

Offline tests validate every bundled preset against independent registry
fixtures. The Java harness in `tests/minecraft/` additionally exercises WorldEdit,
Litematica, and Axiom readers in a dedicated local Minecraft 26.1.2 instance.
It is a separate acceptance check, not part of CI. Game setup tools require an
explicit installation path and JDK path; see their `--help` output.

The add-on never discovers or modifies a Minecraft installation. Developer tools
use explicit inputs and cache fetched palette reference data under `.cache/`.
See [PALETTE_AUDIT.md](PALETTE_AUDIT.md) for regeneration steps and
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) for data provenance.
