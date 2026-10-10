"""Bundled, version-correct dry ground covers and their compact preview geometry."""

import gzip
import json
from functools import lru_cache
from pathlib import Path

from ..core.palette import Block
from ..core.shapes import state_mask
from .materials import GLASS, transmits_light

KINDS = [
    ("GLASS", "Glass", "Clear or colored glass"),
    ("BUTTON", "Buttons", "Small floor buttons; solid support required"),
    ("CARPET", "Carpet", "Thin colored carpet"),
    ("SLAB", "Bottom slabs", "Half-block cover"),
    ("TRAPDOOR", "Closed trapdoors", "A thin horizontal cover"),
    ("LEAVES", "Leaves", "Persistent leaves"),
    ("RAIL", "Rails", "Straight rails on solid support"),
    ("PLATE", "Pressure plates", "Unpowered plates on solid support"),
    ("LEVER", "Levers", "Floor-mounted levers"),
]


@lru_cache(maxsize=1)
def presets():
    return json.loads(
        gzip.decompress((Path(__file__).resolve().parents[1] / "data/covers.json.gz").read_bytes())
    )


def choices(profile, kind):
    if kind == "GLASS":
        by_state = {b.state: b for b in profile.blocks}
        return [by_state.get(b.state, b) for b in GLASS]
    data = presets().get(profile.id)
    if data is None:
        data = next(
            (v for v in presets().values() if v["data_version"] == profile.data_version),
            {"blocks": []},
        )
    return [
        Block(
            row["state"],
            tuple(row["rgb"]),
            shape="slab" if kind == "SLAB" else "cube" if kind == "LEAVES" else "cover",
        )
        for row in data["blocks"]
        if row["kind"] == kind
    ]


@lru_cache(maxsize=4096)
def boxes(state):
    """Exact simple collision/display boxes; lever display is a compact stand-in."""
    name = state.split("[")[0]
    if name.endswith("_carpet"):
        return ((0, 0, 0, 1, 1 / 16, 1),)
    if name.endswith("_button"):
        return ((5 / 16, 0, 6 / 16, 11 / 16, 2 / 16, 10 / 16),)
    if name.endswith("_trapdoor"):
        return ((0, 0, 0, 1, 3 / 16, 1),)
    if name.endswith("_pressure_plate"):
        return ((1 / 16, 0, 1 / 16, 15 / 16, 1 / 16, 15 / 16),)
    if name.endswith("rail"):
        return ((0, 0, 0, 1, 2 / 16, 1),)
    if name == "minecraft:lever":
        return ((4 / 16, 0, 5 / 16, 12 / 16, 6 / 16, 11 / 16),)
    if "_slab[" in state and "type=bottom" in state:
        return ((0, 0, 0, 1, 0.5, 1),)
    return ((0, 0, 0, 1, 1, 1),)


def is_partial_cover(state):
    name = state.split("[")[0]
    return (
        name.endswith(("_carpet", "_button", "_trapdoor", "_pressure_plate", "rail"))
        or name == "minecraft:lever"
    )


def supported(state, below, shape="cube"):
    """Support for bundled floor covers, checked against Java 26.1.2.

    Shape occupancy alone does not prove a sturdy face: leaves and honey are
    explicit exceptions. Carpet only needs an occupied cell beneath it.
    """
    name = state.split("[")[0]
    if name.endswith("_trapdoor") or not is_partial_cover(state):
        return True
    if below is None:
        return False
    if name.endswith("_carpet"):
        return True
    support = below.split("[")[0]
    return (
        shape != "cover"
        and state_mask(below, shape) & 240 == 240
        and not support.endswith("_leaves")
        and support != "minecraft:honey_block"
    )


def blocks_light(state):
    return not (
        transmits_light(state) or is_partial_cover(state) or state.split("[")[0].endswith("_leaves")
    )
