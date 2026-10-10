"""Versioned surface treatment materials, separate from the artwork allow-list."""

from functools import lru_cache

from ..core.palette import Block

DYES = {
    "white": (249, 255, 254),
    "orange": (249, 128, 29),
    "magenta": (199, 78, 189),
    "light_blue": (58, 179, 218),
    "yellow": (254, 216, 61),
    "lime": (128, 199, 31),
    "pink": (243, 139, 170),
    "gray": (71, 79, 82),
    "light_gray": (157, 157, 151),
    "cyan": (22, 156, 156),
    "purple": (137, 50, 184),
    "blue": (60, 68, 170),
    "brown": (131, 84, 50),
    "green": (94, 124, 22),
    "red": (176, 46, 38),
    "black": (29, 29, 33),
}
GLASS = (Block("minecraft:glass", (215, 235, 240)),) + tuple(
    Block("minecraft:" + name + "_stained_glass", rgb) for name, rgb in DYES.items()
)
GLASS_STATES = frozenset(b.state for b in GLASS)
LIGHT_LEVELS = {
    name: 15
    for name in (
        "glowstone",
        "sea_lantern",
        "jack_o_lantern",
        "shroomlight",
        "ochre_froglight",
        "verdant_froglight",
        "pearlescent_froglight",
    )
}
LIGHT_LEVELS["crying_obsidian"] = 10


@lru_cache(maxsize=2048)
def is_glass(state):
    return state.split("[")[0] in GLASS_STATES or state.split("[")[0] == "minecraft:tinted_glass"


def transmits_light(state):
    return state.split("[")[0] in GLASS_STATES


@lru_cache(maxsize=2048)
def emission(state):
    return LIGHT_LEVELS.get(state.split("[")[0].removeprefix("minecraft:"), 0)


def light_threshold(profile):
    return 1 if profile.data_version >= 2860 else 8


def lighting_blocks(profile):
    return [b for b in profile.blocks if emission(b.state) > 0]


def selected_lights(profile, state="AUTO"):
    candidates = lighting_blocks(profile)
    result = (
        [b for b in candidates if emission(b.state) == 15]
        if state == "AUTO"
        else [b for b in candidates if b.state == state]
    )
    if not result:
        raise ValueError(
            "Selected lighting block is unavailable in this version/palette; choose another light"
        )
    return result
