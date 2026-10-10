import base64
import gzip
import hashlib
import io
import json
import re
import uuid
import zlib
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    IntVectorProperty,
    PointerProperty,
    StringProperty,
)
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import catalog
from .core import exporters
from .core.palette import (
    allowed_blocks,
    linear,
    load_file,
    parse_document,
    profile_document,
    srgb,
    survival_obtainable,
)

_version_items = {}
_category_items = {}


def version_number(identifier):
    # Explicit enum numbers prevent new presets from shifting saved selections.
    return (zlib.crc32(identifier.encode("utf-8")) & 0x7FFFFFFF) or 1


def version_items(self, context):
    try:
        key = tuple((p.id, p.data_version) for p in catalog.profiles(self).values())
    except (OSError, ValueError):
        key = ()
    # Blender retains pointers to enum strings: keep lists for BOTH workflows.
    if key not in _version_items:
        _version_items[key] = [
            (
                "NONE",
                "Choose Minecraft version…",
                "Select the version you will open this build in",
                0,
            )
        ] + [
            (
                identifier,
                identifier,
                f"Minecraft data version {data_version}",
                version_number(identifier),
            )
            for identifier, data_version in key
        ]
    return _version_items[key]


def version_get(self):
    # 0.1.0 scenes already store loaded_version as a string. Migrate that value,
    # never their old ordinal enum index. New scenes deliberately select nothing.
    identifier = self.get("selected_profile_id", self.loaded_version)
    return version_number(identifier) if identifier else 0


def version_set(self, value):
    self["selected_profile_id"] = next(
        (p.id for p in catalog.profiles(self).values() if version_number(p.id) == value), ""
    )


def load_preset(settings):
    profile = catalog.profiles(settings).get(settings.target_version)
    if profile is None:
        raise ValueError("Choose a valid Minecraft version preset")
    if not settings.snapshot and not settings.is_property_set("face_matching"):
        settings.face_matching = True
    previous = {row.state.split("[")[0]: row.policy for row in settings.blocks}
    settings.blocks.clear()
    for block in profile.blocks:
        row = settings.blocks.add()
        row.name = block.label
        row.state = block.state
        row.color = tuple(linear(v / 255) for v in block.rgb)
        row.category = block.category
        row.shape = block.shape
        row.gravity = block.gravity
        row.special_appearance = bool(block.appearance)
        row.policy = previous.get(block.state.split("[")[0], "AUTO")
    settings.loaded_version = profile.id
    settings.active_block = 0


def preset_changed(self, context):
    try:
        load_preset(self)
    except (OSError, ValueError, RuntimeError) as e:
        self.status = str(e)


def preview_scale_changed(self, context):
    if context is None:
        return
    meters = 1 / max(1e-9, context.scene.unit_settings.scale_length)
    for obj in context.scene.objects:
        if obj.get("minecraft_builder_preview") != self.preview_token:
            continue
        if "minecraft_builder_fit_scale" not in obj:
            obj["minecraft_builder_fit_scale"] = tuple(obj.scale)
        scale = (
            (meters, meters, meters)
            if self.preview_real_scale
            else tuple(obj["minecraft_builder_fit_scale"])
        )
        obj.scale = scale
        scale = tuple(obj.scale)
        # Record the expected unrotated basis, so a prior manual rotation is still detected.
        obj["minecraft_builder_basis"] = [scale[0], 0, 0, 0, scale[1], 0, 0, 0, scale[2]]


def category_items(self, context):
    key = tuple(sorted({r.category for r in self.blocks}))
    if key not in _category_items:
        _category_items[key] = [("ALL", "All categories", "")] + [(v, v, "") for v in key]
    return _category_items[key]


@lru_cache(maxsize=32)
def search_pattern(query):
    try:
        return re.compile(query, re.IGNORECASE)
    except re.error as error:
        raise ValueError("Invalid regex: " + str(error)) from error


def matches_filter(options, item):
    if options.category != "ALL" and item.category != options.category:
        return False
    text = item.name + " " + item.state
    return (
        bool(search_pattern(options.search).search(text))
        if options.regex_search
        else options.search.lower() in text.lower()
    )


def eligible_rows(options):
    rows = list(options.blocks)
    if options.color_mode == "SINGLE":
        rows = rows[options.active_block : options.active_block + 1]
    return [
        r
        for r in rows
        if r.policy != "DENY"
        and (not options.whitelist or r.policy == "ALLOW")
        and (options.slabs or r.shape != "slab")
        and (options.stairs or r.shape != "stairs")
        and (options.gravity or not r.gravity)
        and (options.special_appearance or not r.special_appearance)
    ]


def palette_settings(context, target="MODEL"):
    return (
        context.scene.minecraft_perimeter
        if target == "PERIMETER"
        else context.scene.minecraft_builder
    )


