"""Build and audit every bundled palette from its own version's assets.

First run tools/palette_sources.py. No game installation is read or modified.
The add-on receives numeric data only; source assets remain in ignored .cache.
"""

import argparse
import gc
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from minecraft_builder.core.palette import parse_document
from minecraft_builder.core.shapes import with_properties
from tools.palette_assets import Assets, Unsupported
from tools.palette_sources import CACHE, load, sha

TECHNICAL = {
    "bedrock",
    "barrier",
    "jigsaw",
    "structure_block",
    "structure_void",
    "light",
    "reinforced_deepslate",
    "test_block",
    "test_instance_block",
    "command_block",
    "chain_command_block",
    "repeating_command_block",
}


def category(name):
    for key, label in (
        ("glass", "Glass"),
        ("leaves", "Leaves"),
        ("concrete", "Concrete"),
        ("wool", "Wool"),
        ("terracotta", "Terracotta"),
        ("copper", "Copper"),
        ("wood", "Wood"),
        ("planks", "Wood"),
        ("log", "Wood"),
        ("bamboo", "Wood"),
        ("quartz", "Quartz"),
        ("sandstone", "Stone"),
        ("brick", "Stone"),
        ("stone", "Stone"),
        ("deepslate", "Stone"),
        ("tuff", "Stone"),
        ("sulfur", "Stone"),
        ("cinnabar", "Stone"),
    ):
        if key in name:
            return label
    return "Other"


def release_enabled(name, version):
    """Registry presence alone does not enable an experimental feature.

    Sources: Mojang release notes for 1.19.3, 1.20.3 and 1.21.2.
    Availability here also applies to perimeter cover presets.
    """
    number = tuple(map(int, version.split(".")))
    if number < (1, 20) and (
        (
            name.startswith(
                ("bamboo_", "cherry_", "stripped_bamboo_", "stripped_cherry_", "suspicious_")
            )
            and name != "bamboo_sapling"
        )
        or name in ("chiseled_bookshelf", "decorated_pot", "piglin_head", "piglin_wall_head")
        or "hanging_sign" in name
    ):
        return False
    if number < (1, 21) and (
        name in ("crafter", "trial_spawner", "vault", "heavy_core")
        or any(
            part in name
            for part in (
                "copper_bulb",
                "chiseled_copper",
                "copper_grate",
                "copper_door",
                "copper_trapdoor",
            )
        )
        or ("tuff" in name and name != "tuff")
    ):
        return False
    if number < (1, 21, 4) and (
        "pale_oak" in name
        or name in ("pale_moss_block", "pale_moss_carpet", "pale_hanging_moss", "creaking_heart")
    ):
        return False
    return True


