"""Minecraft Builder: offline Blender UI and three schematic export formats."""

bl_info = {
    "name": "Minecraft Builder",
    "author": "Minecraft Builder contributors",
    "version": (0, 5, 3),
    "blender": (4, 2, 0),
    "location": "3D View > Sidebar > Minecraft",
    "category": "Import-Export",
}

# Blender can retain submodules when installing over a disabled extension. Reload
# dependencies before defining/registering RNA classes so every module belongs
# to the installed version. In particular Perimeter copies Model's properties.
_MODULE_ORDER = (
    "core.palette",
    "core.geometry",
    "core.shapes",
    "core.appearance",
    "core.texture_pack",
    "core.nbt",
    "core.volume",
    "core.exporters",
    "core.editing",
    "core.bulk",
    "catalog",
    "blender_mesh",
    "ui",
    "perimeter.materials",
    "perimeter.covers",
    "perimeter.streaming",
    "perimeter.layout",
    "perimeter.protection",
    "perimeter.blender_bridge",
    "perimeter.ui",
    "live_edit",
    "protection_ui",
    "textured_preview",
)


def _load_modules():
    import importlib
    import sys

    importlib.invalidate_caches()
    for name in _MODULE_ORDER:
        full_name = __name__ + "." + name
        if full_name in sys.modules:
            importlib.reload(sys.modules[full_name])
        else:
            importlib.import_module(full_name)


def register():
    _load_modules()
    from . import live_edit, protection_ui, textured_preview, ui
    from .perimeter import ui as perimeter_ui

    registered = []
    try:
        for module in (ui, perimeter_ui, live_edit, protection_ui, textured_preview):
            module.register()
            registered.append(module)
    except Exception:
        for module in reversed(registered):
            module.unregister()
        raise


def unregister():
    from . import textured_preview

    textured_preview.unregister()
    from . import protection_ui

    protection_ui.unregister()
    from . import live_edit

    live_edit.unregister()
    from .perimeter import ui as perimeter_ui

    perimeter_ui.unregister()
    from . import ui

    ui.unregister()