def edit_position_changed(options, context):
    from .live_edit import update_cursor

    update_cursor(options, context)


def edit_selection_changed(options, context):
    if context is None:
        return
    from .live_edit import show_selection

    target = (
        "MODEL"
        if options.as_pointer() == context.scene.minecraft_builder.as_pointer()
        else "PERIMETER"
    )
    show_selection(context, options, target)


class MBSource(bpy.types.PropertyGroup):
    object: PointerProperty(type=bpy.types.Object)


class MBBlock(bpy.types.PropertyGroup):
    selected: BoolProperty(
        name="Select block", description="Check several rows, then apply an Include or Exclude rule"
    )
    state: StringProperty()
    color: FloatVectorProperty(name="Representative color", subtype="COLOR", size=3, min=0, max=1)
    category: StringProperty()
    shape: StringProperty()
    gravity: BoolProperty()
    special_appearance: BoolProperty(
        name="Variable appearance",
        description="Transparency or biome tint affects the visible color",
    )
    policy: EnumProperty(
        name="Block rule",
        items=[
            ("AUTO", "Auto", "Use unless whitelist mode is enabled"),
            ("ALLOW", "Include", "Include in whitelist"),
            ("DENY", "Exclude", "Never use this block"),
        ],
        default="AUTO",
    )


