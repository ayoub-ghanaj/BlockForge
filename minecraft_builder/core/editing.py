"""Sparse saved block overrides, neighbor-aware changes, and voxel ray picking."""

import copy
import json
import math

from .shapes import connected_shape, split_state, state_mask, with_properties

BASE = "@generated"


def key(pos):
    return ",".join(map(str, pos))


def position(text):
    return tuple(map(int, text.split(",")))


def empty_document():
    return {"schema_version": 1, "patches": {}, "undo": [], "redo": []}


class Editor:
    def __init__(self, build, document, materials, limits, volume_limit, block_limit=2_000_000):
        self.build = build
        self.document = copy.deepcopy(document)
        self.materials = dict(materials)
        self.limits = tuple(limits)
        self.volume_limit = volume_limit
        self.block_limit = block_limit
        self.origin = tuple(build.get("perimeter", {}).get("origin", (0, 0, 0)))
        self.low = self.origin
        self.high = tuple(self.origin[i] + build["size"][i] - 1 for i in range(3))
        self.base_low = self.low
        self.base_high = self.high
        self.base = {
            tuple(p[i] + self.origin[i] for i in range(3)): build["palette"][p[3]]
            for p in build["cells"]
        }
        for state, color, shape in zip(build["palette"], build["colors"], build["shapes"]):
            self.materials.setdefault(state, (tuple(color), shape))
        self.cells = dict(self.base)
        self.skipped = []
        for text, state in self.document["patches"].items():
            pos = position(text)
            try:
                self.check(pos, state)
            except ValueError:
                self.skipped.append(text)
                continue
            self.assign(pos, state)
        self.resolve({p for p, state in self.cells.items() if self.materials[state][1] == "stairs"})

    def check(self, pos, state, capacity=True):
        if state == BASE:
            return
        if len(pos) != 3 or any(
            type(v) is not int or not 0 <= v < self.limits[i] for i, v in enumerate(pos)
        ):
            raise ValueError("Block is outside the selected build area")
        if state not in (None, BASE) and state not in self.materials:
            raise ValueError("Block is unavailable in the selected palette")
        if capacity and state not in (None, BASE):
            low = tuple(min(self.low[i], pos[i]) for i in range(3))
            high = tuple(max(self.high[i], pos[i]) for i in range(3))
            if math.prod(high[i] - low[i] + 1 for i in range(3)) > self.volume_limit:
                raise ValueError("This addition exceeds the bounding-volume limit")
            if pos not in self.cells and len(self.cells) >= self.block_limit:
                raise ValueError("The placed-block limit has been reached")

    def assign(self, pos, state):
        if state == BASE:
            state = self.base.get(pos)
        if state is None:
            self.cells.pop(pos, None)
        else:
            self.cells[pos] = state
            self.low = tuple(min(self.low[i], pos[i]) for i in range(3))
            self.high = tuple(max(self.high[i], pos[i]) for i in range(3))

    def resolve(self, positions):
        affected = set(positions)
        for p in positions:
            for delta in ((-1, 0, 0), (1, 0, 0), (0, 0, -1), (0, 0, 1)):
                affected.add(tuple(p[i] + delta[i] for i in range(3)))

        def lookup(pos):
            state = self.cells.get(pos)
            return split_state(state)[1] if state and self.materials[state][1] == "stairs" else None

        for pos in affected:
            state = self.cells.get(pos)
            if state and self.materials[state][1] == "stairs":
                new = with_properties(state, shape=connected_shape(pos, state, lookup))
                self.materials[new] = self.materials[state]
                self.cells[pos] = new
        return affected

    def change(self, changes, record=True):
        invalid = set()
        for pos, state in changes.items():
            try:
                self.check(pos, state, False)
            except ValueError:
                if record:
                    raise
                invalid.add(pos)
        effective = {
            p: self.base.get(p) if state == BASE or p in invalid else state
            for p, state in changes.items()
        }
        remaining = len(self.cells) + sum(
            (
                1
                if s is not None and p not in self.cells
                else -1
                if s is None and p in self.cells
                else 0
            )
            for p, s in effective.items()
        )
        if remaining < 1:
            raise ValueError("Keep at least one block in the build")
        if remaining > self.block_limit:
            raise ValueError("The complete operation exceeds the placed-block limit")
        low = list(self.low)
        high = list(self.high)
        for p, s in effective.items():
            if s is not None:
                for i in range(3):
                    low[i] = min(low[i], p[i])
                    high[i] = max(high[i], p[i])
        if math.prod(high[i] - low[i] + 1 for i in range(3)) > self.volume_limit:
            low = list(self.base_low)
            high = list(self.base_high)
            for p in self.cells.keys() | effective.keys():
                if effective.get(p, self.cells.get(p)) is None:
                    continue
                for i in range(3):
                    low[i] = min(low[i], p[i])
                    high[i] = max(high[i], p[i])
        if math.prod(high[i] - low[i] + 1 for i in range(3)) > self.volume_limit:
            raise ValueError("The complete operation exceeds the bounding-volume limit")
        row = [
            [key(pos), self.document["patches"].get(key(pos), BASE), state]
            for pos, state in changes.items()
            if self.document["patches"].get(key(pos), BASE) != state
        ]
        if len(row) > 262144:
            raise ValueError("Change at most 262,144 cells per operation")
        proposed = copy.deepcopy(self.document)
        for text, old, state in row:
            if state == BASE:
                proposed["patches"].pop(text, None)
            else:
                proposed["patches"][text] = state
        if record and row:
            proposed["undo"] = (proposed["undo"] + [row])[-100:]
            proposed["redo"] = []
            while len(proposed["undo"]) > 1 and sum(map(len, proposed["undo"])) > 500000:
                proposed["undo"].pop(0)
        if len(json.dumps(proposed, separators=(",", ":"))) > 128 * 1024 * 1024:
            raise ValueError(
                "This operation exceeds the saved edit budget; use a smaller selection"
            )
        self.document = proposed
        for pos, state in changes.items():
            text = key(pos)
            self.assign(pos, BASE if pos in invalid else state)
            if text in self.skipped:
                self.skipped.remove(text)
            if pos in invalid:
                self.skipped.append(text)
        # Bounds include the generated area, then only still-applied additions.
        self.low = self.base_low
        self.high = self.base_high
        for text, state in self.document["patches"].items():
            if state is None or text in self.skipped:
                continue
            pos = position(text)
            self.low = tuple(min(self.low[i], pos[i]) for i in range(3))
            self.high = tuple(max(self.high[i], pos[i]) for i in range(3))
        return self.resolve(set(changes))

    def undo(self, redo=False):
        source = "redo" if redo else "undo"
        dest = "undo" if redo else "redo"
        if not self.document[source]:
            return set()
        row = self.document[source][-1]
        affected = self.change(
            {position(p): after if redo else before for p, before, after in row}, False
        )
        self.document[source].pop()
        self.document[dest].append(row)
        return affected

    def result(self):
        if not self.cells:
            raise ValueError("Manual edits removed every block; clear edits or add a block")
        used = sorted(set(self.cells.values()))
        indices = {s: i for i, s in enumerate(used)}
        result = {
            **self.build,
            "size": [self.high[i] - self.low[i] + 1 for i in range(3)],
            "palette": used,
            "colors": [list(self.materials[s][0]) for s in used],
            "shapes": [self.materials[s][1] for s in used],
            "masks": [state_mask(s, self.materials[s][1]) for s in used],
            "cells": [
                [*(p[i] - self.low[i] for i in range(3)), indices[s]]
                for p, s in sorted(
                    self.cells.items(), key=lambda item: (item[0][1], item[0][2], item[0][0])
                )
            ],
        }
        if "perimeter" in result:
            result["perimeter"] = copy.deepcopy(result["perimeter"])
            info = result["perimeter"]
            info["origin"] = list(self.low)
            info["decorations"] = [
                [p[i] + self.origin[i] - self.low[i] for i in range(3)] for p in info["decorations"]
            ]
            info["protection"]["light_checks"] = []
            info["protection"]["manual_edits_require_inspection"] = bool(self.document["patches"])
        result["manual_edits"] = {
            "applied": len(self.document["patches"]) - len(self.skipped),
            "skipped": len(self.skipped),
        }
        result["warnings"] = list(result.get("warnings", []))
        if self.skipped:
            result["warnings"].append(
                f"{len(self.skipped)} saved edits are outside this size or palette and were skipped"
            )
        return result


