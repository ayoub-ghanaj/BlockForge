"""Development-only isolated Windows test instance; shared install is read-only.

Downloads only mod/dependency JARs absent locally. No account tokens are read.
The shipped Blender add-on never imports or runs this tool.
"""

import argparse
import hashlib
import io
import json
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]
TEST = ROOT / ".testing"
GAME = TEST / "minecraft"
VERSION = "26.1.2"
LOADER = "fabric-loader-0.19.5-26.1.2"


def win(path):
    """Convert an explicit Windows or WSL-mounted path for Windows Java."""
    path = Path(path).resolve()
    if path.drive:
        return str(path)
    parts = path.parts
    if len(parts) >= 3 and parts[1] == "mnt" and len(parts[2]) == 1:
        return str(PureWindowsPath(parts[2].upper() + ":/", *parts[3:]))
    raise ValueError("Expected a Windows path or a drive mounted under /mnt/<drive>")


def download(url, path, sha1=None, sha512=None):
    algorithm = "sha512" if sha512 else "sha1"
    expected = sha512 or sha1
    if path.exists() and (
        not expected or hashlib.new(algorithm, path.read_bytes()).hexdigest() == expected
    ):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "MinecraftBuilder-dev-tests/0.1"})
    with urllib.request.urlopen(req, timeout=90) as response:
        data = response.read()
    if expected and hashlib.new(algorithm, data).hexdigest() != expected:
        raise ValueError("Download hash mismatch: " + path.name)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.testzip():
            raise ValueError("Corrupt JAR: " + path.name)
    path.write_bytes(data)
    print("Downloaded", path.name, len(data), flush=True)
    return path


def allowed(library):
    rules = library.get("rules")
    if not rules:
        return True
    result = False
    for rule in rules:
        os = rule.get("os", {})
        if os.get("name", "windows") != "windows" or os.get("arch", "x86_64") not in (
            "x86_64",
            "amd64",
        ):
            continue
        if "features" in rule:
            continue
        result = rule["action"] == "allow"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--install",
        type=Path,
        required=True,
        help="Existing Windows Minecraft installation (read-only)",
    )
    parser.add_argument(
        "--java", type=Path, required=True, help="Windows JDK 25 java.exe executable"
    )
    args = parser.parse_args()
    install, java = args.install.resolve(), args.java.resolve()
    if not install.is_dir() or not java.is_file():
        parser.error("--install must be a directory and --java an existing executable")
    win(install)
    win(java)
    GAME.mkdir(parents=True, exist_ok=True)
    (GAME / "mods").mkdir(exist_ok=True)
    (TEST / "temp").mkdir(exist_ok=True)
    vanilla = json.loads((install / "versions" / VERSION / (VERSION + ".json")).read_text())
    fabric = json.loads((install / "versions" / LOADER / (LOADER + ".json")).read_text())
    tasks = []
    classpath = []
    for library in vanilla["libraries"] + fabric["libraries"]:
        if not allowed(library):
            continue
        artifact = library.get("downloads", {}).get("artifact")
        if artifact:
            rel = artifact["path"]
            url = artifact["url"]
            sha = artifact.get("sha1")
        else:
            group, name, version = library["name"].split(":")[:3]
            rel = f"{group.replace('.', '/')}/{name}/{version}/{name}-{version}.jar"
            url = "https://maven.fabricmc.net/" + rel
            sha = None
        path = install / "libraries" / rel
        if not path.exists():
            path = TEST / "libraries" / rel
            tasks.append((url, path, sha, None))
        classpath.append(path)
    classpath.append(install / "versions" / VERSION / (VERSION + ".jar"))
    manifest = []
    for project in ("axiom", "litematica", "worldedit", "malilib", "fabric-api"):
        versions = json.loads(
            (ROOT / ".cache/mod-metadata" / f"{project}-{VERSION}.json").read_text()
        )
        version = versions[0]
        file = next((f for f in version["files"] if f["primary"]), version["files"][0])
        path = GAME / "mods" / file["filename"]
        tasks.append((file["url"], path, None, file["hashes"]["sha512"]))
        manifest.append(
            {
                "project": project,
                "version": version["version_number"],
                "file": file["filename"],
                "sha512": file["hashes"]["sha512"],
                "url": file["url"],
                "dependencies": version["dependencies"],
            }
        )
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda a: download(*a), tasks))
    (TEST / "mods-lock.json").write_text(json.dumps(manifest, indent=2))
    args = [
        "-Xms512M",
        "-Xmx4G",
        "-Djava.io.tmpdir=" + win(TEST / "temp"),
        "-Dlog4j2.formatMsgNoLookups=true",
        "-Dminecraft.launcher.brand=MinecraftBuilderTest",
        "-Dminecraft.launcher.version=0.1",
        "-Dfabric.log.disableAnsi=true",
        "-cp",
        ";".join(win(p) for p in classpath),
        fabric["mainClass"],
        "--username",
        "BuilderTest",
        "--version",
        VERSION,
        "--gameDir",
        win(GAME),
        "--assetsDir",
        win(install / "assets"),
        "--assetIndex",
        vanilla["assetIndex"]["id"],
        "--uuid",
        "00000000000000000000000000000001",
        "--accessToken",
        "0",
        "--userType",
        "legacy",
        "--width",
        "1280",
        "--height",
        "800",
        "--versionType",
        "Minecraft Builder isolated test",
    ]
    # Java argfiles require doubled backslashes inside quotes.
    (TEST / "client.args").write_text(
        "\n".join('"' + a.replace("\\", "\\\\").replace('"', '\\"') + '"' for a in args) + "\n"
    )
    (TEST / "classpath.json").write_text(json.dumps([win(p) for p in classpath]))
    (GAME / "launch-test.cmd").write_text(
        '@echo off\r\ncd /d "%~dp0"\r\n"' + win(java) + '" "@' + win(TEST / "client.args") + '"\r\n'
    )
    # Only this newly created test instance receives these options.
    options = GAME / "options.txt"
    if not options.exists():
        options.write_text(
            "autoJump:false\nrenderDistance:5\nsimulationDistance:5\nmaxFps:60\nfullscreen:false\nsoundCategory_master:0.0\njoinedFirstServer:true\n"
        )
    print("Prepared", win(GAME), "using", len(classpath), "libraries")


if __name__ == "__main__":
    main()