class MBSettings(bpy.types.PropertyGroup):
    sources: CollectionProperty(type=MBSource)
    model_up: EnumProperty(
        name="Model up direction",
        description="Source axis that should point upward in Minecraft; regenerate after changing",
        items=[
            ("Z", "+Z (Blender up)", "Normal Blender orientation"),
            ("NEG_Z", "−Z (flip upside down)", "Turn an upside-down source upright"),
            ("Y", "+Y", "Y-up imported model"),
            ("NEG_Y", "−Y", "Negative Y points up"),
            ("X", "+X", "X points up"),
            ("NEG_X", "−X", "Negative X points up"),
        ],
        default="Z",
    )
    target_version: EnumProperty(
        name="Minecraft Java",
        items=version_items,
        get=version_get,
        set=version_set,
        update=preset_changed,
    )
    loaded_version: StringProperty()
    custom_palettes: PointerProperty(type=bpy.types.Text)
    blocks: CollectionProperty(type=MBBlock)
    active_block: IntProperty()
    category: EnumProperty(name="Category", items=category_items)
    search: StringProperty(name="Search blocks", default="", options={"TEXTEDIT_UPDATE"})
    regex_search: BoolProperty(
        name="Regex", description="Match block names or IDs with a regular expression"
    )
    rule_scope: EnumProperty(
        name="Apply rules to",
        items=[
            ("CHECKED", "Checked blocks", "Rows selected with checkboxes"),
            ("FILTERED", "Filtered results", "Every row matching search and category"),
            ("ALL", "Entire palette", "Every block in this preset"),
        ],
    )
    width: IntProperty(name="Width (X)", default=48, min=1, max=512)
    height: IntProperty(name="Height (Y)", default=48, min=1, max=512)
    depth: IntProperty(name="Depth (Z)", default=48, min=1, max=512)
    preserve: BoolProperty(name="Keep proportions", default=True)
    preview_real_scale: BoolProperty(
        name="Preview: 1 meter per block",
        description="Show Minecraft blocks at their real size in Blender; export dimensions stay unchanged",
        default=False,
        update=preview_scale_changed,
    )
    hollow: BoolProperty(name="Hollow build", default=True)
    thickness: IntProperty(
        name="Shell thickness",
        description="Thickness in Minecraft blocks",
        default=1,
        min=1,
        max=16,
    )
    interior_state: StringProperty(
        name="Interior material", description="Optional allowed full block for a solid interior"
    )
    whitelist: BoolProperty(name="Only use explicitly allowed blocks", default=False)
    slabs: BoolProperty(name="Slabs", default=True)
    stairs: BoolProperty(name="Stairs", default=True)
    gravity: BoolProperty(name="Allow falling blocks", default=False)
    special_appearance: BoolProperty(
        name="Allow glass / biome colors",
        default=False,
        description="Enable optional transparent and biome-tinted materials. Colors use a Plains reference and can differ in-game",
    )
    shape_weight: FloatProperty(
        name="Prefer shape",
        description="0 prioritizes color; 1 prioritizes geometric fit",
        default=0.65,
        min=0,
        max=1,
    )
    face_matching: BoolProperty(
        name="Match visible block faces",
        default=False,
        description="Match exposed sides and select legal block orientations; turn off for average-color matching",
    )
    color_mode: EnumProperty(
        name="Color source",
        items=[
            (
                "MATERIAL",
                "Textures / materials",
                "Read UV textures, flat colors or color attributes",
            ),
            ("SINGLE", "Single material", "Use the active block in the list"),
        ],
        default="MATERIAL",
    )
    build_name: StringProperty(name="Build name", default="Minecraft build")
    author: StringProperty(name="Author", default="")
    preview_token: StringProperty()
    texture_preview: BoolProperty(
        name="Use Minecraft textures",
        default=False,
        description="Optional packed textures from your selected ZIP; click Apply Preview Display after changing",
    )
    texture_source: StringProperty(name="Texture archive", subtype="FILE_PATH")
    texture_stamp: StringProperty()
    texture_file_info: StringProperty()
    texture_atlas: PointerProperty(type=bpy.types.Image)
    texture_material: PointerProperty(type=bpy.types.Material)
    texture_status: StringProperty()
    snapshot: PointerProperty(type=bpy.types.Text)
    snapshot_signature: StringProperty()
    busy: BoolProperty(default=False, options={"SKIP_SAVE"})
    status: StringProperty(default="Choose your model and a block preset")
    progress: FloatProperty(min=0, max=1, default=0, options={"SKIP_SAVE"})
    manual_edits: PointerProperty(type=bpy.types.Text)
    keep_manual_edits: BoolProperty(
        name="Keep edits on regenerate",
        default=True,
        description="Reapply saved edits at their block coordinates; uncheck to reset them on the next generation",
    )
    edit_enabled: BoolProperty(default=False, options={"SKIP_SAVE"})
    edit_count: IntProperty(default=0)
    edit_last_chunks: IntProperty(default=0)
    edit_cursor: PointerProperty(type=bpy.types.Object)
    edit_position: IntVectorProperty(size=3, min=0, max=2051, update=edit_position_changed)
    edit_from: IntVectorProperty(size=3, min=0, max=2051)
    edit_brush: StringProperty(name="Brush block")
    edit_mode: EnumProperty(
        items=[
            ("PICK", "Pick", "Pick a block and its material"),
            ("ADD", "Add", "Add beside the picked face"),
            ("REPLACE", "Repaint", "Change the clicked block material"),
            ("DELETE", "Delete", "Remove the clicked block"),
            ("MOVE", "Move", "Drag a block across its horizontal plane; wheel adjusts height"),
            ("SELECT", "Select area", "Click two opposite corner blocks to select a box"),
        ]
    )
    edit_half: EnumProperty(name="Half", items=[("bottom", "Bottom", ""), ("top", "Top", "")])
    edit_facing: EnumProperty(
        name="Facing", items=[(s, s.title(), "") for s in ("north", "east", "south", "west")]
    )
    edit_through_glass: BoolProperty(name="Pick through glass", default=True)
    edit_radius: IntProperty(
        name="Brush radius",
        default=0,
        min=0,
        max=16,
        description="0 edits one block; larger values apply a spherical brush",
    )
    edit_selection_a: IntVectorProperty(
        name="Selection corner A", size=3, min=0, max=2051, update=edit_selection_changed
    )
    edit_selection_b: IntVectorProperty(
        name="Selection corner B", size=3, min=0, max=2051, update=edit_selection_changed
    )
    edit_clipboard: PointerProperty(type=bpy.types.Text)
    edit_replace_source: StringProperty(name="Replace block")
    edit_paste_overwrite: BoolProperty(name="Overwrite on paste", default=False)
    edit_paste_air: BoolProperty(name="Paste empty cells", default=False)
    edit_mirror: EnumProperty(
        name="Mirror axis",
        items=[
            ("NONE", "None", ""),
            ("X", "X", "East/west"),
            ("Y", "Y", "Up/down"),
            ("Z", "Z", "North/south"),
        ],
    )


def settings_signature(options):
    values = {
        k: getattr(options, k)
        for k in (
            "target_version",
            "width",
            "height",
            "depth",
            "preserve",
            "hollow",
            "thickness",
            "interior_state",
            "whitelist",
            "slabs",
            "stairs",
            "gravity",
            "shape_weight",
            "color_mode",
        )
    }
    values["blocks"] = [(b.state, b.policy, tuple(b.color)) for b in options.blocks]
    values["sources"] = [
        (s.object.name, [list(row) for row in s.object.matrix_world])
        for s in options.sources
        if s.object
    ]
    if options.model_up != "Z":
        values["model_up"] = options.model_up  # Retain signatures of 0.1.0 scenes.
    if options.special_appearance:
        values["special_appearance"] = True
    if options.face_matching:
        values["face_matching"] = True
    if options.color_mode == "SINGLE":
        values["single"] = options.blocks[options.active_block].state if options.blocks else ""
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def chosen_blocks(options):
    if not options.blocks or options.loaded_version != options.target_version:
        load_preset(options)
    profile = catalog.profiles(options)[options.target_version]
    originals = {b.state: b for b in profile.blocks}
    rows = list(options.blocks)
    if options.color_mode == "SINGLE":
        rows = [rows[options.active_block]]
    candidates = []
    for row in rows:
        if (
            row.shape == "slab"
            and not options.slabs
            or row.shape == "stairs"
            and not options.stairs
        ):
            continue
        original = originals[row.state]
        rgb = tuple(max(0, min(255, round(255 * srgb(v)))) for v in row.color)
        candidates.append(
            replace(original, rgb=rgb)
            if rgb == original.rgb
            else replace(
                original, rgb=rgb, faces=(), variants=tuple((s, ()) for s, _ in original.variants)
            )
        )
    return profile, allowed_blocks(
        candidates,
        [r.state for r in rows if r.policy == "ALLOW"] if options.whitelist else None,
        [r.state for r in rows if r.policy == "DENY"],
        options.gravity,
        options.special_appearance,
    )


