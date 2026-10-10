"""A separate guided perimeter workflow. No model snapshot or settings are reused."""

import base64
import gzip
import hashlib
import io
import json
import uuid

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Vector

from .. import catalog
from .. import ui as common
from ..core.exporters import material_counts
from ..core.palette import srgb
from . import blender_bridge as bridge
from . import covers, layout, streaming
from .materials import GLASS, light_threshold, lighting_blocks

STEPS = (
    "Size",
    "Images and materials",
    "3D decorations",
    "Cover and lighting",
    "Preview",
    "Export",
)
FACE_ITEMS = [(name, name.title(), "") for name in layout.FACES]
_light_items = {}
_cover_items = {}


def cover_items(options, context):
    profile = catalog.profiles(options).get(options.target_version)
    blocks = covers.choices(profile, options.cover_kind) if profile else []
    key = tuple(b.state for b in blocks)
    if key not in _cover_items:
        _cover_items[key] = [
            (b.state, b.label, "", common.version_number(b.state)) for b in blocks
        ] or [("NONE", "Choose a version first", "", 0)]
    return _cover_items[key]


def cover_get(options):
    items = cover_items(options, None)
    state = options.get("cover_choice", "")
    return next((i[3] for i in items if i[0] == state), items[0][3])


def cover_set(options, value):
    options["cover_choice"] = next(i[0] for i in cover_items(options, None) if i[3] == value)


def light_items(options, context):
    profile = catalog.profiles(options).get(options.target_version)
    key = tuple(b.state for b in lighting_blocks(profile)) if profile else ()
    if key not in _light_items:
        _light_items[key] = [
            ("AUTO", "Match artwork color", "Choose the closest available level-15 light", 0)
        ] + [
            (
                state,
                state.split(":")[-1].split("[")[0].replace("_", " ").title(),
                "",
                common.version_number(state),
            )
            for state in key
        ]
    return _light_items[key]


def light_get(options):
    state = options.get("light_choice", "AUTO")
    return next((item[3] for item in light_items(options, None) if item[0] == state), 0)


def light_set(options, value):
    options["light_choice"] = next(
        item[0] for item in light_items(options, None) if item[3] == value
    )


def layout_changed(options, context):
    for name in layout.FACES:
        getattr(options, name).enabled = options.project_kind == "PERIMETER" or name == (
            "floor" if options.project_kind == "FLOOR" else "north"
        )
    options.face = "north" if options.project_kind == "WALL" else "floor"


def scale_changed(options, context):
    if context is None:
        return
    for obj in context.scene.objects:
        if obj.get("minecraft_perimeter_generated") != options.preview_token:
            continue
        scale = (
            1
            if options.preview_real_scale
            else min(1, 20 / max(obj["perimeter_preview_width"], obj["perimeter_preview_depth"]))
        ) / max(1e-9, context.scene.unit_settings.scale_length)
        obj.scale = (scale,) * 3
        scale = float(obj.scale.x)
        obj["perimeter_basis"] = [scale, 0, 0, 0, scale, 0, 0, 0, scale]


def issue_visibility(options, context):
    from ..protection_ui import visibility

    visibility(options, context)


class PBFace(bpy.types.PropertyGroup):
    enabled: BoolProperty(name="Include this surface", default=True)
    image: PointerProperty(name="Image", type=bpy.types.Image)
    fit: EnumProperty(
        name="Image sizing",
        items=[
            ("STRETCH", "Stretch", "Stretch to the surface dimensions"),
            ("FIT", "Fit + pad", "Keep proportions; pad unused space"),
            ("FILL", "Fill + crop", "Keep proportions; crop the overflow"),
            (
                "CROP",
                "Crop at 1:1",
                "Center original pixels; crop overflow and pad uncovered space",
            ),
            ("PAD", "Pad at 1:1", "Center original pixels without scaling; image must fit"),
        ],
        default="FIT",
    )
    flip_x: BoolProperty(name="Flip horizontally")
    flip_y: BoolProperty(name="Flip vertically")


