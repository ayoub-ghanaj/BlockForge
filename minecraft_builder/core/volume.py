"""Sample mesh volumes at half-block resolution, then fit Minecraft shapes."""

import math
from collections import defaultdict

import numpy as np

from .palette import Matcher, oklab
from .shapes import orientations, resolve_stairs, split_state, state_mask


def erode(volume, iterations):
    current = volume.copy()
    for _ in range(iterations):
        result = np.zeros_like(current)
        result[1:-1, 1:-1, 1:-1] = (
            current[1:-1, 1:-1, 1:-1]
            & current[:-2, 1:-1, 1:-1]
            & current[2:, 1:-1, 1:-1]
            & current[1:-1, :-2, 1:-1]
            & current[1:-1, 2:, 1:-1]
            & current[1:-1, 1:-1, :-2]
            & current[1:-1, 1:-1, 2:]
        )
        current = result
    return current


def sample_volume(sources, size):
    """BVHs use Minecraft coordinates. Array order is X,Y,Z.

    Three scan directions preserve thin surfaces parallel to one of the rays.
    Separate objects are unioned, so overlapping component meshes stay solid.
    """
    from mathutils import Vector

    fine = tuple(v * 2 for v in size)
    result = np.zeros(fine, dtype=np.bool_)
    odd_columns = 0
    for obj_index, source in enumerate(sources):
        bvh = source["bvh"]
        low = np.maximum(0, np.floor(source["vertices"].min(axis=0) * 2).astype(int))
        high = np.minimum(
            np.array(fine), np.ceil(source["vertices"].max(axis=0) * 2).astype(int) + 1
        )
        for axis in range(3):
            others = [a for a in range(3) if a != axis]
            a, b = others
            direction = Vector(tuple(1.0 if i == axis else 0.0 for i in range(3)))
            for u in range(low[a], high[a]):
                for v in range(low[b], high[b]):
                    point = [0.0] * 3
                    point[a] = (u + 0.5) / 2
                    point[b] = (v + 0.5) / 2
                    point[axis] = -0.001
                    hits = []
                    while point[axis] < size[axis] + 0.001:
                        hit, normal, _, _ = bvh.ray_cast(
                            Vector(point), direction, size[axis] + 0.01 - point[axis]
                        )
                        if hit is None:
                            break
                        if not hits or abs(hit[axis] - hits[-1]) > 1e-5:
                            hits.append(float(hit[axis]))
                        point[axis] = float(hit[axis]) + 1e-5
                        if len(hits) > 4096:
                            raise ValueError(
                                "Too many intersecting surfaces in one column; simplify overlapping geometry"
                            )
                    if not hits:
                        continue
                    if len(hits) % 2:
                        odd_columns += 1
                        for hit in hits:
                            cell = [0, 0, 0]
                            cell[a] = u
                            cell[b] = v
                            cell[axis] = max(0, min(fine[axis] - 1, math.floor(hit * 2)))
                            result[tuple(cell)] = True
                    else:
                        for start, end in zip(hits[::2], hits[1::2]):
                            lo = max(0, math.ceil(start * 2 - 0.5 - 1e-6))
                            hi = min(fine[axis], math.ceil(end * 2 - 0.5 - 1e-6))
                            if hi <= lo:
                                lo = max(0, min(fine[axis] - 1, math.floor(start + end)))
                                hi = lo + 1
                            slicer = [0, 0, 0]
                            slicer[a] = u
                            slicer[b] = v
                            slicer[axis] = slice(lo, hi)
                            result[tuple(slicer)] = True
                if (u - low[a]) % 8 == 0:
                    yield (
                        "Sampling geometry",
                        (obj_index + (axis + (u - low[a] + 1) / max(1, high[a] - low[a])) / 3)
                        / len(sources),
                    )
    if not result.any():
        raise ValueError("No occupied cells found; increase dimensions or check the model geometry")
    yield "result", (result, odd_columns)


