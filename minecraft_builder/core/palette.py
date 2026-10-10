"""Validated, version-specific palettes. No game-directory or network access."""

import json
import re
from dataclasses import dataclass
from functools import lru_cache

STATE = re.compile(
    r"^[a-z0-9_.-]+:[a-z0-9_./-]+(?:\[[a-z0-9_]+=[a-z0-9_.-]+(?:,[a-z0-9_]+=[a-z0-9_.-]+)*\])?$"
)
MAX_PALETTE_BYTES = 16 * 1024 * 1024
RGB = tuple[int, int, int]
FaceColors = tuple[tuple[str, RGB], ...]
StateVariant = tuple[str, FaceColors]

# Normal survival collection/crafting; excludes commands and bug exploits.
SURVIVAL_EXCLUDED = frozenset(
    (
        "bedrock",
        "barrier",
        "light",
        "budding_amethyst",
        "reinforced_deepslate",
        "petrified_oak_slab",
        "suspicious_sand",
        "suspicious_gravel",
        "spawner",
        "trial_spawner",
        "vault",
        "end_portal_frame",
        "command_block",
        "chain_command_block",
        "repeating_command_block",
        "structure_block",
        "structure_void",
        "jigsaw",
        "test_block",
        "test_instance_block",
        "frosted_ice",
    )
)


def survival_obtainable(state, version):
    namespace, name = state.split("[", 1)[0].split(":", 1)
    if namespace != "minecraft":
        return False  # Custom blocks need an explicit user choice.
    if name in SURVIVAL_EXCLUDED or name.startswith("infested_"):
        return False
    if version in ("1.13", "1.13.1", "1.13.2") and name in (
        "smooth_stone",
        "smooth_quartz",
        "smooth_sandstone",
        "smooth_red_sandstone",
    ):
        return False
    return True


def canonical_state(state: str) -> str:
    """Validate a namespaced state and sort its properties for stable comparisons."""
    if not isinstance(state, str) or len(state) > 512 or not STATE.fullmatch(state):
        raise ValueError(f"Invalid block state: {str(state)[:80]}")
    if "[" not in state:
        return state
    block, props = state[:-1].split("[", 1)
    pairs = props.split(",")
    if len({p.split("=")[0] for p in pairs}) != len(pairs):
        raise ValueError("Duplicate block-state property")
    return block + "[" + ",".join(sorted(pairs)) + "]"


def rgb_check(value: object) -> RGB:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or any(type(v) is not int or not 0 <= v <= 255 for v in value)
    ):
        raise ValueError("Colors must be three integers from 0 to 255 (sRGB)")
    return tuple(value)


@dataclass(frozen=True)
class Block:
    state: str
    rgb: RGB
    category: str = "Other"
    faces: FaceColors = ()
    gravity: bool = False
    legacy_id: int = -1
    legacy_data: int = 0
    shape: str = "cube"
    appearance: tuple[str, ...] = ()
    variants: tuple[StateVariant, ...] = ()

    @property
    def label(self):
        return self.state.split(":", 1)[-1].split("[")[0].replace("_", " ").title()


@dataclass(frozen=True)
class Profile:
    id: str
    data_version: int
    blocks: tuple[Block, ...]
    legacy: bool = False
    litematic: bool = True


