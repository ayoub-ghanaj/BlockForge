"""Small, version-exact developer inputs; never shipped or used by the add-on.

Fetch block assets only, keeping filtered compressed caches instead of game
installations. Modern data comes from tagged mcmeta data-generator exports;
1.13 assets come from SHA1-verified Mojang client archives.
"""

import argparse
import base64
import gzip
import hashlib
import io
import json
import sys
import tarfile
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from minecraft_builder.catalog import bundled

CACHE = ROOT / ".cache/palette-audit"
PREFIXES = (
    "assets/minecraft/blockstates/",
    "assets/minecraft/models/block/",
    "assets/minecraft/textures/block/",
    "assets/minecraft/textures/colormap/",
)


def download(url):
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "MinecraftBuilder-palette-audit/0.4"}
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def encoded(data):
    return base64.b64encode(data).decode("ascii")


def decode(data):
    return base64.b64decode(data)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(version):
    with gzip.open(CACHE / (version + ".json.gz"), "rt") as stream:
        return json.load(stream)


def fetch(version, official, refresh=False):
    target = CACHE / (version + ".json.gz")
    if target.exists() and not refresh:
        return version, "cached", target.stat().st_size
    files = {}
    sources = []

    def get(url):
        data = download(url)
        sources.append({"url": url, "sha256": sha(data), "bytes": len(data)})
        return data

    if version.startswith("1.13"):
        meta = json.loads(get(official[version]["url"]))
        client = meta["downloads"]["client"]
        data = get(client["url"])
        assert hashlib.sha1(data).hexdigest() == client["sha1"]
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                if name.startswith(PREFIXES):
                    files[name] = encoded(z.read(name))
        legacy = "1.13.2" if version == "1.13.2" else "1.13"
        rows = json.loads(
            get(
                f"https://raw.githubusercontent.com/PrismarineJS/minecraft-data/master/data/pc/{legacy}/blocks.json"
            )
        )
        report = {}
        for row in rows:
            defaults = {}
            props = {}
            offset = row["defaultState"] - row["minStateId"]
            for prop in reversed(row["states"]):
                values = prop.get(
                    "values",
                    ["true", "false"]
                    if prop["type"] == "bool"
                    else [str(i) for i in range(prop["num_values"])],
                )
                props[prop["name"]] = values
                defaults[prop["name"]] = values[offset % len(values)]
                offset //= len(values)
            report[row["name"]] = [props, defaults]
        registry = sorted(report)
        data_version = {"1.13": 1519, "1.13.1": 1628, "1.13.2": 1631}[version]
    else:
        url = f"https://codeload.github.com/misode/mcmeta/tar.gz/refs/tags/{version}-assets-tiny"
        data = get(url)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for entry in tar:
                if not entry.isfile():
                    continue
                name = entry.name.split("/", 1)[-1]
                if name.startswith(PREFIXES) or name == "version.json":
                    files[name] = encoded(tar.extractfile(entry).read())
        meta = json.loads(decode(files["version.json"]))
        assert meta["id"] == version and meta["type"] == "release"
        data_version = meta["data_version"]
        report = json.loads(
            get(
                f"https://raw.githubusercontent.com/misode/mcmeta/{version}-summary/blocks/data.json"
            )
        )
        registry = json.loads(
            get(
                f"https://raw.githubusercontent.com/misode/mcmeta/{version}-registries/block/data.json"
            )
        )
        report = {name: report.get(name, [{}, {}]) for name in registry}
    doc = {
        "version": version,
        "data_version": data_version,
        "sources": sources,
        "files": files,
        "blocks": report,
        "registry": registry,
    }
    payload = gzip.compress(
        json.dumps(doc, sort_keys=True, separators=(",", ":")).encode(), mtime=0
    )
    target.write_bytes(payload)
    return version, "downloaded", len(payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", nargs="*")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    manifest = download("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
    (CACHE / "official-manifest.json").write_bytes(manifest)
    official = {v["id"]: v for v in json.loads(manifest)["versions"] if v["type"] == "release"}
    versions = args.versions or list(bundled())
    assert set(versions) <= official.keys(), "Preset is not an official release"
    expected = {v for v in official if tuple(map(int, v.split("."))) >= (1, 13)}
    print(
        "Official stable releases >=1.13:",
        len(expected),
        "missing presets:",
        sorted(expected - set(bundled())),
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        for version, status, size in pool.map(lambda v: fetch(v, official, args.refresh), versions):
            print(version, status, size, flush=True)


if __name__ == "__main__":
    main()