def ray_pick(cells, materials, limits, origin, direction, ignore=None):
    """Ray traverse half-block cells so slabs/stairs are picked by actual shape."""
    length = math.sqrt(sum(v * v for v in direction))
    if length < 1e-12:
        return None
    d = tuple(v / length for v in direction)
    near = 0.0
    far = float("inf")
    entry = None
    for axis in range(3):
        if abs(d[axis]) < 1e-12:
            if origin[axis] < 0 or origin[axis] >= limits[axis]:
                return None
            continue
        a = (0 - origin[axis]) / d[axis]
        b = (limits[axis] - origin[axis]) / d[axis]
        lower = min(a, b)
        upper = max(a, b)
        if lower > near:
            near = lower
            entry = axis
        far = min(far, upper)
    if far < near:
        return None
    point = [origin[i] + d[i] * (near + 1e-7) for i in range(3)]
    voxel = [math.floor(v * 2) for v in point]
    step = [1 if v > 0 else -1 for v in d]
    tmax = [
        near + (((voxel[i] + (1 if d[i] > 0 else 0)) / 2 - point[i]) / d[i])
        if abs(d[i]) > 1e-12
        else float("inf")
        for i in range(3)
    ]
    delta = [abs(0.5 / v) if abs(v) > 1e-12 else float("inf") for v in d]
    axis = entry if entry is not None else max(range(3), key=lambda i: abs(d[i]))
    for _ in range(2 * sum(limits) + 16):
        pos = tuple(v // 2 for v in voxel)
        if any(v < 0 or v >= limits[i] for i, v in enumerate(pos)):
            return None
        state = cells.get(pos)
        if state and not (ignore and ignore(state)):
            if materials[state][1] == "cover":
                from ..perimeter.covers import boxes

                for bounds in boxes(state):
                    enter = 0.0
                    leave = float("inf")
                    face = axis
                    for a in range(3):
                        lo = pos[a] + bounds[a]
                        hi = pos[a] + bounds[a + 3]
                        if abs(d[a]) < 1e-12:
                            if not lo <= origin[a] <= hi:
                                leave = -1
                                break
                        else:
                            t0 = (lo - origin[a]) / d[a]
                            t1 = (hi - origin[a]) / d[a]
                            if min(t0, t1) > enter:
                                enter = min(t0, t1)
                                face = a
                            leave = min(leave, max(t0, t1))
                    if leave >= enter:
                        return pos, tuple(-step[i] if i == face else 0 for i in range(3)), state
                state = None
        if state and not (ignore and ignore(state)):
            bit = (voxel[0] % 2) + 2 * (voxel[2] % 2) + 4 * (voxel[1] % 2)
            if state_mask(state, materials[state][1]) & (1 << bit):
                normal = tuple(-step[i] if i == axis else 0 for i in range(3))
                return pos, normal, state
        axis = min(range(3), key=lambda i: tmax[i])
        if tmax[axis] > far:
            return None
        voxel[axis] += step[axis]
        tmax[axis] += delta[axis]
    return None
