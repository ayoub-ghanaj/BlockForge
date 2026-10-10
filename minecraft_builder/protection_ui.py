"""Recheck and highlight current perimeter protection without changing blocks."""

import json

import bpy

from . import catalog
from .perimeter import protection
from .perimeter import ui as perimeter


def invalidate(options):
    if options.protection_audit:
        options.protection_audit.clear()
    for obj in list(bpy.data.objects):
        if obj.get("mb_protection_overlay") == options.preview_token:
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh and not mesh.users:
                bpy.data.meshes.remove(mesh)


def current(options):
    if not options.protection_audit or not options.protection_audit.as_string():
        return None
    if options.snapshot_signature != perimeter.settings_signature(options):
        return None
    report = json.loads(options.protection_audit.as_string())
    if report.get("require_dry_cover") != options.check_dry_cover:
        return None
    return report


def highlights(context, options, report):
    from .live_edit import display, root_object

    root = root_object(context, options, "PERIMETER")
    if not root:
        return
    issues = {tuple(row[:3]): row[3] for row in report["issues"]}
    verts = []
    faces = []
    for x, y, z in issues:
        start = len(verts)
        verts.extend(
            display(v, "PERIMETER")
            for v in (
                (x, y + 1.025, z),
                (x + 1, y + 1.025, z),
                (x + 1, y + 1.025, z + 1),
                (x, y + 1.025, z + 1),
            )
        )
        faces.append((start, start + 1, start + 2, start + 3))
    if not faces:
        return
    mesh = bpy.data.meshes.new("Perimeter protection issues")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("Protection issues — recheck after edits", mesh)
    root.users_collection[0].objects.link(obj)
    obj.parent = root
    obj["mb_protection_overlay"] = options.preview_token
    obj["mb_edit_preview"] = options.preview_token
    obj.hide_select = True
    obj.hide_render = True
    obj.show_in_front = True
    obj.display_type = "WIRE"
    obj.color = (1, 0.12, 0.02, 1)
    obj.hide_set(not options.show_protection_issues)


def visibility(options, context):
    if context is None:
        return
    for obj in context.scene.objects:
        if obj.get("mb_protection_overlay") == options.preview_token:
            obj.hide_set(not options.show_protection_issues)


class MB_OT_check_protection(bpy.types.Operator):
    bl_idname = "minecraft_perimeter.check_protection"
    bl_label = "Check Current Protection"
    bl_description = "Inspect current blocks, including manual edits; highlight unproven lighting, uncovered surfaces and unsupported covers"
    _job = None
    _timer = None
    _scene = None

    @classmethod
    def poll(cls, context):
        options = context.scene.minecraft_perimeter
        return bool(options.snapshot) and not options.busy

    def job(self, context):
        options = context.scene.minecraft_perimeter
        build = perimeter.snapshot(options)
        profile = catalog.profiles(options)[options.target_version]
        for stage, value in protection.check(build, profile, options.check_dry_cover):
            if stage != "result":
                yield stage, value
                continue
            invalidate(options)
            if not options.protection_audit:
                options.protection_audit = bpy.data.texts.new("Perimeter protection check")
            options.protection_audit.write(json.dumps(value, separators=(",", ":")))
            highlights(context, options, value)
            options.status = (
                f"Protection check: {value['issue_count']:,} issues; {value['covered']:,} covered, "
                f"{value['proven_lit']:,} proven lit"
            )
        yield "done", 1

    def finish(self, context):
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        if self._job:
            self._job.close()
            self._job = None
        if self._scene:
            self._scene.minecraft_perimeter.busy = False

    def execute(self, context):
        self._scene = context.scene
        self._scene.minecraft_perimeter.busy = True
        self._job = self.job(context)
        try:
            for stage, value in self._job:
                pass
        except Exception as e:
            self.report({"ERROR"}, str(e))
            self.finish(context)
            return {"CANCELLED"}
        self.finish(context)
        return {"FINISHED"}

    def invoke(self, context, event):
        if bpy.app.background:
            return self.execute(context)
        self._scene = context.scene
        self._scene.minecraft_perimeter.busy = True
        self._job = self.job(context)
        self._timer = context.window_manager.event_timer_add(0.02, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC" or context.scene != self._scene:
            self.finish(context)
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        try:
            stage, value = next(self._job)
            p = self._scene.minecraft_perimeter
            p.progress = value
            if stage == "done":
                self.finish(context)
                return {"FINISHED"}
            p.status = stage
            if context.area:
                context.area.tag_redraw()
        except StopIteration:
            self.finish(context)
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            self.finish(context)
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


def draw(box, options):
    box = box.box()
    box.label(text="Check the edited perimeter")
    box.prop(options, "check_dry_cover")
    box.operator("minecraft_perimeter.check_protection", icon="CHECKMARK")
    report = current(options)
    if report:
        box.label(
            text=f"{report['issue_count']:,} issues · {report['surfaces']:,} surfaces",
            icon="CHECKMARK" if not report["issue_count"] else "ERROR",
        )
        box.label(
            text=f"Light unproven: {report['unproven_light']:,}; uncovered: {report['uncovered']:,}"
        )
        box.prop(options, "show_protection_issues")
        if report["highlights_truncated"]:
            box.label(text="First 10,000 issues highlighted; report counts all.")
    else:
        box.label(text="Check again after changes.", icon="INFO")
    box.label(text="Conservative light / dry-cover check.")
    box.label(text="World biome and special spawns are not simulated.")


CLASSES = (MB_OT_check_protection,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
