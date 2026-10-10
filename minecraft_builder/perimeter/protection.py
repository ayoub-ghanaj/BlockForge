"""Conservative checks on the current block grid, including manual edits.

This reports supported dry covers and a lower bound on ordinary block lighting.
It does not infer biome, world height, slime chunks, spawners or raid mechanics.
"""

from collections import defaultdict

from ..core.shapes import split_state, state_mask
from .covers import is_partial_cover, supported
from .layout import lit_path
from .materials import emission, is_glass, light_threshold


def dry_surface(state, shape):
    name, props = split_state(state)
    if is_glass(state) or name.endswith("_leaves"):
        return True
    if shape == "slab":
        return props.get("type") == "bottom"
    if shape == "stairs":
        return props.get("half") == "bottom"
    if name.endswith("_trapdoor"):
        return props.get("open", "false") == "false" and props.get("half", "bottom") == "bottom"
    if name.endswith("_button") or name == "minecraft:lever":
        return props.get("face") == "floor"
    return name.endswith(("_carpet", "_pressure_plate", "rail"))


def check(build, profile, require_cover=True):
    origin = build.get("perimeter", {}).get("origin", (0, 0, 0))
    cells = {tuple(row[i] + origin[i] for i in range(3)): row[3] for row in build["cells"]}
    states = build["palette"]
    shapes = build["shapes"]
    threshold = light_threshold(profile)
    report = {
        "schema_version": 1,
        "version": profile.id,
        "status": "passed",
        "light_threshold": threshold,
        "require_dry_cover": require_cover,
        "surfaces": 0,
        "covered": 0,
        "proven_lit": 0,
        "unproven_light": 0,
        "uncovered": 0,
        "unsupported_covers": 0,
        "issue_count": 0,
        "issues": [],
        "highlight_limit": 10000,
        "light_checks": [],
        "covered_checks": [],
        "scope": "Supported dry ground surfaces and conservative block-light paths; no world/biome/spawner simulation",
    }
    buckets = defaultdict(list)
    for pos, index in cells.items():
        level = emission(states[index])
        if level:
            buckets[tuple(v // 16 for v in pos)].append((pos, level))

    def issue(pos, reason):
        report["issue_count"] += 1
        if len(report["issues"]) < report["highlight_limit"]:
            report["issues"].append([*pos, reason])

    def full_top(index):
        return (
            index is not None
            and state_mask(states[index], shapes[index]) & 240 == 240
            and shapes[index] != "cover"
        )

    def supported_at(index, below):
        return supported(
            states[index],
            states[below] if below is not None else None,
            shapes[below] if below is not None else "cube",
        )

    def covered(pos):
        report["covered"] += 1
        if len(report["covered_checks"]) < 10000:
            report["covered_checks"].append(list(pos))

    for number, (pos, index) in enumerate(cells.items()):
        if number % 2048 == 0:
            yield "Checking edited surfaces", number / max(1, len(cells))
        state = states[index]
        name, props = split_state(state)
        shape = shapes[index]
        below = cells.get((pos[0], pos[1] - 1, pos[2]))
        if is_partial_cover(state) and not supported_at(index, below):
            report["unsupported_covers"] += 1
            issue(pos, "unsupported_cover")
        above = (pos[0], pos[1] + 1, pos[2])
        over = cells.get(above)
        if dry_surface(state, shape):
            continue
        if not full_top(index):
            continue
        # A complete occupied feet cell is unavailable; its own top is checked
        # independently. Thin covers occupy feet space but need separate proof.
        if over is not None and shapes[over] == "cube":
            if dry_surface(states[over], shapes[over]):
                report["surfaces"] += 1
                covered(above)
            continue
        report["surfaces"] += 1
        if (
            over is not None
            and dry_surface(states[over], shapes[over])
            and supported_at(over, index)
        ):
            covered(above)
            continue
        report["uncovered"] += 1
        if require_cover:
            issue(pos, "uncovered_surface")
        bx, by, bz = (v // 16 for v in above)
        level = 0
        # The emitter directly beneath the feet contributes emission minus one.
        for x in range(bx - 1, bx + 2):
            for y in range(by - 1, by + 2):
                for z in range(bz - 1, bz + 2):
                    for source, emitted in buckets.get((x, y, z), ()):
                        possible = emitted - sum(abs(a - b) for a, b in zip(source, above))
                        if possible > level and lit_path(above, source, cells, states):
                            level = possible
        if level >= threshold:
            report["proven_lit"] += 1
            if len(report["light_checks"]) < 10000:
                report["light_checks"].append(list(above))
        else:
            report["unproven_light"] += 1
            issue(pos, "light_not_proven")
    report["status"] = "needs_attention" if report["issue_count"] else "passed"
    report["highlights_truncated"] = report["issue_count"] > len(report["issues"])
    yield "result", report
