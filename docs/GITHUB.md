# Builds and releases

The [Build and test workflow](../.github/workflows/build.yml) runs on main-branch
pushes, pull requests, version tags, and manual dispatches. It works with public
and private repositories.

## Checks

1. Ruff formatting and lint checks.
2. Offline Python tests with independent readers for all three export formats.
3. Extension ZIP build with its GPL license and third-party notices.
4. Blender 5.2.2 integration: generation, controls, palettes, saved editing,
   ZIP installation, and upgrades from earlier versions.

Builds use read-only repository permissions. Pull requests run without release
credentials. Actions are pinned to commit SHAs. Only the tag release job can
write repository contents, and it runs after both test jobs pass.

CI produces the extension ZIP, its checksum, and test reports. Generated game
worlds, imported models, texture archives, and local example reports are excluded
from published release assets. CI does not launch Minecraft or simulate desktop
mouse input; see [development and testing](DEVELOPMENT.md) for those checks.

## Publish a version

1. Update both `minecraft_builder/blender_manifest.toml` and `bl_info` in
   `minecraft_builder/__init__.py` to the same version.
2. Add `docs/releases/<version>.md` and update the installation guide.
3. Run the checks in [DEVELOPMENT.md](DEVELOPMENT.md), push to `main`, and inspect
   the Actions results.
4. Tag that commit, for example `git tag -a v0.5.2 -m "Release 0.5.2"`, and push
   the tag with `git push origin v0.5.2`.

The tag must match the manifest exactly. After verification, the workflow creates
a release with `minecraft_builder-<version>.zip` and `addon-checksum.json`.
Main-branch pushes and pull requests build artifacts without publishing releases.