def masks_from_volume(volume):
    size = tuple(v // 2 for v in volume.shape)
    result = np.zeros(size, dtype=np.uint8)
    for y in range(2):
        for z in range(2):
            for x in range(2):
                result |= volume[x::2, y::2, z::2].astype(np.uint8) << (x + 2 * z + 4 * y)
    return result


class ShapeMatcher:
    def __init__(self, blocks, shape_weight=0.65):
        self.blocks = blocks
        self.weight = shape_weight
        groups = defaultdict(list)
        for block in blocks:
            groups[block.shape].append(block)
        self.matchers = {kind: Matcher(items) for kind, items in groups.items()}
        self.cache = {}

    def match(self, target, rgb):
        key = (int(target), tuple(rgb))
        if key in self.cache:
            return self.cache[key]
        candidates = []
        desired = oklab(rgb)
        for matcher in self.matchers.values():
            block = matcher.blocks[matcher.nearest(tuple(rgb))]
            color_error = sum((a - b) ** 2 for a, b in zip(desired, oklab(block.rgb)))
            for state, mask in (
                [(block.state, 255)] if block.shape == "cube" else orientations(block)
            ):
                # Prefer a slightly fuller silhouette to holes through a shell.
                # Missing volume costs more than an equal amount of extra volume.
                missing = (int(target) & ~mask).bit_count()
                extra = (mask & ~int(target)).bit_count()
                shape_error = (1.75 * missing + extra) / 8
                score = self.weight * shape_error + (1 - self.weight) * color_error
                candidates.append((score, shape_error, state, block))
        # Stable tie-breaks keep exports reproducible.
        _, _, state, block = min(candidates, key=lambda v: (v[0], v[1], v[2]))
        result = (state, block)
        if len(self.cache) < 100000:
            self.cache[key] = result
        return result


def convert(
    sources,
    size,
    blocks,
    sample_color,
    hollow=True,
    thickness=1,
    shape_weight=0.65,
    interior=None,
    face_matching=False,
):
    volume = None
    for stage, value in sample_volume(sources, size):
        if stage == "result":
            volume, odd = value
        else:
            yield stage, value * 0.60
    inner = erode(volume, thickness * 2)
    shape_volume = volume & ~inner if hollow else volume
    masks = masks_from_volume(shape_volume)
    interior_masks = masks_from_volume(inner) if not hollow and interior else None
    coordinates = np.argwhere(masks != 0)
    from .appearance import FaceMatcher, surface_samples

    matcher = (
        FaceMatcher(blocks, shape_weight) if face_matching else ShapeMatcher(blocks, shape_weight)
    )
    cells = {}
    chosen = {}
    for i, coord in enumerate(coordinates):
        pos = tuple(int(v) for v in coord)
        rgb = sample_color(tuple(v + 0.5 for v in pos))
        if interior and interior_masks is not None and interior_masks[pos] == 255:
            state, block = interior.state, interior
        else:
            state, block = (
                matcher.match(
                    int(masks[pos]), surface_samples(masks, pos, sample_color, rgb), tuple(rgb)
                )
                if face_matching
                else matcher.match(masks[pos], rgb)
            )
        cells[pos] = state
        chosen[split_state(state)[0]] = block
        if i % 512 == 0:
            yield "Matching blocks", 0.60 + 0.35 * i / max(1, len(coordinates))
    kinds = {split_state(b.state)[0]: b.shape for b in blocks}
    cells = resolve_stairs(cells, kinds)
    palette = sorted(set(cells.values()))
    indices = {state: i for i, state in enumerate(palette)}
    result = {
        "size": list(size),
        "palette": palette,
        "cells": [
            [*pos, indices[state]]
            for pos, state in sorted(cells.items(), key=lambda p: (p[0][1], p[0][2], p[0][0]))
        ],
        "colors": [list(chosen[split_state(s)[0]].rgb) for s in palette],
        "shapes": [kinds[split_state(s)[0]] for s in palette],
        "masks": [state_mask(s, kinds[split_state(s)[0]]) for s in palette],
        "warnings": (
            ["Open or ambiguous mesh surfaces were sampled; inspect thin areas in the preview."]
            if odd
            else []
        ),
    }
    yield "result", result
