"""Bounded selection and clipboard operations, independent of Blender/models."""

import math
from collections.abc import Iterator, Mapping

from .shapes import split_state, with_properties

MAX_SELECTION = 262144
Position = tuple[int, int, int]


def bounds(a: Position, b: Position, limits: Position) -> tuple[Position, Position]:
    """Return inclusive selection bounds after checking dimensions and capacity."""
    low = tuple(min(a[i], b[i]) for i in range(3))
    high = tuple(max(a[i], b[i]) for i in range(3))
    if any(not 0 <= low[i] <= high[i] < limits[i] for i in range(3)):
        raise ValueError("Selection leaves the build area")
    if math.prod(high[i] - low[i] + 1 for i in range(3)) > MAX_SELECTION:
        raise ValueError(
            "Select at most 262,144 cells per operation; split larger areas into sections"
        )
    return low, high


def positions(a: Position, b: Position, limits: Position) -> Iterator[Position]:
    low, high = bounds(a, b, limits)
    return (
        (x, y, z)
        for y in range(low[1], high[1] + 1)
        for z in range(low[2], high[2] + 1)
        for x in range(low[0], high[0] + 1)
    )


def brush_positions(center: Position, radius: int, limits: Position) -> Iterator[Position]:
    if not 0 <= radius <= 16:
        raise ValueError("Brush radius must be between 0 and 16 blocks")
    return (
        p
        for p in positions(
            tuple(max(0, c - radius) for c in center),
            tuple(min(limits[i] - 1, center[i] + radius) for i in range(3)),
            limits,
        )
        if sum((p[i] - center[i]) ** 2 for i in range(3)) <= radius * radius
    )


def copy(cells: Mapping[Position, str], a: Position, b: Position, limits: Position) -> dict:
    """Store occupied selection cells relative to its minimum corner."""
    low, high = bounds(a, b, limits)
    result = {"schema_version": 1, "size": [high[i] - low[i] + 1 for i in range(3)], "cells": []}
    for p in positions(a, b, limits):
        if p in cells:
            result["cells"].append([*(p[i] - low[i] for i in range(3)), cells[p]])
    return result


def mirrored_state(state: str, axis: str) -> str:
    if not axis:
        return state
    _, props = split_state(state)
    swap = {"X": ("east", "west"), "Y": ("up", "down"), "Z": ("north", "south")}[axis]
    changes = {}
    if props.get("facing") in swap:
        changes["facing"] = swap[1 - swap.index(props["facing"])]
    if axis == "Y":
        for key in ("half", "type"):
            if props.get(key) in ("top", "bottom"):
                changes[key] = "bottom" if props[key] == "top" else "top"
    elif props.get("shape") in ("inner_left", "inner_right", "outer_left", "outer_right"):
        changes["shape"] = (
            props["shape"]
            .replace("left", "RIGHT")
            .replace("right", "left")
            .replace("RIGHT", "right")
        )
    for key, other in ((swap[0], swap[1]), (swap[1], swap[0])):
        if key in props and other in props:
            changes[key] = props[other]
    return with_properties(state, **changes) if changes else state


def paste(clipboard, destination, cells, limits, overwrite=False, include_air=False, mirror=""):
    if not isinstance(clipboard, dict) or clipboard.get("schema_version") != 1:
        raise ValueError("Invalid block clipboard")
    size = clipboard.get("size", [])
    if len(size) != 3 or any(type(v) is not int or v < 1 for v in size):
        raise ValueError("Invalid clipboard dimensions")
    high = tuple(destination[i] + size[i] - 1 for i in range(3))
    bounds(destination, high, limits)
    content = {}
    axis = "XYZ".index(mirror) if mirror else None
    for row in clipboard.get("cells", []):
        if len(row) != 4 or any(
            type(v) is not int or not 0 <= v < size[i] for i, v in enumerate(row[:3])
        ):
            raise ValueError("Invalid clipboard block coordinate")
        p = list(row[:3])
        if axis is not None:
            p[axis] = size[axis] - 1 - p[axis]
        target = tuple(destination[i] + p[i] for i in range(3))
        if target in content:
            raise ValueError("Duplicate clipboard coordinate")
        content[target] = mirrored_state(row[3], mirror)
    if include_air:
        for p in positions(destination, high, limits):
            content.setdefault(p, None)
    if not overwrite and any(p in cells and cells[p] != s for p, s in content.items()):
        raise ValueError(
            "Paste overlaps existing blocks; move the cursor or enable Overwrite on paste"
        )
    return content
