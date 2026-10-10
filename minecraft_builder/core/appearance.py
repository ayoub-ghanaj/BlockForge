"""Directional color matching shared by arbitrary models and image surfaces."""

from dataclasses import replace
from functools import lru_cache

import numpy as np

from .palette import oklab
from .shapes import orientations

SIDES = ("west", "east", "down", "up", "north", "south")
NORMALS = ((-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1))


def oriented_blocks(block):
    """One entry per legal orientation; uniform custom palettes keep their color."""
    faces = dict(block.variants)
    for state, mask in orientations(block):
        yield replace(block, state=state, faces=faces.get(state, block.faces)), mask


def face_color(block, face):
    return dict(block.faces).get(face, block.rgb)


class FaceMatcher:
    def __init__(self, blocks, shape_weight=0.65):
        candidates = {}
        for block in blocks:
            for oriented, mask in oriented_blocks(block):
                colors = tuple(face_color(oriented, face) for face in SIDES)
                key = (mask, colors)
                previous = candidates.get(key)
                if previous is None or oriented.state < previous.state:
                    candidates[key] = oriented
        keys = list(candidates)
        self.blocks = [candidates[k] for k in keys]
        self.masks = np.array([k[0] for k in keys], dtype=np.uint16)
        self.labs = np.array([[oklab(rgb) for rgb in k[1]] for k in keys], dtype=np.float32)
        self.weight = shape_weight
        self.match = lru_cache(maxsize=32768)(self._match)

    def _match(self, target, samples, fallback):
        # samples: one (r,g,b,exposed area) tuple for each canonical direction.
        weights = np.array([s[3] for s in samples], dtype=np.float32)
        if not weights.any():
            weights[:] = 1
            samples = tuple((*fallback, 1) for _ in SIDES)
        wanted = np.array([oklab(s[:3]) for s in samples], dtype=np.float32)
        color = ((self.labs - wanted) ** 2).sum(axis=2) @ weights / weights.sum()
        missing = np.array([(target & ~int(m)).bit_count() for m in self.masks])
        extra = np.array([(int(m) & ~target).bit_count() for m in self.masks])
        shape = (1.75 * missing + extra) / 8
        costs = self.weight * shape + (1 - self.weight) * color
        best = min(
            np.flatnonzero(costs <= costs.min() + 1e-10),
            key=lambda i: (shape[i], self.blocks[i].state),
        )
        block = self.blocks[best]
        return block.state, block


@lru_cache(maxsize=32768)
def exposed_centers(mask, neighbors):
    """Average exposed half-cell face centers and areas, including stair risers."""
    result = []
    for delta, neighbor in zip(NORMALS, neighbors):
        points = []
        for y in range(2):
            for z in range(2):
                for x in range(2):
                    if not mask & (1 << (x + 2 * z + 4 * y)):
                        continue
                    xyz = (x, y, z)
                    next_xyz = tuple(xyz[i] + delta[i] for i in range(3))
                    local = all(0 <= n < 2 for n in next_xyz)
                    n = tuple(v % 2 for v in next_xyz)
                    if (mask if local else neighbor) & (1 << (n[0] + 2 * n[2] + 4 * n[1])):
                        continue
                    points.append(tuple((xyz[i] + 0.5 + delta[i] * 0.5) / 2 for i in range(3)))
        result.append(
            (tuple(sum(p[i] for p in points) / len(points) for i in range(3)), len(points))
            if points
            else ((0.5, 0.5, 0.5), 0)
        )
    return tuple(result)


def surface_samples(masks, pos, sample_color, fallback):
    neighbors = []
    for delta in NORMALS:
        other = tuple(pos[i] + delta[i] for i in range(3))
        neighbors.append(
            int(masks[other]) if all(0 <= other[i] < masks.shape[i] for i in range(3)) else 0
        )
    return tuple(
        (*(sample_color(tuple(pos[i] + point[i] for i in range(3))) if area else fallback), area)
        for point, area in exposed_centers(int(masks[pos]), tuple(neighbors))
    )
