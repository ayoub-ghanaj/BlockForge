"""Conservative surface voxelization and optional enclosed-volume fill."""

import math
from collections import deque
from dataclasses import dataclass

MAX_CELLS = 2_000_000
MAX_TRIANGLES = 1_000_000


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


@dataclass(frozen=True)
class Grid:
    origin: tuple
    scale: tuple
    size: tuple

    def point(self, p):
        return tuple((p[i] - self.origin[i]) * self.scale[i] for i in range(3))


def fit_grid(points, limits, preserve=True):
    if not points:
        raise ValueError("The selected meshes have no vertices")
    if len(limits) != 3 or any(type(v) is not int or not 1 <= v <= 512 for v in limits):
        raise ValueError("Dimensions must be integers from 1 to 512 blocks")
    if any(not math.isfinite(c) for p in points for c in p):
        raise ValueError("The model has non-finite coordinates")
    low = tuple(min(p[i] for p in points) for i in range(3))
    high = tuple(max(p[i] for p in points) for i in range(3))
    ext = sub(high, low)
    if max(ext) <= 1e-10:
        raise ValueError("The model has no measurable size")
    common = min(limits[i] / ext[i] for i in range(3) if ext[i] > 1e-10)
    scale = tuple(common if preserve or ext[i] <= 1e-10 else limits[i] / ext[i] for i in range(3))
    size = tuple(max(1, min(limits[i], math.ceil(ext[i] * scale[i] - 1e-8))) for i in range(3))
    if math.prod(size) > MAX_CELLS:
        raise ValueError(
            f"The grid needs {math.prod(size):,} cells; reduce dimensions below {MAX_CELLS:,} cells"
        )
    # Center planar geometry inside its one-cell thickness.
    origin = tuple(low[i] - (0.5 / scale[i] if ext[i] <= 1e-10 else 0) for i in range(3))
    return Grid(origin, scale, size)


def intersects(triangle, cell):
    """Separating-axis test: triangle versus a closed unit cube."""
    center = tuple(v + 0.5 for v in cell)
    vertices = [sub(v, center) for v in triangle]
    edges = [sub(vertices[(i + 1) % 3], vertices[i]) for i in range(3)]
    axes = [(1, 0, 0), (0, 1, 0), (0, 0, 1), cross(edges[0], edges[1])]
    for e in edges:
        axes.extend(((0, e[2], -e[1]), (-e[2], 0, e[0]), (e[1], -e[0], 0)))
    for axis in axes:
        r = 0.5 * sum(abs(c) for c in axis)
        projected = [dot(v, axis) for v in vertices]
        if min(projected) > r + 1e-9 or max(projected) < -r - 1e-9:
            return False
    return True


def triangle_cells(triangle, size):
    normal = cross(sub(triangle[1], triangle[0]), sub(triangle[2], triangle[0]))
    k = max(range(3), key=lambda a: abs(normal[a]))
    if abs(normal[k]) < 1e-14:
        return
    axes = [a for a in range(3) if a != k]
    i, j = axes
    low = [max(0, math.floor(min(v[a] for v in triangle) - 1e-8)) for a in range(3)]
    high = [min(size[a] - 1, math.floor(max(v[a] for v in triangle) + 1e-8)) for a in range(3)]
    d = dot(normal, triangle[0])
    for a in range(low[i], high[i] + 1):
        for b in range(low[j], high[j] + 1):
            depths = [
                (d - normal[i] * u - normal[j] * v) / normal[k]
                for u in (a, a + 1)
                for v in (b, b + 1)
            ]
            for c in range(
                max(low[k], math.floor(min(depths) - 1e-8)),
                min(high[k], math.floor(max(depths) + 1e-8)) + 1,
            ):
                cell = [0, 0, 0]
                cell[i], cell[j], cell[k] = a, b, c
                cell = tuple(cell)
                if intersects(triangle, cell):
                    yield cell


