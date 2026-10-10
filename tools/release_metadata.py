"""Validate release versions without importing Blender or executing tag text."""

import ast
import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def release_version(root: Path = ROOT, tag: str = "") -> str:
    """Require the manifest, legacy Blender metadata, and release notes to agree."""
    source = root / "minecraft_builder"
    version = tomllib.loads((source / "blender_manifest.toml").read_text())["version"]
    tree = ast.parse((source / "__init__.py").read_text())
    metadata = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "bl_info" for target in node.targets)
    )
    legacy_version = ".".join(map(str, ast.literal_eval(metadata)["version"]))
    if version != legacy_version:
        raise ValueError(f"Manifest version {version} differs from bl_info {legacy_version}")
    if tag and tag != "v" + version:
        raise ValueError(f"Tag must be v{version}; got {tag!r}")
    if not (root / "docs/releases" / f"{version}.md").is_file():
        raise ValueError(f"Missing release notes for {version}")
    return version


def main() -> None:
    try:
        version = release_version(tag=os.environ.get("RELEASE_TAG", ""))
    except ValueError as error:
        raise SystemExit(str(error)) from error
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write("version=" + version + "\n")
    print(version)


if __name__ == "__main__":
    main()