class PBSettings(bpy.types.PropertyGroup):
    # Same property definitions, independent RNA storage on Scene.minecraft_perimeter.
    __annotations__ = dict(common.MBSettings.__annotations__)
    width: IntProperty(name="Interior width (X)", default=250, min=1, max=2048)
    depth: IntProperty(name="Interior length (Z)", default=250, min=1, max=2048)
    height: IntProperty(name="Wall / design height", default=64, min=1, max=256)
    step: IntProperty(default=1, min=1, max=6)
    project_kind: EnumProperty(
        name="Design",
        items=[
            ("PERIMETER", "Floor + walls", "A full rectangular perimeter"),
            ("FLOOR", "Floor mosaic", "An image floor; walls start disabled"),
            ("WALL", "Single wall", "One image wall; other surfaces start disabled"),
        ],
        default="PERIMETER",
        update=layout_changed,
    )
    face: EnumProperty(name="Surface", items=FACE_ITEMS, default="floor")
    floor: PointerProperty(type=PBFace)
    north: PointerProperty(type=PBFace)
    south: PointerProperty(type=PBFace)
    west: PointerProperty(type=PBFace)
    east: PointerProperty(type=PBFace)
    background: FloatVectorProperty(
        name="Plain / padding color",
        subtype="COLOR",
        size=3,
        default=(0.0144, 0.0144, 0.0144),
        min=0,
        max=1,
    )
    protection: EnumProperty(
        name="Surface treatment",
        items=[
            ("GLASS", "Ground cover", "Cover exposed tops with a selected material"),
            (
                "LIGHTS",
                "Lighting",
                "Inset selected lights or place them over partial shapes; does not prevent slime-chunk spawning",
            ),
            ("BOTH", "Cover + lighting", "Selected ground cover and automatic lights"),
            ("NONE", "No cover or lighting", "Export the artwork and decorations"),
        ],
        default="GLASS",
    )
    cover_kind: EnumProperty(name="Cover type", items=covers.KINDS, default="GLASS")
    cover_material: EnumProperty(
        name="Cover block", items=cover_items, get=cover_get, set=cover_set
    )
    glass_material: EnumProperty(
        name="Glass color",
        items=[
            (b.state, "Clear glass" if b.state == "minecraft:glass" else b.label, "") for b in GLASS
        ],
        default="minecraft:glass",
    )
    light_material: EnumProperty(
        name="Lighting block", items=light_items, get=light_get, set=light_set
    )
    guide_token: StringProperty()
    deco_width: IntProperty(name="Decoration width", default=48, min=1, max=512)
    deco_height: IntProperty(name="Decoration height", default=48, min=1, max=256)
    deco_depth: IntProperty(name="Decoration length", default=48, min=1, max=512)
    preview_real_scale: BoolProperty(
        name="Preview: 1 meter per block", default=True, update=scale_changed
    )
    build_name: StringProperty(name="Perimeter name", default="My perimeter")
    status: StringProperty(default="Start with the perimeter dimensions and Minecraft version")
    protection_audit: PointerProperty(type=bpy.types.Text)
    check_dry_cover: BoolProperty(
        name="Require dry ground protection",
        default=True,
        description="Also flag surfaces without a supported dry cover, even when lit; useful for slime-safe designs",
    )
    show_protection_issues: BoolProperty(
        name="Show problem surfaces", default=True, update=issue_visibility
    )


def settings_signature(options):
    doc = {
        k: getattr(options, k)
        for k in (
            "width",
            "depth",
            "height",
            "target_version",
            "protection",
            "hollow",
            "thickness",
            "shape_weight",
            "whitelist",
            "gravity",
            "slabs",
            "stairs",
        )
    }
    if options.glass_material != "minecraft:glass":
        doc["glass_material"] = options.glass_material
    if options.special_appearance:
        doc["special_appearance"] = True
    if options.face_matching:
        doc["face_matching"] = True
    if options.light_material != "AUTO":
        doc["light_material"] = options.light_material
    if options.cover_kind != "GLASS":
        doc.update(cover_kind=options.cover_kind, cover_material=options.cover_material)
    doc["background"] = list(options.background)
    doc["materials"] = [(r.state, r.policy, list(r.color)) for r in options.blocks]
    doc["sources"] = [
        (s.object.name, [list(row) for row in s.object.matrix_world])
        for s in options.sources
        if s.object
    ]
    doc["unit_scale"] = bpy.context.scene.unit_settings.scale_length
    doc["faces"] = {}
    for name in layout.FACES:
        face = getattr(options, name)
        image = face.image
        doc["faces"][name] = [
            face.enabled,
            face.fit,
            face.flip_x,
            face.flip_y,
            [
                image.name,
                "packed" if image.packed_file else bpy.path.abspath(image.filepath),
                list(image.size),
            ]
            if image
            else None,
        ]
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


