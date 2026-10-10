"""Compile the isolated Fabric verification mod with an explicit JDK 25."""

import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from test_core import fixture

from minecraft_builder import catalog
from minecraft_builder.core import exporters
from minecraft_builder.core.shapes import orientations, state_mask, with_properties
from tools.setup_minecraft_test import win


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-dir", type=Path, default=ROOT / ".testing/minecraft")
    parser.add_argument(
        "--javac", type=Path, required=True, help="Windows JDK 25 javac.exe executable"
    )
    args = parser.parse_args()
    javac = args.javac.resolve()
    if not javac.is_file():
        parser.error("--javac must name an existing executable")
    game_dir = args.game_dir
    out = ROOT / "build/verification"
    out.mkdir(parents=True, exist_ok=True)
    cases = ["cube_hollow"]
    for count in (17, 260):
        build = fixture(count)
        name = f"packing_{count}"
        cases.append(name)
        (out / (name + ".json")).write_text(json.dumps(build))
        for kind in ("schem", "litematic", "bp"):
            exporters.write(out / (name + "." + kind), build, kind, "Unicode cat 🐈", "Blender")
    if (out / "cat.json").exists():
        cases.append("cat")
    import shutil

    for name in ("cat", "skull"):
        source = ROOT / "build/user-models"
        if (source / (name + ".json")).exists():
            target = "user_" + name
            for ext in ("json", "schem", "litematic", "bp"):
                shutil.copy2(source / (name + "." + ext), out / (target + "." + ext))
            cases.append(target)
    (out / "cases.json").write_text(json.dumps(cases))
    shapes = {}
    for block in catalog.bundled()["26.1.2"].blocks:
        for state, mask in orientations(block):
            if block.shape == "stairs":
                for corner in (
                    "straight",
                    "inner_left",
                    "inner_right",
                    "outer_left",
                    "outer_right",
                ):
                    changed = with_properties(state, shape=corner)
                    shapes[changed] = state_mask(changed, "stairs")
            else:
                shapes[state] = mask
    (out / "shape-cases.json").write_text(
        json.dumps([{"state": s, "mask": m} for s, m in shapes.items()])
    )
    target = ROOT / ".testing/verify-classes"
    target.mkdir(exist_ok=True)
    cp = json.loads((ROOT / ".testing/compile-classpath.json").read_text())
    args = [
        "-encoding",
        "UTF-8",
        "-cp",
        ";".join(cp),
        "-d",
        win(target),
        win(ROOT / "tests/minecraft/BuilderVerify.java"),
    ]
    argfile = ROOT / ".testing/compile.args"
    argfile.write_text("\n".join('"' + a.replace("\\", "\\\\") + '"' for a in args))
    subprocess.run([str(javac), "@" + win(argfile)], check=True)
    mod = game_dir / "mods/builder-verify.jar"
    mod.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(mod, "w", zipfile.ZIP_DEFLATED) as jar:
        jar.writestr(
            "fabric.mod.json",
            json.dumps(
                {
                    "schemaVersion": 1,
                    "id": "builder_verify",
                    "version": "0.1.0",
                    "name": "Builder import verification",
                    "environment": "client",
                    "entrypoints": {"client": ["builderverify.BuilderVerify"]},
                    "depends": {
                        "fabricloader": ">=0.19.5",
                        "minecraft": "26.1.2",
                        "java": ">=25",
                        "axiom": "*",
                        "litematica": "*",
                        "worldedit": "*",
                    },
                }
            ),
        )
        for p in target.rglob("*.class"):
            jar.write(p, str(p.relative_to(target)).replace("\\", "/"))
    print("Prepared", len(cases), "export cases and", len(shapes), "shape cases")


if __name__ == "__main__":
    main()
