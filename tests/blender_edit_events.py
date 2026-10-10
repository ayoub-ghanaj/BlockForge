"""Run in a NEW foreground Blender with --enable-event-simulate; exits itself."""

import json
import sys
import traceback
from pathlib import Path

import bpy
from bpy_extras import view3d_utils
from mathutils import Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import minecraft_builder
from minecraft_builder import live_edit as edit

OUT = ROOT / "build/live-edit"
OUT.mkdir(parents=True, exist_ok=True)
report = {"checks": [], "blender": bpy.app.version_string}
active_target = "MODEL"


class MB_PT_event_test(bpy.types.Panel):
    bl_label = "Sidebar event regression"
    bl_idname = "MB_PT_event_test"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Edit Test"

    def draw(self, context):
        p = edit.settings(context, active_target)
        self.layout.prop(p, "keep_manual_edits")
        op = self.layout.operator("minecraft_builder.edit_action", text="Delete selected block")
        op.target = active_target
        op.action = "DELETE"
        for mode, label in (("PICK", "Pick Block"), ("SELECT", "Select Area (2 Clicks)")):
            op = self.layout.operator("minecraft_builder.edit_view", text=label)
            op.target = active_target
            op.start_mode = mode


bpy.context.preferences.use_preferences_save = False
bpy.context.preferences.view.show_splash = False