def base_snapshot(options):
    if not options.snapshot:
        raise ValueError("Generate a preview first")
    if settings_signature(options) != options.snapshot_signature:
        raise ValueError("Settings changed. Regenerate the preview before exporting.")
    for obj in bpy.context.scene.objects:
        if obj.get("minecraft_builder_preview") == options.preview_token:
            basis = [v for row in obj.matrix_basis.to_3x3() for v in row]
            saved = obj.get("minecraft_builder_basis")
            changed = (
                any(abs(a - b) > 1e-5 for a, b in zip(basis, saved))
                if saved is not None
                else abs(obj.matrix_basis.to_quaternion().angle) > 1e-5
                or obj.matrix_basis.determinant() < 0
            )
            if changed:
                raise ValueError(
                    "Preview was rotated or scaled. Set Model up direction or rotate the source, then regenerate."
                )
    try:
        raw = base64.b64decode(options.snapshot.as_string(), validate=True)
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            content = stream.read(256 * 1024 * 1024 + 1)
        if len(content) > 256 * 1024 * 1024:
            raise ValueError("Saved preview is too large")
        build = json.loads(content)
        exporters.validate_build(build)
        profile = catalog.profiles(options).get(options.target_version)
        if profile is None:
            raise ValueError("Choose a Minecraft version")
        exporters.validate_profile(build, profile)
        return build
    except (ValueError, OSError) as exc:
        raise ValueError("Saved preview is invalid; regenerate it") from exc


def snapshot(options):
    from .live_edit import edited_snapshot

    return edited_snapshot(bpy.context, options, "MODEL", base_snapshot(options))


def clear_generated(token):
    if not token:
        return
    for obj in list(bpy.data.objects):
        if obj.get("minecraft_builder_preview") == token or obj.get("mb_edit_preview") == token:
            mesh = obj.data if obj.type == "MESH" else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
    for collection in list(bpy.data.collections):
        if (
            collection.get("minecraft_builder_preview") == token
            and not collection.objects
            and not collection.children
        ):
            bpy.data.collections.remove(collection)
    for material in list(bpy.data.materials):
        if (
            material.get("minecraft_builder_preview") == token
            or material.get("mb_edit_preview") == token
        ) and material.users == 0:
            bpy.data.materials.remove(material)


def capture(options, context):
    selected = set()
    for obj in context.selected_objects:
        for child in [obj, *obj.children_recursive]:
            if (
                child.type == "MESH"
                and not child.get("minecraft_builder_preview")
                and not child.get("minecraft_perimeter_generated")
                and not child.get("mb_edit_preview")
            ):
                selected.add(child)
    if not selected:
        raise ValueError("Select a mesh model, or its parent, in the viewport")
    options.sources.clear()
    for obj in sorted(selected, key=lambda o: o.name):
        options.sources.add().object = obj
    options.status = f"{len(selected)} source meshes selected"


