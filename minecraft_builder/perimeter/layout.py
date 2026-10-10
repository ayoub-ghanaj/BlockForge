"""Image fitting, sparse perimeter composition and conservative surface protection."""

import math
from collections import defaultdict
from itertools import permutations

import numpy as np

from ..core.palette import oklab
from ..core.shapes import resolve_stairs, split_state, state_mask
from . import covers
from .materials import emission, is_glass, light_threshold, selected_lights, transmits_light
from .streaming import MAX_BLOCKS, MAX_VOLUME

FACES = ("floor", "north", "south", "west", "east")


def fit_image(
    pixels, width, height, mode="FIT", background=(32, 32, 32), flip_x=False, flip_y=False
):
    """Input/output rows run from image top to bottom; pixels are sRGB bytes."""
    pixels = np.asarray(pixels, dtype=np.float32)
    if pixels.ndim != 3 or pixels.shape[2] not in (3, 4):
        raise ValueError("Expected an RGB or RGBA image")
    if flip_x:
        pixels = pixels[:, ::-1]
    if flip_y:
        pixels = pixels[::-1]
    ih, iw = pixels.shape[:2]
    if mode == "PAD" and (iw > width or ih > height):
        raise ValueError("Image is larger than this surface. Choose Fit, Fill or Crop.")
    if mode == "STRETCH":
        scale_x, scale_y = width / iw, height / ih
    elif mode in ("FIT", "FILL"):
        scale_x = scale_y = (min if mode == "FIT" else max)(width / iw, height / ih)
    elif mode in ("CROP", "PAD"):
        scale_x = scale_y = 1
    else:
        raise ValueError("Unknown image sizing mode")
    xs = (np.arange(width) + 0.5 - width / 2) / scale_x + iw / 2 - 0.5
    ys = (np.arange(height) + 0.5 - height / 2) / scale_y + ih / 2 - 0.5
    valid = (
        (ys[:, None] >= -0.5)
        & (ys[:, None] < ih - 0.5)
        & (xs[None, :] >= -0.5)
        & (xs[None, :] < iw - 0.5)
    )
    xs = np.clip(xs, 0, iw - 1)
    ys = np.clip(ys, 0, ih - 1)
    x0 = np.floor(xs).astype(int)
    y0 = np.floor(ys).astype(int)
    tx = (xs - x0)[None, :, None]
    ty = (ys - y0)[:, None, None]
    x1 = np.minimum(x0 + 1, iw - 1)
    y1 = np.minimum(y0 + 1, ih - 1)
    colors = (1 - ty) * (
        (1 - tx) * pixels[y0[:, None], x0[None, :]] + tx * pixels[y0[:, None], x1[None, :]]
    )
    colors += ty * (
        (1 - tx) * pixels[y1[:, None], x0[None, :]] + tx * pixels[y1[:, None], x1[None, :]]
    )
    if colors.shape[2] == 4:
        alpha = colors[:, :, 3:4] / 255
        colors = colors[:, :, :3] * alpha + np.array(background) * (1 - alpha)
    colors[~valid] = background
    return np.rint(colors).clip(0, 255).astype(np.uint8)


def lab_array(rgb):
    rgb = np.asarray(rgb, dtype=np.float32) / 255
    rgb = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    lms = (
        rgb
        @ np.array(
            [
                [0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005],
            ],
            dtype=np.float32,
        ).T
    )
    return (
        np.cbrt(lms)
        @ np.array(
            [
                [0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660],
            ],
            dtype=np.float32,
        ).T
    )


def match_image(rgb, blocks, face=None):
    flat = np.asarray(rgb, dtype=np.uint8).reshape(-1, 3)
    colors, inverse = np.unique(flat, axis=0, return_inverse=True)
    from ..core.appearance import face_color

    candidates = np.array(
        [oklab(face_color(b, face) if face else b.rgb) for b in blocks], dtype=np.float32
    )
    norms = (candidates * candidates).sum(axis=1)
    indices = np.empty(len(colors), dtype=np.int32)
    for start in range(0, len(colors), 4096):
        labs = lab_array(colors[start : start + 4096])
        distances = (labs * labs).sum(axis=1)[:, None] + norms[None, :] - 2 * (labs @ candidates.T)
        indices[start : start + len(labs)] = distances.argmin(axis=1)
    return indices[inverse].reshape(rgb.shape[:2])


