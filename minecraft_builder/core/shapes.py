"""Minecraft cube, slab and stair geometry on a half-block grid.

Octant index = x + 2*z + 4*y. Minecraft axes: X east, Y up, Z south.
Stair corners follow the game's neighboring stair rules, across materials.
"""

from .palette import canonical_state

FACING = {"north": (0, 0, -1), "east": (1, 0, 0), "south": (0, 0, 1), "west": (-1, 0, 0)}
ORDER = ("north", "east", "south", "west")


def split_state(state):
    if "[" not in state:
        return state, {}
    name, properties = state[:-1].split("[", 1)
    return name, dict(pair.split("=", 1) for pair in properties.split(","))


def with_properties(state, **properties):
    name, existing = split_state(state)
    existing.update(properties)
    return canonical_state(name + "[" + ",".join(f"{k}={v}" for k, v in existing.items()) + "]")


def stair_mask(facing, half="bottom", corner="straight"):
    def in_side(x, z, direction):
        return {"north": z == 0, "south": z == 1, "east": x == 1, "west": x == 0}[direction]

    index = ORDER.index(facing)
    side = ORDER[(index + (-1 if corner.endswith("left") else 1)) % 4]
    mask = 0
    for y in range(2):
        for z in range(2):
            for x in range(2):
                base = y == (0 if half == "bottom" else 1)
                tread = in_side(x, z, facing)
                if corner.startswith("inner"):
                    tread |= in_side(x, z, side)
                elif corner.startswith("outer"):
                    tread &= in_side(x, z, side)
                if base or tread:
                    mask |= 1 << (x + 2 * z + 4 * y)
    return mask


def state_mask(state, kind="cube"):
    _, props = split_state(state)
    if kind == "slab":
        return {"bottom": 15, "top": 240, "double": 255}[props.get("type", "bottom")]
    if kind == "stairs":
        return stair_mask(
            props.get("facing", "north"),
            props.get("half", "bottom"),
            props.get("shape", "straight"),
        )
    return 255


def orientations(block):
    if block.shape == "cube":
        return (
            [(state, 255) for state, _ in block.variants]
            if block.variants
            else [(block.state, 255)]
        )
    if block.shape == "slab":
        return [
            (with_properties(block.state, type=half), mask)
            for half, mask in (("bottom", 15), ("top", 240))
        ]
    return [
        (
            with_properties(block.state, facing=facing, half=half, shape="straight"),
            stair_mask(facing, half),
        )
        for half in ("bottom", "top")
        for facing in ORDER
    ]


def connected_shape(position, state, lookup):
    _, props = split_state(state)
    facing, half = props["facing"], props["half"]
    index = ORDER.index(facing)

    def at(direction):
        delta = FACING[direction]
        return lookup(tuple(position[i] + delta[i] for i in range(3)))

    def eligible(other):
        return other is not None and other.get("half") == half and "facing" in other

    def can_take(direction):
        other = at(direction)
        return not (eligible(other) and other["facing"] == facing)

    front = at(facing)
    if eligible(front):
        turn = ORDER.index(front["facing"])
        if (index - turn) % 2 and can_take(ORDER[(turn + 2) % 4]):
            return "outer_left" if turn == (index - 1) % 4 else "outer_right"
    back = at(ORDER[(index + 2) % 4])
    if eligible(back):
        turn = ORDER.index(back["facing"])
        if (index - turn) % 2 and can_take(back["facing"]):
            return "inner_left" if turn == (index - 1) % 4 else "inner_right"
    return "straight"


def resolve_stairs(cells, shapes):
    """Cells map positions to state strings; shapes map block IDs to shape names."""

    def lookup(pos):
        other = cells.get(pos)
        if other is None:
            return None
        name, props = split_state(other)
        return props if shapes.get(name) == "stairs" else None

    result = dict(cells)
    for pos, state in cells.items():
        if shapes.get(split_state(state)[0]) == "stairs":
            result[pos] = with_properties(state, shape=connected_shape(pos, state, lookup))
    return result