class MB_OT_capture(bpy.types.Operator):
    bl_idname = "minecraft_builder.capture"
    bl_label = "Use Selected Model"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            capture(context.scene.minecraft_builder, context)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class MB_OT_load(bpy.types.Operator):
    bl_idname = "minecraft_builder.load_preset"
    bl_label = "Reload Block Preset"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Refresh the block list and preset colors after an update; keep Include/Exclude rules, then regenerate"
    target: StringProperty(default="MODEL", options={"HIDDEN"})

    def execute(self, context):
        try:
            load_preset(palette_settings(context, self.target))
        except (ValueError, OSError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class MB_OT_rules(bpy.types.Operator):
    bl_idname = "minecraft_builder.rules"
    bl_label = "Set Block Rules"
    bl_options = {"REGISTER", "UNDO"}
    policy: EnumProperty(
        items=[("AUTO", "Reset", ""), ("ALLOW", "Allow", ""), ("DENY", "Exclude", "")]
    )
    target: StringProperty(default="MODEL", options={"HIDDEN"})

    def execute(self, context):
        options = palette_settings(context, self.target)
        try:
            rows = [
                r
                for r in options.blocks
                if options.rule_scope == "ALL"
                or (options.rule_scope == "CHECKED" and r.selected)
                or (options.rule_scope == "FILTERED" and matches_filter(options, r))
            ]
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        if not rows:
            self.report({"WARNING"}, "No matching blocks selected")
            return {"CANCELLED"}
        for row in rows:
            row.policy = self.policy
        options.status = f"Updated {len(rows)} block rules"
        return {"FINISHED"}


class MB_OT_select_blocks(bpy.types.Operator):
    bl_idname = "minecraft_builder.select_blocks"
    bl_label = "Select Blocks"
    bl_options = {"REGISTER", "UNDO"}
    mode: EnumProperty(
        items=[
            ("ALL", "Select all results", "Select all rows matching the current filter"),
            ("NONE", "Clear selection", "Clear every checkbox"),
            ("INVERT", "Invert results", "Invert checkboxes in the current filter"),
        ]
    )
    target: StringProperty(default="MODEL", options={"HIDDEN"})

    def execute(self, context):
        options = palette_settings(context, self.target)
        try:
            rows = (
                list(options.blocks)
                if self.mode == "NONE"
                else [r for r in options.blocks if matches_filter(options, r)]
            )
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        for row in rows:
            row.selected = not row.selected if self.mode == "INVERT" else self.mode == "ALL"
        return {"FINISHED"}


class MB_OT_only_blocks(bpy.types.Operator):
    bl_idname = "minecraft_builder.only_blocks"
    bl_label = "Use Only These Blocks"
    bl_options = {"REGISTER", "UNDO"}
    scope: EnumProperty(
        items=[
            ("CHECKED", "Use only checked", "Replace the allowed list with checked rows"),
            (
                "FILTERED",
                "Use only search results",
                "Replace the allowed list with all matching rows",
            ),
        ]
    )
    target: StringProperty(default="MODEL", options={"HIDDEN"})

    def execute(self, context):
        options = palette_settings(context, self.target)
        try:
            states = {
                r.state
                for r in options.blocks
                if (r.selected if self.scope == "CHECKED" else matches_filter(options, r))
            }
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        if not states:
            self.report(
                {"WARNING"}, "No blocks matched. Check rows or enter a matching search first."
            )
            return {"CANCELLED"}
        for row in options.blocks:
            row.policy = "ALLOW" if row.state in states else "DENY"
        options.whitelist = True
        count = len(eligible_rows(options))
        options.status = f"Only {len(states)} selected materials allowed; {count} eligible after material filters"
        if not count:
            self.report(
                {"WARNING"},
                "Enable the matching shape, falling-block or glass / biome colors checkbox",
            )
        return {"FINISHED"}


class MB_OT_material_preset(bpy.types.Operator):
    bl_idname = "minecraft_builder.material_preset"
    bl_label = "Material Preset"
    bl_options = {"REGISTER", "UNDO"}
    preset: EnumProperty(
        items=[
            (
                "SURVIVAL",
                "Survival obtainable",
                "Exclude blocks unavailable through normal survival collection or crafting",
            ),
            ("ALL", "All materials", "Reset block rules and disable whitelist mode"),
        ]
    )
    target: StringProperty(default="MODEL", options={"HIDDEN"})

    def execute(self, context):
        options = palette_settings(context, self.target)
        try:
            if not options.blocks or options.loaded_version != options.target_version:
                load_preset(options)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        survival = self.preset == "SURVIVAL"
        for row in options.blocks:
            row.policy = (
                ("ALLOW" if survival_obtainable(row.state, options.target_version) else "DENY")
                if survival
                else "AUTO"
            )
        options.whitelist = survival
        options.status = f"{sum(r.policy != 'DENY' for r in options.blocks)} materials in " + (
            "survival preset" if survival else "full palette"
        )
        return {"FINISHED"}


class MB_OT_interior(bpy.types.Operator):
    bl_idname = "minecraft_builder.interior"
    bl_label = "Use Active Block Inside"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        options = context.scene.minecraft_builder
        if not options.blocks or options.blocks[options.active_block].shape != "cube":
            self.report({"ERROR"}, "Choose a full cube for the interior")
            return {"CANCELLED"}
        options.interior_state = options.blocks[options.active_block].state
        return {"FINISHED"}


def install_model_snapshot(context, options, build, mesh_data, grid):
    """Commit a complete preview, then release the previous generated objects."""
    from .blender_mesh import install_preview

    token = str(uuid.uuid4())
    try:
        install_preview(context, build, mesh_data, grid, token)
        encoded = base64.b64encode(
            gzip.compress(json.dumps(build, separators=(",", ":")).encode(), mtime=0)
        ).decode()
        text = bpy.data.texts.new("Minecraft Builder preview data")
        text.write(encoded)
    except Exception:
        clear_generated(token)
        raise
    old_token = options.preview_token
    old_text = options.snapshot
    options.preview_token = token
    options.snapshot = text
    options.snapshot_signature = settings_signature(options)
    clear_generated(old_token)
    if old_text and old_text.users == 0:
        bpy.data.texts.remove(old_text)


class MB_OT_generate(bpy.types.Operator):
    bl_idname = "minecraft_builder.generate"
    bl_label = "Generate Block Preview"
    bl_options = {"REGISTER", "UNDO"}
    _timer = None
    _job = None
    _scene = None

    @classmethod
    def poll(cls, context):
        options = context.scene.minecraft_builder
        if options.target_version == "NONE":
            cls.poll_message_set("Choose your Minecraft version in Blocks first")
            return False
        return not options.busy

    def job(self, context):
        from .blender_mesh import ColorSampler, extract_sources, preview_mesh
        from .core.volume import convert

        options = context.scene.minecraft_builder
        if not options.sources:
            capture(options, context)
        objects = [s.object for s in options.sources if s.object]
        if not objects:
            raise ValueError("The source objects were removed; select a model again")
        profile, blocks = chosen_blocks(options)
        interior = next((b for b in blocks if b.state == options.interior_state), None)
        if (
            not options.hollow
            and options.interior_state
            and (interior is None or interior.shape != "cube")
        ):
            raise ValueError("The interior block must be an allowed full cube in this version")
        yield "Reading model", 0.0
        sources, grid, triangles = extract_sources(
            objects,
            context.evaluated_depsgraph_get(),
            (options.width, options.height, options.depth),
            options.preserve,
            options.model_up,
        )
        sampler = ColorSampler(sources) if options.color_mode == "MATERIAL" else None
        sample = sampler.sample if sampler else lambda _: blocks[0].rgb
        for stage, value in convert(
            sources,
            grid.size,
            blocks,
            sample,
            options.hollow,
            options.thickness,
            options.shape_weight,
            interior,
            options.face_matching,
        ):
            if stage == "result":
                build = value
            else:
                yield stage, value
        build.update(
            data_version=profile.data_version,
            version=profile.id,
            source_triangles=triangles,
            hollow=options.hollow,
            shell_thickness=options.thickness,
            model_up=options.model_up,
            face_matching=options.face_matching,
        )
        for stage, value in preview_mesh(build):
            if stage == "result":
                mesh_data = value
            else:
                yield stage, value
        install_model_snapshot(context, options, build, mesh_data, grid)
        dims = " x ".join(str(v) for v in build["size"])
        options.status = f"{len(build['cells']):,} blocks | {dims} | {len(build['palette'])} states"
        from .live_edit import generation_finished

        generation_finished(context, options, "MODEL")
        if build["warnings"]:
            self.report({"WARNING"}, build["warnings"][0])
        yield "done", 1.0

    def finish(self, context):
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        if self._job:
            self._job.close()
            self._job = None
        if self._scene:
            self._scene.minecraft_builder.busy = False
        context.window_manager.progress_end()

    def execute(self, context):
        self._scene = context.scene
        options = context.scene.minecraft_builder
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
        options = context.scene.minecraft_builder
        options.busy = True
        self._job = self.job(context)
        self._timer = context.window_manager.event_timer_add(0.02, window=context.window)
        context.window_manager.progress_begin(0, 100)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC" or context.scene != self._scene:
            self._scene.minecraft_builder.status = "Cancelled; previous preview retained"
            self.finish(context)
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        options = self._scene.minecraft_builder
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


class MB_OT_export(bpy.types.Operator, ExportHelper):
    bl_idname = "minecraft_builder.export"
    bl_label = "Export Preview"
    filename_ext = ".schem"
    filter_glob: StringProperty(default="*.schem", options={"HIDDEN"})
    format: EnumProperty(
        items=[
            ("schem", "WorldEdit", ""),
            ("litematic", "Litematica", ""),
            ("bp", "Axiom blueprint", ""),
        ],
        default="schem",
        options={"HIDDEN"},
    )

    def invoke(self, context, event):
        self.filename_ext = "." + self.format
        self.filter_glob = "*." + self.format
        options = context.scene.minecraft_builder
        self.filepath = (
            bpy.path.clean_name(options.build_name + "-mc" + options.target_version)
            + self.filename_ext
        )
        return ExportHelper.invoke(self, context, event)

    def draw(self, context):
        self.layout.label(
            text="Minecraft Java " + context.scene.minecraft_builder.target_version, icon="INFO"
        )
        self.layout.label(text="Open in this version or a compatible newer version.")

    def execute(self, context):
        options = context.scene.minecraft_builder
        try:
            build = snapshot(options)
            path = bpy.path.ensure_ext(self.filepath, "." + self.format)
            exporters.write(path, build, self.format, options.build_name, options.author)
        except (OSError, ValueError, KeyError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report(
            {"INFO"}, f"Exported {len(build['cells']):,} blocks for Java {build['version']}"
        )
        return {"FINISHED"}


class MB_OT_materials(bpy.types.Operator, ExportHelper):
    bl_idname = "minecraft_builder.materials"
    bl_label = "Export Material List"
    filename_ext = ".csv"
    filter_glob: StringProperty(default="*.csv", options={"HIDDEN"})

    def execute(self, context):
        import csv

        try:
            counts = exporters.material_counts(snapshot(context.scene.minecraft_builder))
            with open(self.filepath, "w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["Block", "Count", "Full stacks", "Remainder"])
                for block, count in sorted(counts.items()):
                    writer.writerow([block, count, count // 64, count % 64])
        except (ValueError, OSError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class MB_OT_import_palette(bpy.types.Operator, ImportHelper):
    bl_idname = "minecraft_builder.import_palette"
    bl_label = "Import Palette File"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})
    target: StringProperty(default="MODEL", options={"HIDDEN"})

    def execute(self, context):
        options = palette_settings(context, self.target)
        try:
            document = load_file(self.filepath)
            previous = (
                json.loads(options.custom_palettes.as_string())
                if options.custom_palettes
                else {"schema_version": 1, "profiles": []}
            )
            merged = {entry["id"]: entry for entry in previous["profiles"]}
            merged.update({entry["id"]: entry for entry in document["profiles"]})
            result = {"schema_version": 1, "profiles": list(merged.values())}
            parse_document(result)
            text = bpy.data.texts.new("Minecraft Builder imported palettes")
            text.write(json.dumps(result))
            old = options.custom_palettes
            options.custom_palettes = text
            options.target_version = document["profiles"][0]["id"]
            load_preset(options)
            if old and old.users == 0:
                bpy.data.texts.remove(old)
        except (ValueError, OSError, KeyError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class MB_OT_export_palette(bpy.types.Operator, ExportHelper):
    bl_idname = "minecraft_builder.export_palette"
    bl_label = "Export Allowed Palette"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})
    target: StringProperty(default="MODEL", options={"HIDDEN"})

    def execute(self, context):
        try:
            profile, blocks = chosen_blocks(palette_settings(context, self.target))
            Path(self.filepath).write_text(
                json.dumps(profile_document(profile, blocks), indent=2), encoding="utf-8"
            )
        except (OSError, ValueError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class MB_UL_blocks(bpy.types.UIList):
    def draw_filter(self, context, layout):
        # The native UIList search must edit the SAME query as the bulk actions.
        # Otherwise typing in its filter field appears to select the entire list.
        layout.prop(context.scene.minecraft_builder, "search", text="", icon="VIEWZOOM")

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "selected", text="")
        swatch = row.row()
        swatch.ui_units_x = 0.7
        swatch.prop(item, "color", text="")
        row.label(text=item.name)
        if item.special_appearance:
            row.label(text="", icon="INFO")
        rule = row.row()
        rule.ui_units_x = 4.5
        rule.prop(item, "policy", text="")

    def filter_items(self, context, data, propname):
        flags = []
        p = data
        for item in getattr(data, propname):
            try:
                match = matches_filter(p, item)
            except ValueError:
                match = False
            flags.append(self.bitflag_filter_item if match else 0)
        return flags, []


def draw_model_sources(controls, options):
    box = controls.box()
    box.label(text="1  Model", icon="OUTLINER_OB_MESH")
    box.operator("minecraft_builder.capture")
    box.label(text=f"{sum(1 for s in options.sources if s.object)} source meshes")
    box.prop(options, "model_up")


def draw_model_dimensions(controls, options):
    box = controls.box()
    box.label(text="2  Size and structure", icon="FULLSCREEN_ENTER")
    box.prop(options, "width")
    box.prop(options, "height")
    box.prop(options, "depth")
    box.prop(options, "preserve")
    box.prop(options, "preview_real_scale")
    box.prop(options, "hollow")
    if options.hollow:
        box.prop(options, "thickness")
    else:
        box.prop(options, "interior_state")
        box.operator("minecraft_builder.interior")


def draw_model_blocks(controls, options):
    box = controls.box()
    box.label(text="3  Blocks", icon="MATERIAL")
    box.prop(options, "target_version")
    if options.target_version == "NONE":
        box.label(text="Choose the version of your Minecraft instance.", icon="INFO")
    else:
        box.operator("minecraft_builder.load_preset", icon="FILE_REFRESH")
    row = box.row(align=True)
    for preset, label in (("SURVIVAL", "Survival obtainable"), ("ALL", "All materials")):
        row.operator("minecraft_builder.material_preset", text=label).preset = preset
    box.prop(options, "color_mode")
    box.prop(options, "category")
    row = box.row(align=True)
    row.prop(options, "search", text="", icon="VIEWZOOM")
    row.prop(options, "regex_search")
    try:
        visible = sum(matches_filter(options, r) for r in options.blocks)
    except ValueError as e:
        visible = 0
        error = box.row()
        error.alert = True
        error.label(text=str(e), icon="ERROR")
    row = box.row(align=True)
    row.prop(options, "slabs")
    row.prop(options, "stairs")
    box.prop(options, "gravity")
    box.prop(options, "whitelist")
    box.prop(options, "special_appearance")
    box.prop(options, "face_matching")
    if options.special_appearance:
        box.label(text="Tint: Plains; transparency varies in-game.", icon="INFO")
    box.template_list("MB_UL_blocks", "", options, "blocks", options, "active_block", rows=7)
    box.label(
        text=f"{visible} results · {sum(r.selected for r in options.blocks)} checked · {len(eligible_rows(options))} eligible"
    )
    row = box.row(align=True)
    for mode, label in (("ALL", "Select all results"), ("NONE", "Clear"), ("INVERT", "Invert")):
        row.operator("minecraft_builder.select_blocks", text=label).mode = mode
    box.operator(
        "minecraft_builder.only_blocks", text="Use only checked", icon="CHECKMARK"
    ).scope = "CHECKED"
    box.operator(
        "minecraft_builder.only_blocks", text="Use only search results", icon="VIEWZOOM"
    ).scope = "FILTERED"
    box.prop(options, "rule_scope")
    row = box.row(align=True)
    for policy, label in (("ALLOW", "Include"), ("DENY", "Exclude"), ("AUTO", "Reset")):
        op = row.operator("minecraft_builder.rules", text=label)
        op.policy = policy
    if options.blocks and options.active_block < len(options.blocks):
        active = options.blocks[options.active_block]
        box.prop(active, "policy", text="Selected block")
        box.label(text=active.shape.title() + " | " + active.category)
        box.label(text=active.state, icon="INFO")
    row = box.row(align=True)
    row.operator("minecraft_builder.import_palette", text="Import palette")
    row.operator("minecraft_builder.export_palette", text="Export palette")
    box.prop(options, "shape_weight", slider=True)


def draw_model_export(controls, options):
    box = controls.box()
    box.label(text="4  Export preview", icon="EXPORT")
    box.label(text="Target: Minecraft Java " + options.target_version, icon="INFO")
    box.prop(options, "build_name")
    box.prop(options, "author")
    row = box.row(align=True)
    for fmt, label in (
        ("schem", "WorldEdit"),
        ("litematic", "Litematica"),
        ("bp", "Axiom"),
    ):
        op = row.operator("minecraft_builder.export", text=label)
        op.format = fmt
    box.operator("minecraft_builder.materials", icon="TEXT")
    box.label(text="Regenerate after changing the source model.", icon="INFO")


class MB_PT_main(bpy.types.Panel):
    bl_label = "Minecraft Builder"
    bl_idname = "MB_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Minecraft"

    def draw(self, context):
        options = context.scene.minecraft_builder
        layout = self.layout
        controls = layout.column()
        controls.enabled = not options.busy
        draw_model_sources(controls, options)
        draw_model_dimensions(controls, options)
        draw_model_blocks(controls, options)
        controls.operator("minecraft_builder.generate", icon="MOD_REMESH")
        from .textured_preview import draw as draw_textures

        draw_textures(controls, options, "MODEL")
        layout.label(text=options.status)
        if options.busy:
            layout.progress(factor=options.progress, type="BAR", text="Esc to cancel")
        if options.snapshot:
            draw_model_export(controls, options)


CLASSES = (
    MBSource,
    MBBlock,
    MBSettings,
    MB_OT_capture,
    MB_OT_load,
    MB_OT_rules,
    MB_OT_select_blocks,
    MB_OT_only_blocks,
    MB_OT_material_preset,
    MB_OT_interior,
    MB_OT_generate,
    MB_OT_export,
    MB_OT_materials,
    MB_OT_import_palette,
    MB_OT_export_palette,
    MB_UL_blocks,
    MB_PT_main,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.minecraft_builder = PointerProperty(type=MBSettings)


def unregister():
    if hasattr(bpy.types.Scene, "minecraft_builder"):
        del bpy.types.Scene.minecraft_builder
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