def base_snapshot(options):
    if not options.snapshot:
        raise ValueError("Generate the perimeter preview first")
    if options.snapshot_signature != settings_signature(options):
        raise ValueError("Perimeter settings changed; regenerate its preview")
    for obj in bpy.context.scene.objects:
        if obj.get("minecraft_perimeter_generated") == options.preview_token:
            actual = [v for row in obj.matrix_basis.to_3x3() for v in row]
            if any(abs(a - b) > 1e-5 for a, b in zip(actual, obj["perimeter_basis"])):
                raise ValueError(
                    "Perimeter preview was rotated/scaled. Use the scale checkbox or regenerate."
                )
    with gzip.GzipFile(
        fileobj=io.BytesIO(base64.b64decode(options.snapshot.as_string(), validate=True))
    ) as stream:
        content = stream.read(256 * 1024 * 1024 + 1)
    if len(content) > 256 * 1024 * 1024:
        raise ValueError("Perimeter snapshot is too large")
    build = json.loads(content)
    streaming.validate(build)
    profile = catalog.profiles(options).get(options.target_version)
    if (
        not profile
        or build["version"] != profile.id
        or build["data_version"] != profile.data_version
    ):
        raise ValueError("Perimeter preview version changed; regenerate it")
    allowed = {s.state.split("[")[0] for s in profile.blocks} | {b.state for b in GLASS}
    for kind, _, _ in covers.KINDS:
        allowed.update(b.state.split("[")[0] for b in covers.choices(profile, kind))
    if any(s.split("[")[0] not in allowed for s in build["palette"]):
        raise ValueError("Perimeter contains materials outside its selected version")
    return build


def snapshot(options):
    from ..live_edit import edited_snapshot

    result = edited_snapshot(bpy.context, options, "PERIMETER", base_snapshot(options))
    from ..protection_ui import current

    report = current(options)
    if report:
        result["perimeter"]["audit"] = report
    return result


class PB_OT_step(bpy.types.Operator):
    bl_idname = "minecraft_perimeter.step"
    bl_label = "Perimeter Step"
    step: IntProperty(min=1, max=6)

    def execute(self, context):
        options = context.scene.minecraft_perimeter
        if self.step > 1 and options.target_version == "NONE":
            self.report({"ERROR"}, "Choose the destination Minecraft version first")
            return {"CANCELLED"}
        options.step = self.step
        return {"FINISHED"}