def build_entry(assets, name, report, version):
    if not release_enabled(name, version):
        raise Unsupported("experimental")
    if name in ("air", "cave_air", "void_air"):
        raise Unsupported("empty_space")
    if name in ("water", "lava", "bubble_column"):
        raise Unsupported("fluid")
    if name in TECHNICAL:
        raise Unsupported("technical")
    if name.endswith(("_skull", "_head")):
        raise Unsupported("entity_renderer")
    if name == "powder_snow":
        raise Unsupported("non_solid_surface")
    # Its visual planes span the cell but Minecraft's selection shape is inset
    # by 1/16 on X/Z; verified by the exact game-shape regression.
    if name == "cactus":
        raise Unsupported("unsupported_shape")
    if name in ("spawner", "trial_spawner", "vault"):
        raise Unsupported("configured_block_entity")
    props, default = report[name]
    default = dict(default)
    if name.endswith("_leaves") and "persistent" in default:
        default["persistent"] = "true"
    state = with_properties("minecraft:" + name, **default) if default else "minecraft:" + name
    kind = "stairs" if name.endswith("_stairs") else "slab" if name.endswith("_slab") else "cube"
    color, faces, appearance = assets.measure(name, default, kind, state)
    result = {
        "state": state,
        "rgb": color,
        "faces": faces,
        "shape": kind,
        "category": category(name),
    }
    if appearance:
        result["appearance"] = appearance
    if name in (
        "sand",
        "red_sand",
        "gravel",
        "suspicious_sand",
        "suspicious_gravel",
    ) or name.endswith("_concrete_powder"):
        result["gravity"] = True
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", nargs="*")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument(
        "--baseline", type=Path, default=ROOT / "minecraft_builder/data/bundled.json.gz"
    )
    args = parser.parse_args()
    baseline = json.loads(gzip.decompress(args.baseline.read_bytes()))
    old = {p["id"]: p for p in baseline["profiles"]}
    versions = args.versions or list(old)
    profiles = []
    audits = {}
    sources = {}
    failures = []
    references = {}
    for version in versions:
        source = load(version)
        assert source["data_version"] == old[version]["data_version"]
        assets = Assets(source)
        entries = []
        decisions = {}
        errors = {}
        for name in sorted(source["registry"]):
            try:
                entry = build_entry(assets, name, source["blocks"], version)
                entries.append(entry)
                decisions[name] = "optional" if entry.get("appearance") else "included"
            except Unsupported as e:
                decisions[name] = str(e)
            except Exception as e:
                decisions[name] = "ERROR"
                errors[name] = type(e).__name__ + ": " + str(e)
                failures.append((version, name, errors[name]))
        before = {b["state"].split("[")[0].split(":")[1]: b for b in old[version]["blocks"]}
        after = {b["state"].split("[")[0].split(":")[1]: b for b in entries}
        audits[version] = {
            "data_version": source["data_version"],
            "registry_blocks": len(decisions),
            "previous_palette": len(before),
            "palette_blocks": len(entries),
            "counts": dict(Counter(decisions.values())),
            "added": sorted(after.keys() - before.keys()),
            "removed": sorted(before.keys() - after.keys()),
            "changed_colors": sum(
                before[n]["rgb"] != after[n]["rgb"] for n in before.keys() & after.keys()
            ),
            "decisions": decisions,
            "errors": errors,
        }
        references[version] = {n: source["blocks"][n][0] for n in source["registry"]}
        sources[version] = {
            "data_version": source["data_version"],
            "sources": source["sources"],
            "cache_sha256": sha((CACHE / (version + ".json.gz")).read_bytes()),
            "asset_hashes": {
                p: sha(assets.read(p)) for p in sorted(assets.used) if p in assets.files
            },
        }
        profiles.append({"id": version, "data_version": source["data_version"], "blocks": entries})
        print(
            version,
            "palette",
            len(entries),
            "added",
            len(audits[version]["added"]),
            "removed",
            audits[version]["removed"],
            "optional",
            audits[version]["counts"].get("optional", 0),
            "errors",
            len(errors),
            flush=True,
        )
        del assets, source
        gc.collect()
    out = ROOT / "build/palette-audit"
    out.mkdir(parents=True, exist_ok=True)
    (out / "coverage.json").write_text(json.dumps(audits, indent=2) + "\n")
    (out / "sources.json.gz").write_bytes(
        gzip.compress(json.dumps(sources, sort_keys=True, separators=(",", ":")).encode(), mtime=0)
    )
    if failures:
        print("UNRESOLVED ASSET ERRORS", json.dumps(failures, indent=2))
        raise RuntimeError("Audit has unresolved errors; bundle was not changed")
    document = {
        "schema_version": 1,
        "name": "Version-exact vanilla building palettes",
        "color_source": "Per-version vanilla assets; six projected faces, UVs, animation timing and alpha; Plains reference for biome tints",
        "sources": [
            "https://github.com/misode/mcmeta",
            "https://github.com/PrismarineJS/minecraft-data",
            "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",
        ],
        "profiles": profiles,
    }
    parse_document(document)
    (out / "bundled.json.gz").write_bytes(
        gzip.compress(json.dumps(document, separators=(",", ":")).encode(), mtime=0)
    )
    if not args.audit_only:
        if args.versions:
            raise ValueError("Partial audits cannot overwrite the full bundle; use --audit-only")
        (ROOT / "minecraft_builder/data/bundled.json.gz").write_bytes(
            (out / "bundled.json.gz").read_bytes()
        )
        fixtures = ROOT / "tests/fixtures"
        (fixtures / "minecraft-reports.json.gz").write_bytes(
            gzip.compress(
                json.dumps(references, sort_keys=True, separators=(",", ":")).encode(), mtime=0
            )
        )
        (fixtures / "palette-coverage.json.gz").write_bytes(
            gzip.compress(
                json.dumps(audits, sort_keys=True, separators=(",", ":")).encode(), mtime=0
            )
        )
        (fixtures / "palette-asset-sources.json.gz").write_bytes(
            (out / "sources.json.gz").read_bytes()
        )
    print("Audited", len(versions), "versions; unresolved errors:", len(failures))


if __name__ == "__main__":
    main()