def run():
    global active_target
    minecraft_builder.register()
    bpy.utils.register_class(MB_PT_event_test)
    window = bpy.context.window
    area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")
    space = area.spaces.active
    window.event_simulate(type="ESC", value="PRESS", x=150, y=150)
    window.event_simulate(type="ESC", value="RELEASE", x=150, y=150)
    yield
    for target in ("MODEL", "PERIMETER"):
        active_target = target
        p = edit.settings(bpy.context, target)
        p.target_version = "26.1.2"
        p.width = p.depth = p.height = 8
        p.preview_real_scale = True
        if target == "MODEL":
            p.hollow = False
            bpy.ops.object.select_all(action="DESELECT")
            cube = bpy.data.objects["Cube"]
            cube.select_set(True)
            bpy.context.view_layer.objects.active = cube
            bpy.ops.minecraft_builder.capture()
            bpy.ops.minecraft_builder.generate()
            top = 7
        else:
            p.project_kind = "FLOOR"
            p.protection = "NONE"
            p.search = "minecraft:red_wool"
            p.regex_search = False
            bpy.ops.minecraft_builder.only_blocks(target="PERIMETER", scope="FILTERED")
            bpy.ops.minecraft_perimeter.generate()
            top = 0
        if target == "PERIMETER":
            # Keep both colors allowed before generation and editing.
            p.search = r"minecraft:(red|blue)_wool$"
            p.regex_search = True
            bpy.ops.minecraft_builder.only_blocks(target=target, scope="FILTERED")
            bpy.ops.minecraft_perimeter.generate()
        p.edit_brush = "minecraft:blue_wool"
        root = edit.root_object(bpy.context, p, target)
        bpy.context.view_layer.update()
        center = root.matrix_world @ Vector(edit.display((4, top + 0.5, 4), target))
        space.region_3d.view_perspective = "ORTHO"
        space.region_3d.view_rotation = Quaternion((1, 0, 0, 0))
        space.region_3d.view_location = center
        space.region_3d.view_distance = 16
        space.show_region_ui = False
        area.tag_redraw()
        yield
        with bpy.context.temp_override(window=window, area=area, region=region):
            assert bpy.ops.minecraft_builder.edit_view("INVOKE_DEFAULT", target=target) == {
                "RUNNING_MODAL"
            }

        def point(pos):
            xy = view3d_utils.location_3d_to_region_2d(
                region,
                space.region_3d,
                root.matrix_world @ Vector(edit.display(tuple(v + 0.5 for v in pos), target)),
            )
            assert xy is not None
            return int(region.x + xy.x), int(region.y + xy.y)

        def event(kind, value, pos, **kwargs):
            x, y = point(pos)
            window.event_simulate(type=kind, value=value, x=x, y=y, **kwargs)

        def cells():
            return edit.session(bpy.context, p, target).cells

        source = (2, top, 2)
        destination = (4, top, 2)
        event("D", "PRESS", source)
        yield
        event("LEFTMOUSE", "PRESS", source)
        event("LEFTMOUSE", "RELEASE", source)
        yield
        assert source not in cells(), (target, "delete failed", p.status)
        event("Z", "PRESS", source, ctrl=True)
        event("Z", "RELEASE", source, ctrl=True)
        yield
        assert source in cells(), (target, "undo failed")
        event("Z", "PRESS", source, ctrl=True, shift=True)
        event("Z", "RELEASE", source, ctrl=True, shift=True)
        yield
        assert source not in cells(), (target, "redo failed")
        event("A", "PRESS", source)
        yield
        event("LEFTMOUSE", "PRESS", source)
        event("LEFTMOUSE", "RELEASE", source)
        yield
        assert cells().get(source) == "minecraft:blue_wool", (
            target,
            "add failed",
            p.status,
            list(cells())[-2:],
        )
        event("D", "PRESS", destination)
        yield
        event("LEFTMOUSE", "PRESS", destination)
        event("LEFTMOUSE", "RELEASE", destination)
        yield
        assert destination not in cells()
        event("G", "PRESS", source)
        yield
        event("LEFTMOUSE", "PRESS", source)
        yield
        event("MOUSEMOVE", "NOTHING", destination)
        yield
        event("LEFTMOUSE", "RELEASE", destination)
        yield
        assert source not in cells() and cells().get(destination) == "minecraft:blue_wool", (
            target,
            "drag failed",
            p.status,
            tuple(p.edit_position),
        )
        event("V", "PRESS", destination)
        yield
        event("LEFTMOUSE", "PRESS", destination)
        event("LEFTMOUSE", "RELEASE", destination)
        yield
        event("MOUSEMOVE", "NOTHING", (5, top, 3))
        yield
        assert tuple(p.edit_position) == destination, (
            target,
            "picked block changed while moving toward sidebar",
            tuple(p.edit_position),
        )
        event("B", "PRESS", destination)
        event("B", "RELEASE", destination)
        yield
        assert tuple(p.edit_selection_a) == destination
        corner = (5, top, 3)
        event("LEFTMOUSE", "PRESS", corner)
        event("LEFTMOUSE", "RELEASE", corner)
        yield
        event("C", "PRESS", corner)
        event("C", "RELEASE", corner)
        yield
        assert tuple(p.edit_selection_b) == corner
        assert any(o.get("mb_selection_box") for o in root.children)
        event("LEFTMOUSE", "PRESS", destination)
        event("LEFTMOUSE", "RELEASE", destination)
        yield
        space.show_region_ui = True
        area.tag_redraw()
        yield
        side = next(r for r in area.regions if r.type == "UI")
        side.active_panel_category = "Edit Test"
        area.tag_redraw()
        yield
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.screen.screenshot(filepath=str(OUT / (target.lower() + "-sidebar-events.png")))

        def side_click(offset):
            x = side.x + side.width // 2
            y = side.y + side.height - offset
            window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
            yield
            window.event_simulate(type="LEFTMOUSE", value="PRESS", x=x, y=y)
            yield
            window.event_simulate(type="LEFTMOUSE", value="RELEASE", x=x, y=y)
            yield

        before = p.keep_manual_edits
        yield from side_click(45)
        assert p.keep_manual_edits != before, (
            target,
            "sidebar checkbox blocked by viewport tool",
            side.x,
            side.y,
            side.width,
            side.height,
        )
        assert tuple(p.edit_position) == destination, (target, "sidebar changed picked coordinates")
        yield from side_click(70)
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.screen.screenshot(filepath=str(OUT / (target.lower() + "-sidebar-after.png")))
        assert destination not in cells(), (
            target,
            "sidebar Delete button blocked",
            p.status,
            tuple(p.edit_position),
            tuple(edit.cursor_position(p, target)),
        )
        # Modal editing must remain active after interacting with the sidebar.
        event("Z", "PRESS", source, ctrl=True)
        event("Z", "RELEASE", source, ctrl=True)
        yield
        assert cells().get(destination) == "minecraft:blue_wool", (
            target,
            "viewport tool stopped after sidebar interaction",
        )
        event("ESC", "PRESS", destination)
        yield
        with bpy.context.temp_override(window=window, area=area, region=region):
            assert edit.active_view(bpy.context, target) is None
        before = dict(cells())
        yield from side_click(120)
        with bpy.context.temp_override(window=window, area=area, region=region):
            active = edit.active_view(bpy.context, target)
        assert active is not None and p.edit_mode == "SELECT", (
            target,
            "sidebar did not start area selection",
            p.status,
        )
        yield from side_click(120)
        with bpy.context.temp_override(window=window, area=area, region=region):
            assert edit.active_view(bpy.context, target) == active
        corner_a = (1, top, 1)
        corner_b = (4, top, 4)
        event("LEFTMOUSE", "PRESS", corner_a)
        event("LEFTMOUSE", "RELEASE", corner_a)
        yield
        assert tuple(p.edit_selection_a) == corner_a and p.edit_mode == "SELECT"
        event("LEFTMOUSE", "PRESS", corner_b)
        event("LEFTMOUSE", "RELEASE", corner_b)
        yield
        assert tuple(p.edit_selection_b) == corner_b and p.edit_mode == "PICK"
        assert cells() == before, (target, "selection changed block contents")
        event("ESC", "PRESS", corner_b)
        yield
        yield from side_click(95)
        event("LEFTMOUSE", "PRESS", destination)
        event("LEFTMOUSE", "RELEASE", destination)
        yield
        assert tuple(p.edit_position) == destination
        with bpy.context.temp_override(window=window, area=area, region=region):
            assert edit.active_view(bpy.context, target) is not None
        event("ESC", "PRESS", destination)
        yield
        report["checks"].append(
            target
            + ": real viewport add/delete/drag, undo/redo, sticky picking, B/C corners, sidebar editing, stopped-tool Pick/Select buttons, two-click area selection without shortcuts, repeated starts reuse one modal handler"
        )
        if target == "PERIMETER":
            space.show_region_ui = True
            p.step = 5
            area.tag_redraw()
            yield
            side = next(r for r in area.regions if r.type == "UI")
            side.active_panel_category = "Perimeter"
            space.shading.color_type = "MATERIAL"
            area.tag_redraw()
            yield
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.screen.screenshot(filepath=str(OUT / "live-edit-ui.png"))
            report["visible_meshes"] = [
                {
                    "name": o.name,
                    "polygons": len(o.data.polygons),
                    "location": list(o.matrix_world.translation),
                    "bounds": [
                        [
                            min(v.co[i] for v in o.data.vertices),
                            max(v.co[i] for v in o.data.vertices),
                        ]
                        for i in range(3)
                    ],
                }
                for o in root.children
                if o.type == "MESH" and len(o.data.vertices)
            ]
            bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "viewport-edited.blend"))
    report["status"] = "passed"


job = run()


def advance():
    try:
        next(job)
        return 0.3
    except StopIteration:
        pass
    except Exception as error:
        traceback.print_exc()
        report.update(status="failed", error=str(error))
    (OUT / "blender-edit-events.json").write_text(json.dumps(report, indent=2))
    print("BLENDER_EDIT_EVENTS", json.dumps(report), flush=True)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(advance, first_interval=2)