def face_size(face, width, depth, height):
    return (
        (width, depth)
        if face == "floor"
        else ((width if face in ("north", "south") else depth), height)
    )


def face_position(face, column, row, width, depth, height):
    # Wall images read left-to-right when viewed from INSIDE the perimeter.
    if face == "floor":
        return (column + 1, 0, row + 1)
    if face == "north":
        return (column + 1, height - row, 0)
    if face == "south":
        return (width - column, height - row, depth + 1)
    if face == "west":
        return (0, height - row, depth - column)
    if face == "east":
        return (width + 1, height - row, column + 1)
    raise ValueError("Unknown perimeter face")


def tops(cells, states, shapes, spawnable_only=False):
    for pos, index in list(cells.items()):
        state = states[index]
        if is_glass(state) or state.split("[")[0].endswith("_leaves"):
            continue
        mask = state_mask(state, shapes[index])
        if spawnable_only and mask & 240 != 240:
            continue
        x, y, z = pos
        if (x, y + 1, z) not in cells:
            yield pos


def lit_path(target, source, cells, states):
    """A clear shortest axis-aligned path is a conservative lighting proof.

    Treat partial/unknown shapes as opaque. This may add extra lights, but never
    assumes light can travel through an opaque face of an imported decoration.
    """
    for axes in permutations(range(3)):
        pos = list(source)
        clear = True
        for axis in axes:
            while pos[axis] != target[axis]:
                pos[axis] += 1 if target[axis] > pos[axis] else -1
                index = cells.get(tuple(pos))
                if index is not None and not transmits_light(states[index]):
                    clear = False
                    break
            if not clear:
                break
        if clear:
            return True
    return False


