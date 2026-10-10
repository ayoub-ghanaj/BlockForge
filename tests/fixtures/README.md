# Test fixtures

`minecraft-reports.json.gz` contains independent block registry/property reports
for all 51 bundled versions. It is generated from the downloaded upstream reports,
not from the add-on palette. The input paths, upstream projects and SHA256 hashes
are recorded in `minecraft-reports-sources.json`.

Regenerate with `python tools/build_test_references.py` after fetching matching
reference data into `.cache/`. Normal tests and CI use this committed snapshot
offline and do not need a Minecraft installation or current upstream downloads.

`palette-coverage.json.gz` records an outcome for every block registry ID in every
version. `palette-asset-sources.json.gz` records source URLs, download hashes,
filtered input hashes and hashes of model/texture files used by the 0.4.0 audit.
It contains hashes, not Minecraft assets. Run `tools/palette_sources.py`,
`tools/build_palettes.py`, `tools/build_cover_presets.py`, and
`tools/report_palette_audit.py` to refresh the audited numeric palettes and lists.

`releases/` contains this project's original 0.1.2 and 0.3.0 add-on ZIPs for real
Blender upgrade regressions. The latter reproduces the stale-module problem fixed
in 0.3.1. They contain our GPL add-on, not Minecraft/mod binaries.
