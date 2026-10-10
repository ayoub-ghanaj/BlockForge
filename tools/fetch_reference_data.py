"""Development only: download public reference data into .cache; never inspect Minecraft installs."""

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"


def fetch(url, dest):
    dest = CACHE / dest
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url, headers={"User-Agent": "MinecraftBuilder-palette-build/0.1"}
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read()
    dest.write_bytes(data)
    return dest


def main():
    versions = json.loads(
        fetch(
            "https://raw.githubusercontent.com/misode/mcmeta/summary/versions/data.json",
            "versions.json",
        ).read_text()
    )
    releases = [v for v in versions if v["type"] == "release" and v["data_version"] >= 1952]

    def report(v):
        name = v["id"]
        try:
            fetch(
                f"https://raw.githubusercontent.com/misode/mcmeta/{name}-summary/blocks/data.json",
                f"blocks/{name}.json",
            )
            fetch(
                f"https://raw.githubusercontent.com/misode/mcmeta/{name}-registries/block/data.json",
                f"registries/{name}.json",
            )
            return name, "OK"
        except Exception as exc:
            return name, str(exc)

    with ThreadPoolExecutor(max_workers=6) as pool:
        for version, result in pool.map(report, releases):
            print(version, result, flush=True)
    for v in ("1.13", "1.13.2", "1.12", "1.8"):
        try:
            fetch(
                f"https://raw.githubusercontent.com/PrismarineJS/minecraft-data/master/data/pc/{v}/blocks.json",
                f"legacy/{v}.json",
            )
        except Exception as exc:
            print(v, exc, flush=True)
    fetch(
        "https://raw.githubusercontent.com/sakura-ryoko/litematica/1.21.11/src/main/java/fi/dy/masa/litematica/schematic/LitematicaSchematic.java",
        "LitematicaSchematic.java",
    )
    fetch(
        "https://raw.githubusercontent.com/sakura-ryoko/litematica/1.21.11/src/main/java/fi/dy/masa/litematica/schematic/container/LitematicaBlockStateContainer.java",
        "LitematicaBlockStateContainer.java",
    )
    for name in ("BlueprintIo", "BlueprintHeader"):
        fetch(
            f"https://raw.githubusercontent.com/Moulberry/AxiomPaperPlugin/master/src/main/java/com/moulberry/axiom/blueprint/{name}.java",
            name + ".java",
        )


if __name__ == "__main__":
    main()