class PB_OT_image(bpy.types.Operator, ImportHelper):
    bl_idname = "minecraft_perimeter.image"
    bl_label = "Choose Surface Image"
    filter_glob: StringProperty(
        default="*.png;*.jpg;*.jpeg;*.webp;*.tif;*.tiff;*.bmp;*.tga;*.exr", options={"HIDDEN"}
    )
    face: EnumProperty(items=FACE_ITEMS)

    def execute(self, context):
        try:
            getattr(context.scene.minecraft_perimeter, self.face).image = bpy.data.images.load(
                self.filepath, check_existing=True
            )
        except (RuntimeError, OSError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class PB_OT_image_size(bpy.types.Operator):
    bl_idname = "minecraft_perimeter.image_size"
    bl_label = "Use Image Size"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        options = context.scene.minecraft_perimeter
        image = getattr(options, options.face).image
        if not image:
            self.report({"ERROR"}, "Choose an image first")
            return {"CANCELLED"}
        width, height = image.size
        if not (1 <= width <= 2048 and 1 <= height <= (2048 if options.face == "floor" else 256)):
            self.report(
                {"ERROR"}, "Image exceeds supported dimensions; choose a smaller size and Fit/Fill"
            )
            return {"CANCELLED"}
        if options.face == "floor":
            options.width = width
            options.depth = height
        elif options.face in ("north", "south"):
            options.width = width
            options.height = height
        else:
            options.depth = width
            options.height = height
        getattr(options, options.face).fit = "PAD"
        return {"FINISHED"}


class PB_OT_guide(bpy.types.Operator):
    bl_idname = "minecraft_perimeter.guide"
    bl_label = "Create / Update Perimeter Guide"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        bridge.create_guide(context, context.scene.minecraft_perimeter)
        return {"FINISHED"}


class PB_OT_decorations(bpy.types.Operator):
    bl_idname = "minecraft_perimeter.decorations"
    bl_label = "Decoration Sources"
    bl_options = {"REGISTER", "UNDO"}
    action: EnumProperty(
        items=[
            ("ADD", "Add selected meshes", "Use their scene placement; one meter is one block"),
            ("CLEAR", "Clear list", "Keep all Blender objects"),
        ]
    )

    def execute(self, context):
        options = context.scene.minecraft_perimeter
        if self.action == "CLEAR":
            options.sources.clear()
            return {"FINISHED"}
        selected = set()
        for obj in context.selected_objects:
            for child in [obj, *obj.children_recursive]:
                if (
                    child.type == "MESH"
                    and not child.get("minecraft_perimeter_generated")
                    and not child.get("minecraft_builder_preview")
                    and not child.get("mb_edit_preview")
                ):
                    selected.add(child)
        if not selected:
            self.report({"ERROR"}, "Select decoration meshes in the viewport")
            return {"CANCELLED"}
        existing = {s.object for s in options.sources}
        for obj in sorted(selected - existing, key=lambda o: o.name):
            options.sources.add().object = obj
        return {"FINISHED"}


class PB_OT_fit_decorations(bpy.types.Operator):
    bl_idname = "minecraft_perimeter.fit_decorations"
    bl_label = "Fit Decorations to Center"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = (
        "Move and scale listed source objects into the guide; Undo restores their transforms"
    )

    def execute(self, context):
        options = context.scene.minecraft_perimeter
        objects = [s.object for s in options.sources if s.object]
        if not objects:
            self.report({"ERROR"}, "Add decoration meshes first")
            return {"CANCELLED"}
        points = [o.matrix_world @ Vector(corner) for o in objects for corner in o.bound_box]
        low = Vector([min(v[i] for v in points) for i in range(3)])
        high = Vector([max(v[i] for v in points) for i in range(3)])
        unit = 1 / context.scene.unit_settings.scale_length
        limits = (
            min(options.width, options.deco_width) * unit,
            min(options.depth, options.deco_depth) * unit,
            min(options.height, options.deco_height) * unit,
        )
        factor = min(limits[i] / (high[i] - low[i]) for i in range(3) if high[i] - low[i] > 1e-8)
        origin = Vector(((low.x + high.x) / 2, (low.y + high.y) / 2, low.z))
        target = Vector((options.width * unit / 2, -options.depth * unit / 2, 0))
        matrices = {obj: obj.matrix_world.copy() for obj in objects}

        def parent_depth(obj):
            count = 0
            while obj.parent:
                count += 1
                obj = obj.parent
            return count

        for obj in sorted(objects, key=parent_depth):
            matrix = matrices[obj]
            matrix.translation = (matrix.translation - origin) * factor + target
            for row in range(3):
                for column in range(3):
                    matrix[row][column] *= factor
            obj.matrix_world = matrix
            context.view_layer.update()
        context.view_layer.update()
        bridge.create_guide(context, options)
        return {"FINISHED"}


class PB_OT_generate(bpy.types.Operator):
    bl_idname = "minecraft_perimeter.generate"
    bl_label = "Generate Perimeter Preview"
    bl_options = {"REGISTER", "UNDO"}
    _timer = None
    _job = None
    _scene = None

    @classmethod
    def poll(cls, context):
        options = context.scene.minecraft_perimeter
        return not options.busy and options.target_version != "NONE"

    def job(self, context):
        options = context.scene.minecraft_perimeter
        profile, blocks = common.chosen_blocks(options)
        faces = {}
        for name in layout.FACES:
            face = getattr(options, name)
            if face.enabled:
                faces[name] = {
                    "pixels": bridge.image_pixels(face.image) if face.image else None,
                    "mode": face.fit,
                    "flip_x": face.flip_x,
                    "flip_y": face.flip_y,
                }
        yield "Reading image surfaces", 0.02
        for stage, value in bridge.decorate(context, options, blocks):
            if stage == "result":
                decorations = value
            else:
                yield stage, 0.03 + value * 0.25
        background = tuple(round(255 * srgb(v)) for v in options.background)
        for stage, value in layout.compose(
            options.width,
            options.depth,
            options.height,
            faces,
            blocks,
            profile,
            background,
            options.protection,
            decorations,
            options.glass_material,
            options.light_material,
            options.cover_kind,
            options.cover_material,
            options.face_matching,
        ):
            if stage == "result":
                build = value
            else:
                yield stage, 0.28 + value * 0.45
        streaming.validate(build)
        token = str(uuid.uuid4())
        committed = False
        try:
            for stage, value in bridge.make_preview(
                context, build, token, options.preview_real_scale
            ):
                if stage != "result":
                    yield stage, 0.75 + (value - 0.7) * 0.5
            data = bpy.data.texts.new("Perimeter Designer snapshot")
            data.write(
                base64.b64encode(
                    gzip.compress(json.dumps(build, separators=(",", ":")).encode(), mtime=0)
                ).decode()
            )
            committed = True
        finally:
            if not committed:
                bridge.remove_generated(token)
        old_token = options.preview_token
        old_data = options.snapshot
        options.preview_token = token
        options.snapshot = data
        options.snapshot_signature = settings_signature(options)
        bridge.remove_generated(old_token)
        if old_data and not old_data.users:
            bpy.data.texts.remove(old_data)
        options.status = f"{len(build['cells']):,} blocks | " + " × ".join(map(str, build["size"]))
        from ..live_edit import generation_finished

        generation_finished(context, options, "PERIMETER")
        if build["warnings"]:
            self.report({"WARNING"}, build["warnings"][0])
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
        context.window_manager.progress_end()

    def execute(self, context):
        self._scene = context.scene
        options = context.scene.minecraft_perimeter
        options.busy = True
        self._job = self.job(context)
        try:
            for stage, value in self._job:
                options.progress = value
                if stage != "done":
                    options.status = stage
        except Exception as e:
            options.status = str(e)
            self.report({"ERROR"}, str(e))
            self.finish(context)
            return {"CANCELLED"}
        self.finish(context)
        return {"FINISHED"}

    def invoke(self, context, event):
        if bpy.app.background:
            return self.execute(context)
        self._scene = context.scene
        options = context.scene.minecraft_perimeter
        options.busy = True
        self._job = self.job(context)
        self._timer = context.window_manager.event_timer_add(0.02, window=context.window)
        context.window_manager.progress_begin(0, 100)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC" or context.scene != self._scene:
            self._scene.minecraft_perimeter.status = (
                "Cancelled; previous perimeter preview retained"
            )
            self.finish(context)
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        options = self._scene.minecraft_perimeter
        try:
            stage, value = next(self._job)
            options.progress = value
            if stage != "done":
                options.status = stage
            context.window_manager.progress_update(value * 100)
            if context.area:
                context.area.tag_redraw()
            if stage == "done":
                self.finish(context)
                return {"FINISHED"}
        except StopIteration:
            self.finish(context)
            return {"FINISHED"}
        except Exception as e:
            options.status = str(e)
            self.report({"ERROR"}, str(e))
            self.finish(context)
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


class PB_OT_export(bpy.types.Operator, ExportHelper):
    bl_idname = "minecraft_perimeter.export"
    bl_label = "Export Perimeter"
    filename_ext = ".schem"
    filter_glob: StringProperty(default="*.schem", options={"HIDDEN"})
    format: EnumProperty(
        items=[("schem", "WorldEdit", ""), ("litematic", "Litematica", ""), ("bp", "Axiom", "")],
        options={"HIDDEN"},
    )

    def invoke(self, context, event):
        options = context.scene.minecraft_perimeter
        self.filename_ext = "." + self.format
        self.filter_glob = "*." + self.format
        self.filepath = (
            bpy.path.clean_name(options.build_name + "-mc" + options.target_version)
            + self.filename_ext
        )
        return ExportHelper.invoke(self, context, event)

    def draw(self, context):
        self.layout.label(
            text="Perimeter · Minecraft Java " + context.scene.minecraft_perimeter.target_version
        )

    def execute(self, context):
        options = context.scene.minecraft_perimeter
        try:
            streaming.write(
                bpy.path.ensure_ext(self.filepath, "." + self.format),
                snapshot(options),
                self.format,
                options.build_name,
                options.author,
            )
        except (ValueError, OSError, KeyError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, "Exported perimeter for Java " + options.target_version)
        return {"FINISHED"}


class PB_OT_materials(bpy.types.Operator, ExportHelper):
    bl_idname = "minecraft_perimeter.materials"
    bl_label = "Perimeter Material List"
    filename_ext = ".csv"
    filter_glob: StringProperty(default="*.csv", options={"HIDDEN"})

    def execute(self, context):
        import csv

        try:
            counts = material_counts(snapshot(context.scene.minecraft_perimeter))
            with open(self.filepath, "w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["Block", "Count", "Full stacks", "Remainder"])
                for state, count in sorted(counts.items()):
                    writer.writerow([state, count, count // 64, count % 64])
        except (ValueError, OSError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class PB_UL_blocks(bpy.types.UIList):
    draw_item = common.MB_UL_blocks.draw_item
    filter_items = common.MB_UL_blocks.filter_items

    def draw_filter(self, context, layout):
        layout.prop(context.scene.minecraft_perimeter, "search", text="", icon="VIEWZOOM")


def palette_controls(box, options):
    box.operator("minecraft_builder.load_preset", icon="FILE_REFRESH").target = "PERIMETER"
    row = box.row(align=True)
    for preset, label in [("SURVIVAL", "Survival obtainable"), ("ALL", "All materials")]:
        op = row.operator("minecraft_builder.material_preset", text=label)
        op.target = "PERIMETER"
        op.preset = preset
    box.prop(options, "category")
    row = box.row(align=True)
    row.prop(options, "search", text="", icon="VIEWZOOM")
    row.prop(options, "regex_search")
    try:
        count = sum(common.matches_filter(options, r) for r in options.blocks)
    except ValueError as e:
        count = 0
        row = box.row()
        row.alert = True
        row.label(text=str(e), icon="ERROR")
    box.template_list(
        "PB_UL_blocks", "perimeter", options, "blocks", options, "active_block", rows=5
    )
    box.label(
        text=f"{count} results · {sum(r.selected for r in options.blocks)} checked · {len(common.eligible_rows(options))} eligible"
    )
    row = box.row(align=True)
    for mode, label in [("ALL", "Select all results"), ("NONE", "Clear")]:
        op = row.operator("minecraft_builder.select_blocks", text=label)
        op.target = "PERIMETER"
        op.mode = mode
    for scope, label in [("CHECKED", "Use only checked"), ("FILTERED", "Use only search results")]:
        op = box.operator("minecraft_builder.only_blocks", text=label)
        op.target = "PERIMETER"
        op.scope = scope
    box.prop(options, "rule_scope")
    row = box.row(align=True)
    for policy, label in [("ALLOW", "Include"), ("DENY", "Exclude"), ("AUTO", "Reset")]:
        op = row.operator("minecraft_builder.rules", text=label)
        op.target = "PERIMETER"
        op.policy = policy
    box.prop(options, "whitelist")
    box.prop(options, "gravity")
    box.prop(options, "special_appearance")
    box.prop(options, "face_matching")
    if options.special_appearance:
        box.label(text="Tint: Plains; transparency varies in-game.", icon="INFO")
    row = box.row(align=True)
    row.operator("minecraft_builder.import_palette", text="Import palette").target = "PERIMETER"
    row.operator("minecraft_builder.export_palette", text="Export palette").target = "PERIMETER"


class PB_PT_main(bpy.types.Panel):
    bl_label = "Perimeter Designer"
    bl_idname = "PB_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Perimeter"

    def draw(self, context):
        options = context.scene.minecraft_perimeter
        root = self.layout
        root.label(text=f"Step {options.step} / 6 · {STEPS[options.step - 1]}", icon="MOD_BUILD")
        box = root.column()
        box.enabled = not options.busy
        if options.step == 1:
            box.prop(options, "project_kind")
            box.prop(options, "target_version")
            box.prop(options, "width")
            box.prop(options, "depth")
            box.prop(options, "height")
            box.label(text="Dimensions are in Minecraft blocks.")
            box.operator("minecraft_perimeter.guide", icon="MESH_CUBE")
        elif options.step == 2:
            box.prop(options, "face")
            face = getattr(options, options.face)
            surface = box.box()
            surface.prop(face, "enabled")
            surface.prop(face, "image")
            surface.operator("minecraft_perimeter.image", icon="FILE_IMAGE").face = options.face
            if face.image:
                surface.label(text=f"{face.image.size[0]} × {face.image.size[1]} pixels")
                surface.operator("minecraft_perimeter.image_size")
            surface.prop(face, "fit")
            row = surface.row(align=True)
            row.prop(face, "flip_x")
            row.prop(face, "flip_y")
            surface.label(text="Wall images face the inside of the perimeter.")
            box.prop(options, "background")
            palette_controls(box.box(), options)
        elif options.step == 3:
            box.label(text="Optional · place meshes inside the guide.")
            box.operator("minecraft_perimeter.guide")
            row = box.row(align=True)
            row.operator(
                "minecraft_perimeter.decorations", text="Add selected meshes"
            ).action = "ADD"
            row.operator("minecraft_perimeter.decorations", text="Clear list").action = "CLEAR"
            for source in options.sources:
                if source.object:
                    box.label(text=source.object.name, icon="OUTLINER_OB_MESH")
            box.prop(options, "deco_width")
            box.prop(options, "deco_depth")
            box.prop(options, "deco_height")
            box.operator("minecraft_perimeter.fit_decorations", icon="FULLSCREEN_ENTER")
            box.label(text="Fit moves/scales listed meshes; Undo is available.")
            box.prop(options, "hollow")
            if options.hollow:
                box.prop(options, "thickness")
            row = box.row(align=True)
            row.prop(options, "slabs")
            row.prop(options, "stairs")
            box.prop(options, "shape_weight")
        elif options.step == 4:
            box.prop(options, "protection")
            box.label(text="Applied to floor, wall tops and decorations.")
            if options.protection in ("LIGHTS", "BOTH"):
                box.prop(options, "light_material")
                profile = catalog.profiles(options).get(options.target_version)
                if profile:
                    box.label(
                        text=f"Target block light: {light_threshold(profile)} or higher for this version."
                    )
                box.label(text="Partial shapes may gain a light above.")
                if options.protection == "LIGHTS":
                    box.label(text="Slime chunks still need ground cover.", icon="INFO")
            if options.protection in ("GLASS", "BOTH"):
                box.prop(options, "cover_kind")
                box.prop(
                    options, "glass_material" if options.cover_kind == "GLASS" else "cover_material"
                )
                box.label(text="Covers exposed ground surfaces; partial tops may need none.")
            box.label(text="Protection materials are added to the material list.")
        elif options.step == 5:
            box.prop(options, "preview_real_scale")
            box.operator("minecraft_perimeter.generate", icon="MOD_BUILD")
            box.label(text="Preview appears beside the perimeter guide.")
            box.label(text="Covers are shown above the artwork.")
            box.label(text="Regenerate after editing meshes or image pixels.")
            from ..textured_preview import draw as draw_textures

            draw_textures(box, options, "PERIMETER")
            from ..live_edit import draw as draw_editor

            draw_editor(box.box(), options, "PERIMETER")
        else:
            box.prop(options, "build_name")
            box.prop(options, "author")
            box.label(text="Minecraft Java " + options.target_version, icon="INFO")
            if not options.snapshot:
                box.label(text="Go back and generate a preview first.", icon="ERROR")
            exports = box.column()
            exports.enabled = bool(options.snapshot)
            for fmt, label in [
                ("schem", "WorldEdit .schem"),
                ("litematic", "Litematica .litematic"),
                ("bp", "Axiom .bp"),
            ]:
                exports.operator(
                    "minecraft_perimeter.export", text=label, icon="EXPORT"
                ).format = fmt
            exports.operator("minecraft_perimeter.materials", icon="TEXT")
        root.separator()
        root.label(text=options.status)
        if options.busy:
            root.progress(factor=options.progress, type="BAR", text="Esc to cancel")
        nav = root.row(align=True)
        nav.enabled = not options.busy
        if options.step > 1:
            nav.operator("minecraft_perimeter.step", text="Back", icon="TRIA_LEFT").step = (
                options.step - 1
            )
        if options.step < 6:
            nav.operator(
                "minecraft_perimeter.step", text="Next: " + STEPS[options.step], icon="TRIA_RIGHT"
            ).step = options.step + 1


CLASSES = (
    PBFace,
    PBSettings,
    PB_OT_step,
    PB_OT_image,
    PB_OT_image_size,
    PB_OT_guide,
    PB_OT_decorations,
    PB_OT_fit_decorations,
    PB_OT_generate,
    PB_OT_export,
    PB_OT_materials,
    PB_UL_blocks,
    PB_PT_main,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.minecraft_perimeter = PointerProperty(type=PBSettings)


def unregister():
    if hasattr(bpy.types.Scene, "minecraft_perimeter"):
        del bpy.types.Scene.minecraft_perimeter
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