def closest_barycentric(point, triangle):
    """Closest point on a triangle; returns squared distance and barycentric weights."""
    a, b, c = triangle
    ab, ac, ap = sub(b, a), sub(c, a), sub(point, a)
    d1, d2 = dot(ab, ap), dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        weights = (1, 0, 0)
    else:
        bp = sub(point, b)
        d3, d4 = dot(ab, bp), dot(ac, bp)
        if d3 >= 0 and d4 <= d3:
            weights = (0, 1, 0)
        else:
            vc = d1 * d4 - d3 * d2
            if vc <= 0 and d1 >= 0 and d3 <= 0:
                v = d1 / (d1 - d3)
                weights = (1 - v, v, 0)
            else:
                cp = sub(point, c)
                d5, d6 = dot(ab, cp), dot(ac, cp)
                if d6 >= 0 and d5 <= d6:
                    weights = (0, 0, 1)
                else:
                    vb = d5 * d2 - d1 * d6
                    if vb <= 0 and d2 >= 0 and d6 <= 0:
                        w = d2 / (d2 - d6)
                        weights = (1 - w, 0, w)
                    else:
                        va = d3 * d6 - d5 * d4
                        if va <= 0 and d4 - d3 >= 0 and d5 - d6 >= 0:
                            w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
                            weights = (0, 1 - w, w)
                        else:
                            denom = va + vb + vc
                            if abs(denom) < 1e-20:
                                weights = (1, 0, 0)
                            else:
                                v, w = vb / denom, vc / denom
                                weights = (1 - v - w, v, w)
    closest = tuple(sum(weights[t] * triangle[t][i] for t in range(3)) for i in range(3))
    delta = sub(point, closest)
    return dot(delta, delta), weights


def neighbors(cell, size):
    for a in range(3):
        for step in (-1, 1):
            c = list(cell)
            c[a] += step
            if 0 <= c[a] < size[a]:
                yield tuple(c)


def voxelize(triangles, size, solid=False):
    """Yield progress, then ('result', cell -> nearest intersecting triangle).

    Interior cells use -1. Surface mode supports open meshes; solid mode fills
    enclosed cells, and depends on a closed voxel shell.
    """
    if not triangles or len(triangles) > MAX_TRIANGLES:
        raise ValueError("Select between 1 and 1,000,000 mesh triangles")
    if math.prod(size) > MAX_CELLS:
        raise ValueError("Grid cell limit exceeded")
    surface, distances = {}, {}
    operations = 0
    for index, triangle in enumerate(triangles):
        for cell in triangle_cells(triangle, size):
            p = tuple(v + 0.5 for v in cell)
            distance, _ = closest_barycentric(p, triangle)
            if distance < distances.get(cell, float("inf")):
                surface[cell] = index
                distances[cell] = distance
            operations += 1
            if operations % 4096 == 0:
                yield "surface", index / len(triangles)
        if index % 256 == 0:
            yield "surface", index / len(triangles)
    if not surface:
        raise ValueError("No surface could be generated; check the mesh for degenerate faces")
    if solid:
        empty = set()
        queue = deque()
        for axis in range(3):
            other = [a for a in range(3) if a != axis]
            for border in set((0, size[axis] - 1)):
                for i in range(size[other[0]]):
                    for j in range(size[other[1]]):
                        cell = [0, 0, 0]
                        cell[axis] = border
                        cell[other[0]] = i
                        cell[other[1]] = j
                        cell = tuple(cell)
                        if cell not in surface and cell not in empty:
                            empty.add(cell)
                            queue.append(cell)
        n = 0
        while queue:
            for cell in neighbors(queue.popleft(), size):
                if cell not in surface and cell not in empty:
                    empty.add(cell)
                    queue.append(cell)
            n += 1
            if n % 8192 == 0:
                yield "fill", n / math.prod(size)
        for y in range(size[1]):
            for z in range(size[2]):
                for x in range(size[0]):
                    cell = (x, y, z)
                    if cell not in surface and cell not in empty:
                        surface[cell] = -1
            yield "fill", (y + 1) / size[1]
    yield "result", surface