def parse_document(document: object) -> dict[str, Profile]:
    """Validate imported palette data before exposing it to Blender or exporters."""
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("Expected a Minecraft Builder palette with schema_version 1")
    profiles = document.get("profiles")
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= 256:
        raise ValueError("A palette needs between 1 and 256 version profiles")
    result = {}
    total = 0
    for raw in profiles:
        if not isinstance(raw, dict):
            raise ValueError("Invalid version profile")
        ident = raw.get("id")
        data_version = raw.get("data_version")
        if not isinstance(ident, str) or not ident.strip() or len(ident) > 100:
            raise ValueError("Each profile needs a short version id")
        if ident in result:
            raise ValueError("Duplicate version profile: " + ident)
        if type(data_version) is not int or not 0 <= data_version <= 2**31 - 1:
            raise ValueError("Each profile needs an integer Minecraft data_version")
        entries = raw.get("blocks")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 10000:
            raise ValueError("Each profile needs between 1 and 10000 blocks")
        total += len(entries)
        if total > 200000:
            raise ValueError("Too many palette entries")
        blocks = []
        seen = set()
        legacy = raw.get("legacy", False)
        if type(legacy) is not bool or type(raw.get("litematic", True)) is not bool:
            raise ValueError("legacy and litematic must be booleans")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Invalid block entry")
            state = canonical_state(entry.get("state"))
            if state.split("[")[0] in ("minecraft:air", "minecraft:cave_air", "minecraft:void_air"):
                raise ValueError("Air is reserved for empty space and cannot be a color choice")
            if state in seen:
                raise ValueError("Duplicate block state: " + state)
            seen.add(state)
            shape = entry.get("shape", "cube")
            if shape not in ("cube", "slab", "stairs"):
                raise ValueError("Block shape must be cube, slab or stairs")
            if shape != "cube" and legacy:
                raise ValueError("Legacy custom profiles currently support full cubes only")
            category = entry.get("category", "Other")
            if not isinstance(category, str) or len(category) > 80:
                raise ValueError("Invalid block category")
            faces = entry.get("faces", {})
            if not isinstance(faces, dict) or any(
                k not in ("up", "down", "north", "south", "east", "west") for k in faces
            ):
                raise ValueError("Invalid face-color mapping")
            gravity = entry.get("gravity", False)
            if type(gravity) is not bool:
                raise ValueError("gravity must be a boolean")
            appearance = entry.get("appearance", [])
            if (
                not isinstance(appearance, list)
                or any(v not in ("transparent", "biome_tinted") for v in appearance)
                or len(set(appearance)) != len(appearance)
            ):
                raise ValueError("appearance must list unique transparent / biome_tinted flags")
            variants = []
            raw_variants = entry.get("variants", [])
            if not isinstance(raw_variants, list) or len(raw_variants) > 48:
                raise ValueError("Invalid orientation list")
            for variant in raw_variants:
                if not isinstance(variant, dict):
                    raise ValueError("Invalid orientation entry")
                oriented = canonical_state(variant.get("state"))
                if oriented.split("[")[0] != state.split("[")[0]:
                    raise ValueError("An orientation must keep the same block ID")
                mapping = variant.get("faces", {})
                if not isinstance(mapping, dict) or set(mapping) - {
                    "up",
                    "down",
                    "north",
                    "south",
                    "east",
                    "west",
                }:
                    raise ValueError("Invalid orientation face colors")
                variants.append(
                    (oriented, tuple(sorted((k, rgb_check(v)) for k, v in mapping.items())))
                )
            if len(variants) > 48 or len({v[0] for v in variants}) != len(variants):
                raise ValueError("Invalid orientation list")
            legacy_id, legacy_data = entry.get("legacy_id", -1), entry.get("legacy_data", 0)
            if (
                type(legacy_id) is not int
                or not -1 <= legacy_id <= 4095
                or type(legacy_data) is not int
                or not 0 <= legacy_data <= 15
            ):
                raise ValueError("Invalid legacy block ID or data")
            if legacy and legacy_id < 0:
                raise ValueError("Legacy profiles require numeric IDs for every block")
            blocks.append(
                Block(
                    state,
                    rgb_check(entry.get("rgb")),
                    category,
                    tuple(sorted((k, rgb_check(v)) for k, v in faces.items())),
                    gravity,
                    legacy_id,
                    legacy_data,
                    shape,
                    tuple(appearance),
                    tuple(variants),
                )
            )
        result[ident] = Profile(
            ident, data_version, tuple(blocks), legacy, raw.get("litematic", True)
        )
    return result


def load_file(path):
    with open(path, "rb") as stream:
        data = stream.read(MAX_PALETTE_BYTES + 1)
    if len(data) > MAX_PALETTE_BYTES:
        raise ValueError("Palette files are limited to 16 MiB")
    try:
        document = json.loads(data.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Palette must be a UTF-8 JSON file") from exc
    parse_document(document)
    return document


def profile_document(profile, blocks=None):
    entries = []
    for b in blocks if blocks is not None else profile.blocks:
        raw = {"state": b.state, "rgb": list(b.rgb), "category": b.category, "shape": b.shape}
        if b.faces:
            raw["faces"] = dict(b.faces)
        if b.gravity:
            raw["gravity"] = True
        if b.appearance:
            raw["appearance"] = list(b.appearance)
        if b.variants:
            raw["variants"] = [
                {"state": state, "faces": dict(faces)} for state, faces in b.variants
            ]
        if profile.legacy:
            raw.update(legacy_id=b.legacy_id, legacy_data=b.legacy_data)
        entries.append(raw)
    return {
        "schema_version": 1,
        "profiles": [
            {
                "id": profile.id,
                "data_version": profile.data_version,
                "legacy": profile.legacy,
                "litematic": profile.litematic,
                "blocks": entries,
            }
        ],
    }


def linear(value):
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def srgb(value):
    return 12.92 * value if value <= 0.0031308 else 1.055 * max(value, 0.0) ** (1 / 2.4) - 0.055


def oklab(rgb: RGB) -> tuple[float, float, float]:
    r, g, b = (linear(c / 255) for c in rgb)
    cone_l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (
        0.2104542553 * cone_l + 0.793617785 * m - 0.0040720468 * s,
        1.9779984951 * cone_l - 2.428592205 * m + 0.4505937099 * s,
        0.0259040371 * cone_l + 0.7827717662 * m - 0.808675766 * s,
    )


class Matcher:
    def __init__(self, blocks):
        if not blocks:
            raise ValueError("No allowed blocks. Enable some blocks or clear the blacklist.")
        self.blocks = tuple(blocks)
        self.labs = [oklab(b.rgb) for b in blocks]
        self.nearest = lru_cache(maxsize=32768)(self._nearest)

    def _nearest(self, rgb):
        lab = oklab(rgb)
        return min(
            range(len(self.blocks)),
            key=lambda i: sum((a - b) ** 2 for a, b in zip(lab, self.labs[i])),
        )


def allowed_blocks(blocks, whitelist=None, blacklist=(), allow_gravity=False, allow_special=False):
    whitelist = None if whitelist is None else set(whitelist)
    blacklist = set(blacklist)
    result = [
        b
        for b in blocks
        if (whitelist is None or b.state in whitelist)
        and b.state not in blacklist
        and (allow_gravity or not b.gravity)
        and (allow_special or not b.appearance)
    ]
    if not result:
        raise ValueError("No allowed blocks remain after your filters")
    return result
