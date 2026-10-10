"""Build a reproducible extension ZIP containing only supported runtime files."""

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.release_metadata import release_version

PACKAGE_FILES = frozenset(
    {
        "blender_manifest.toml",
        "LICENSE.txt",
        "THIRD_PARTY_NOTICES.txt",
        "data/bundled.json.gz",
        "data/covers.json.gz",
        "data/visuals.json.gz",
    }
)


def package_files(source: Path) -> list[Path]:
    """Keep caches, credentials, imported assets, and arbitrary archives out."""
    files = []
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if not path.is_file() or path.is_symlink():
            continue
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        if relative.as_posix() in PACKAGE_FILES or path.suffix == ".py":
            files.append(path)
    return files


def build_package(root: Path = ROOT) -> dict:
    source = root / "minecraft_builder"
    version = release_version(root)
    files = package_files(source)
    names = {path.relative_to(source).as_posix() for path in files}
    missing = PACKAGE_FILES - names
    if missing:
        raise ValueError("Package files missing: " + ", ".join(sorted(missing)))
    if (root / "LICENSE").read_bytes() != (source / "LICENSE.txt").read_bytes():
        raise ValueError("Root and packaged GPL license texts differ")
    target = root / "dist"
    target.mkdir(exist_ok=True)
    output = target / f"minecraft_builder-{version}.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            # Fixed timestamps and permissions make identical source trees produce
            # identical ZIPs on different checkout dates and operating systems.
            entry = zipfile.ZipInfo(path.relative_to(source).as_posix(), (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, path.read_bytes())
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("Built ZIP failed its integrity check")
    result = {
        "file": output.name,
        "bytes": output.stat().st_size,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    (target / "addon-checksum.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    print(json.dumps(build_package()))


if __name__ == "__main__":
    main()