def protect(
    cells,
    states,
    colors,
    shapes,
    mode,
    profile,
    glass_state="minecraft:glass",
    light_state="AUTO",
    cover_kind="GLASS",
    cover_state="",
):
    def material(state, color, shape="cube"):
        if state not in states:
            states.append(state)
            colors.append(list(color))
            shapes.append(shape)
        return states.index(state)

    options = covers.choices(profile, cover_kind)
    selected_state = (
        glass_state
        if cover_kind == "GLASS"
        else cover_state or (options[0].state if options else "")
    )
    cover_block = next((b for b in options if b.state == selected_state), None)
    if mode in ("GLASS", "BOTH") and cover_block is None:
        raise ValueError("Choose a cover material available in this version")
    cover = (
        material(cover_block.state, cover_block.rgb, cover_block.shape)
        if mode in ("GLASS", "BOTH")
        else None
    )
    lights = selected_lights(profile, light_state) if mode in ("LIGHTS", "BOTH") else []
    threshold = light_threshold(profile)
    report = {
        "mode": mode,
        "glass_material": glass_state,
        "cover_kind": cover_kind,
        "cover_state": selected_state,
        "cover_blocks": 0,
        "lighting_choice": light_state,
        "glass_blocks": 0,
        "light_blocks": 0,
        "light_threshold": threshold,
        "light_checks": [],
        "light_materials": {},
    }
    if lights:
        light_indices = [material(b.state, b.rgb) for b in lights]
        labs = [oklab(b.rgb) for b in lights]
        choices = {}
        surfaces = list(tops(cells, states, shapes, True))
        buckets = defaultdict(list)
        sources = {}

        def register(pos, level):
            sources[pos] = level
            buckets[tuple(v // 16 for v in pos)].append(pos)

        for pos, index in cells.items():
            level = emission(states[index])
            if level:
                register(pos, level)

        def add(pos):
            existing = cells[pos]
            target = pos if shapes[existing] == "cube" else (pos[0], pos[1] + 1, pos[2])
            if target in sources:
                return
            if existing not in choices:
                rgb = oklab(colors[existing])
                choices[existing] = min(
                    range(len(lights)),
                    key=lambda i: sum((a - b) ** 2 for a, b in zip(rgb, labs[i])),
                )
            choice = choices[existing]
            cells[target] = light_indices[choice]
            register(target, emission(lights[choice].state))
            report["light_blocks"] += 1
            state = lights[choice].state
            report["light_materials"][state] = report["light_materials"].get(state, 0) + 1

        # An even floor grid looks intentional; irregular decorations get extra
        # lights only when no clear path proves the requested light level.
        spacing = max(1, min(emission(b.state) for b in lights) - threshold - 1)
        for pos in surfaces:
            if pos[0] % spacing == 0 and pos[2] % spacing == 0:
                add(pos)
        for number, pos in enumerate(surfaces):
            target = (pos[0], pos[1] + 1, pos[2])
            if target in cells:
                continue
            bx, by, bz = (v // 16 for v in target)
            safe = False
            for x in range(bx - 1, bx + 2):
                for y in range(by - 1, by + 2):
                    for z in range(bz - 1, bz + 2):
                        for source in buckets.get((x, y, z), ()):
                            if sum(abs(a - b) for a, b in zip(source, target)) <= sources[
                                source
                            ] - threshold and lit_path(target, source, cells, states):
                                safe = True
                                break
                        if safe:
                            break
                    if safe:
                        break
                if safe:
                    break
            if not safe:
                add(pos)
            if number % 2048 == 0:
                yield "Lighting exposed surfaces", number / max(1, len(surfaces))
        report["light_checks"] = [
            list((x, y + 1, z)) for x, y, z in tops(cells, states, shapes, True)
        ]
    if cover is not None:
        # Support-sensitive thin covers only go on a full top face. Bottom slabs
        # and bottom stairs already have no full spawnable top and need no cover.
        surfaces = list(tops(cells, states, shapes, cover_kind != "GLASS"))
        for pos in surfaces:
            index = cells[pos]
            if not covers.supported(cover_block.state, states[index], shapes[index]):
                raise ValueError(
                    f"{cover_block.state.split('[')[0]} needs sturdy support at {pos}; "
                    "choose glass, carpet, a bottom slab or a closed trapdoor instead"
                )
        for pos in surfaces:
            x, y, z = pos
            cells[x, y + 1, z] = cover
            report["cover_blocks"] += 1
        if cover_kind == "GLASS":
            report["glass_blocks"] = report["cover_blocks"]
        elif mode == "BOTH":
            report["light_checks"] = []  # Solid/thin cover occupies those feet positions.
    yield "result", report


def compose(
    width,
    depth,
    height,
    face_images,
    blocks,
    profile,
    background=(32, 32, 32),
    protection="GLASS",
    decorations=(),
    glass_state="minecraft:glass",
    light_state="AUTO",
    cover_kind="GLASS",
    cover_state="",
    face_matching=False,
):
    if not (1 <= width <= 2048 and 1 <= depth <= 2048 and 1 <= height <= 256):
        raise ValueError("Perimeter size is outside supported limits")
    estimated = sum(
        math.prod(face_size(f, width, depth, height))
        for f, spec in face_images.items()
        if spec is not None
    )
    if estimated > MAX_BLOCKS:
        raise ValueError("Image surfaces alone exceed two million blocks; reduce dimensions")
    cubes = [b for b in blocks if b.shape == "cube"]
    if not cubes:
        raise ValueError("Image surfaces need at least one allowed full cube block")
    if face_matching:
        from ..core.appearance import oriented_blocks

        cubes = [oriented for block in cubes for oriented, _ in oriented_blocks(block)]
    cells = {}
    states = []
    colors = []
    shapes = []

    def state_index(state, rgb, shape):
        index = index_by_state.get(state)
        if index is None:
            index = len(states)
            index_by_state[state] = index
            states.append(state)
            colors.append(list(rgb))
            shapes.append(shape)
        return index

    index_by_state = {}
    cube_indices = [state_index(b.state, b.rgb, "cube") for b in cubes]
    background_index = cube_indices[
        int(match_image(np.array([[background]], dtype=np.uint8), cubes)[0, 0])
    ]
    enabled = []
    for face in FACES:
        spec = face_images.get(face)
        if spec is None:
            continue
        fw, fh = face_size(face, width, depth, height)
        enabled.append(face)
        pixels = spec.get("pixels")
        visible = (
            {"floor": "up", "north": "south", "south": "north", "west": "east", "east": "west"}[
                face
            ]
            if face_matching
            else None
        )
        if pixels is None:
            face_background = cube_indices[
                int(match_image(np.array([[background]], dtype=np.uint8), cubes, visible)[0, 0])
            ]
            matched = np.full((fh, fw), face_background, dtype=np.int32)
        else:
            fitted = fit_image(
                pixels,
                fw,
                fh,
                spec.get("mode", "FIT"),
                background,
                spec.get("flip_x", False),
                spec.get("flip_y", False),
            )
            matched = np.asarray(cube_indices, dtype=np.int32)[match_image(fitted, cubes, visible)]
        for row in range(fh):
            for column in range(fw):
                cells[face_position(face, column, row, width, depth, height)] = int(
                    matched[row, column]
                )
            if row % 32 == 0:
                yield "Building " + face, 0.1 + 0.45 * (FACES.index(face) + row / max(1, fh)) / 5
    # Plain corner posts close the wall seams; never mirror the neighboring image.
    for x, z, adjacent in [
        (0, 0, ("north", "west")),
        (width + 1, 0, ("north", "east")),
        (0, depth + 1, ("south", "west")),
        (width + 1, depth + 1, ("south", "east")),
    ]:
        if all(face in enabled for face in adjacent):
            for y in range(1, height + 1):
                cells[x, y, z] = background_index
    deco_positions = set()
    overlaps = 0
    for deco, offset in decorations:
        indices = [
            state_index(s, rgb, shape)
            for s, rgb, shape in zip(deco["palette"], deco["colors"], deco["shapes"])
        ]
        for x, y, z, index in deco["cells"]:
            pos = (x + offset[0] + 1, y + offset[1] + 1, z + offset[2] + 1)
            if not (1 <= pos[0] <= width and 1 <= pos[2] <= depth and 1 <= pos[1] <= height):
                raise ValueError(
                    "A decoration leaves the interior bounds; move/scale it inside the perimeter guide"
                )
            if pos in cells:
                overlaps += 1
            cells[pos] = indices[index]
            deco_positions.add(pos)
    if not cells:
        raise ValueError("Enable a floor/wall or add a decoration")
    if len(cells) > MAX_BLOCKS:
        raise ValueError("Too many perimeter blocks; reduce dimensions")
    for stage, value in protect(
        cells,
        states,
        colors,
        shapes,
        protection,
        profile,
        glass_state,
        light_state,
        cover_kind,
        cover_state,
    ):
        if stage == "result":
            protection_report = value
        else:
            yield stage, 0.6 + value * 0.25
    index_by_state.update({state: i for i, state in enumerate(states)})
    kinds = {split_state(s)[0]: shape for s, shape in zip(states, shapes)}
    changed = resolve_stairs({p: states[i] for p, i in cells.items()}, kinds)
    old_metadata = {split_state(s)[0]: (c, k) for s, c, k in zip(states, colors, shapes)}
    for pos, state in changed.items():
        color, kind = old_metadata[split_state(state)[0]]
        cells[pos] = state_index(state, color, kind)
    used = sorted(set(cells.values()))
    remap = {v: i for i, v in enumerate(used)}
    palette = [states[i] for i in used]
    palette_shapes = [shapes[i] for i in used]
    origin = tuple(min(p[i] for p in cells) for i in range(3))
    size = [max(p[i] for p in cells) - origin[i] + 1 for i in range(3)]
    if math.prod(size) > MAX_VOLUME:
        raise ValueError(
            "This perimeter exceeds 64 million bounding cells; lower wall height or dimensions"
        )
    protection_report["light_checks"] = [
        [p[i] - origin[i] for i in range(3)] for p in protection_report["light_checks"]
    ]
    result = {
        "size": size,
        "version": profile.id,
        "data_version": profile.data_version,
        "palette": palette,
        "colors": [colors[i] for i in used],
        "shapes": palette_shapes,
        "masks": [state_mask(s, k) for s, k in zip(palette, palette_shapes)],
        "cells": [
            [*(pos[a] - origin[a] for a in range(3)), remap[i]]
            for pos, i in sorted(cells.items(), key=lambda p: (p[0][1], p[0][2], p[0][0]))
        ],
        "perimeter": {
            "width": width,
            "depth": depth,
            "height": height,
            "faces": enabled,
            "origin": list(origin),
            "decorations": [[p[i] - origin[i] for i in range(3)] for p in sorted(deco_positions)],
            "protection": protection_report,
        },
        "warnings": (
            ["Lighting alone does not prevent slime-chunk spawns; use ground cover."]
            if protection == "LIGHTS"
            else []
        )
        + (
            [f"{overlaps} overlapping decoration cells used the last decoration."]
            if overlaps
            else []
        ),
    }
    if len(result["cells"]) > MAX_BLOCKS:
        raise ValueError(
            "Protection raises the build above two million placed blocks; reduce dimensions"
        )
    yield "result", result
