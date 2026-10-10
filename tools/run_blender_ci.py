"""Run non-GUI Blender integration tests with the official bpy Python package."""

import runpy
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
bpy.context.preferences.use_preferences_save = False
# Importing bpy first adds Blender's bundled modules to Python's search path.
import addon_utils

# bpy wheels don't necessarily enable Blender's bundled extension installer.
addon_utils.enable("bl_pkg", default_set=False)
test = Path(sys.argv[1]).resolve()
assert test.parent == ROOT / "tests" and test.name.startswith("blender_")
runpy.run_path(str(test), run_name="__main__")
