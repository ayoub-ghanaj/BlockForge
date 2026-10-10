"""Bundle exact dry-cover states from cached per-version registry reports."""

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from minecraft_builder import catalog
from minecraft_builder.core.shapes import with_properties
from minecraft_builder.perimeter.materials import DYES
from tools.build_palettes import release_enabled
from tools.palette_assets import Assets
from tools.palette_sources import load


def main():
    result = {}
    for version, profile in catalog.bundled().items():
        source = load(version)
        report = source["blocks"]
        assets = Assets(source)
        rows = []
        for name, info in report.items():
            kind = (
                "BUTTON"
                if name.endswith("_button")
                else "TRAPDOOR"
                if name.endswith("_trapdoor")
                else "CARPET"
                if name.removesuffix("_carpet") in DYES and name.endswith("_carpet")
                else "LEAVES"
                if name.endswith("_leaves")
                else "RAIL"
                if name in ("rail", "powered_rail", "detector_rail", "activator_rail")
                else "PLATE"
                if name.endswith("_pressure_plate")
                else "LEVER"
                if name == "lever"
                else None
            )
            if not kind or not release_enabled(name, version):
                continue
            props = dict(info[1])
            for key, value in {
                "face": "floor",
                "facing": "north",
                "powered": "false",
                "open": "false",
                "half": "bottom",
                "persistent": "true",
                "distance": "7",
                "waterlogged": "false",
                "shape": "north_south",
            }.items():
                if key in props and value in info[0][key]:
                    props[key] = value
            state = with_properties("minecraft:" + name, **props) if props else "minecraft:" + name
            # These shapes have explicit cover adapters. Measure the actual
            # version's texture instead of using wool dye constants/gray.
            rgb, _, _ = assets.measure(name, props, "cube", state, verify_shape=False)
            rows.append({"state": state, "kind": kind, "rgb": rgb})
        for b in profile.blocks:
            if b.shape == "slab":
                rows.append(
                    {"state": with_properties(b.state, type="bottom"), "kind": "SLAB", "rgb": b.rgb}
                )
        result[version] = {
            "data_version": profile.data_version,
            "blocks": sorted(rows, key=lambda r: r["state"]),
        }
        print(version, len(rows), "covers", flush=True)
    out = ROOT / "minecraft_builder/data/covers.json.gz"
    out.write_bytes(gzip.compress(json.dumps(result, separators=(",", ":")).encode(), mtime=0))
    print(len(result), "cover presets;", out.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
