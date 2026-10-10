"""Freeze independent downloaded registries for offline tests and GitHub CI."""

import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from minecraft_builder.catalog import bundled


def main():
    versions = {}
    sources = {}
    for version in bundled():
        path = ROOT / ".cache/blocks" / f"{version}.json"
        if path.exists():
            raw = json.loads(path.read_text())
            registry = ROOT / ".cache/registries" / f"{version}.json"
            versions[version] = {
                name: raw.get(name, [{}, {}])[0] for name in json.loads(registry.read_text())
            }
            files = [path, registry]
            source = "https://github.com/misode/mcmeta"
        else:
            legacy = "1.13.2" if version == "1.13.2" else "1.13"
            path = ROOT / ".cache/legacy" / f"{legacy}.json"
            raw = json.loads(path.read_text())
            versions[version] = {
                b["name"]: {
                    s["name"]: s.get(
                        "values",
                        ["true", "false"]
                        if s["type"] == "bool"
                        else [str(i) for i in range(s["num_values"])],
                    )
                    for s in b["states"]
                }
                for b in raw
            }
            files = [path]
            source = "https://github.com/PrismarineJS/minecraft-data"
        sources[version] = {
            "source": source,
            "inputs": [
                {
                    "path": str(p.relative_to(ROOT)),
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                }
                for p in files
            ],
        }
    out = ROOT / "tests/fixtures"
    out.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(versions, sort_keys=True, separators=(",", ":")).encode()
    (out / "minecraft-reports.json.gz").write_bytes(gzip.compress(payload, mtime=0))
    (out / "minecraft-reports-sources.json").write_text(json.dumps(sources, indent=2) + "\n")
    print("Saved independent registry/property reports for", len(versions), "presets")


if __name__ == "__main__":
    main()
