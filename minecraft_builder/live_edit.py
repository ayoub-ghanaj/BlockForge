"""Saved block editing with small preview-chunk rebuilds and viewport tools."""

import json
import math

import bpy
import numpy as np
from bpy.app.handlers import persistent
from bpy.props import EnumProperty
from bpy_extras import view3d_utils

from . import catalog, ui
from .blender_mesh import FACE_CORNERS
from .core import bulk, editing
from .core.palette import linear
from .core.shapes import orientations, split_state, state_mask, with_properties
from .perimeter.materials import GLASS, emission, is_glass

_sessions = {}
_view_tools = {}
TARGETS = [("MODEL", "Model", ""), ("PERIMETER", "Perimeter", "")]


def active_view(context, target):
    if not context.window or not context.area:
        return None
    tool = _view_tools.get((context.window.as_pointer(), context.area.as_pointer()))
    try:
        return tool if tool and tool.target == target and tool._scene == context.scene else None
    except ReferenceError:
        return None


def settings(context, target):
    return ui.palette_settings(context, target)


def root_object(context, options, target):
    tag = "minecraft_builder_preview" if target == "MODEL" else "minecraft_perimeter_generated"
    return next((o for o in context.scene.objects if o.get(tag) == options.preview_token), None)


def display(pos, target):
    x, y, z = pos
    return (x, -z, y) if target == "MODEL" else (x - 1, 1 - z, y - 1)


def canonical(pos, target):
    x, y, z = pos
    return (x, z, -y) if target == "MODEL" else (x + 1, z + 1, 1 - y)


def document(options):
    if not options.manual_edits:
        return editing.empty_document()
    text = options.manual_edits.as_string()
    if len(text) > 128 * 1024 * 1024:
        raise ValueError("Saved edit layer is too large")
    data = json.loads(text)
    if data.get("schema_version") != 1 or not isinstance(data.get("patches"), dict):
        raise ValueError("Invalid saved edit layer")
    return data


def save_document(options, data):
    if not options.manual_edits:
        options.manual_edits = bpy.data.texts.new("Minecraft manual block edits")
    options.manual_edits.clear()
    options.manual_edits.write(json.dumps(data, separators=(",", ":")))
    options.edit_count = len(data["patches"])


def material_options(options, target):
    profile, blocks = ui.chosen_blocks(options)
    materials = {}
    for block in blocks:
        for state, _ in orientations(block):
            materials[state] = (block.rgb, block.shape)
            if block.shape == "stairs":
                for corner in ("inner_left", "inner_right", "outer_left", "outer_right"):
                    materials[with_properties(state, shape=corner)] = (block.rgb, block.shape)
    if target == "PERIMETER":
        from .perimeter.covers import KINDS, choices
        from .perimeter.materials import lighting_blocks

        for block in (*GLASS, *lighting_blocks(profile)):
            materials[block.state] = (block.rgb, block.shape)
        for kind, _, _ in KINDS:
            for block in choices(profile, kind):
                materials[block.state] = (block.rgb, block.shape)
    return materials


def base_snapshot(options, target):
    if target == "MODEL":
        return ui.base_snapshot(options)
    from .perimeter import ui as perimeter_ui

    return perimeter_ui.base_snapshot(options)


def validate_current(context, options, target):
    if not options.snapshot:
        raise ValueError("Generate a preview first")
    from .perimeter import ui as perimeter_ui

    signature = (
        ui.settings_signature(options)
        if target == "MODEL"
        else perimeter_ui.settings_signature(options)
    )
    if signature != options.snapshot_signature:
        raise ValueError("Settings changed; regenerate before editing blocks")
    root = root_object(context, options, target)
    if root:
        saved = root.get("minecraft_builder_basis" if target == "MODEL" else "perimeter_basis")
        if saved and any(
            abs(a - b) > 1e-5
            for a, b in zip((v for row in root.matrix_basis.to_3x3() for v in row), saved)
        ):
            raise ValueError(
                "Preview was rotated/scaled; regenerate or use the preview scale checkbox"
            )


def session(context, options, target, base=None):
    validate_current(context, options, target)
    key = (context.scene.as_pointer(), target)
    marker = (
        options.snapshot.as_pointer(),
        options.manual_edits.as_string() if options.manual_edits else "",
    )
    if key not in _sessions or _sessions[key][0] != marker:
        if base is None:
            base = base_snapshot(options, target)
        limits = (
            (options.width, options.height, options.depth)
            if target == "MODEL"
            else (options.width + 2, options.height + 2, options.depth + 2)
        )
        obj = editing.Editor(
            base,
            document(options),
            material_options(options, target),
            limits,
            2_000_000 if target == "MODEL" else 64_000_000,
        )
        _sessions[key] = (marker, obj)
    return _sessions[key][1]


def edited_snapshot(context, options, target, base):
    if not options.manual_edits or not document(options)["patches"]:
        return base
    result = session(context, options, target, base).result()
    if target == "MODEL":
        from .core.exporters import validate_build, validate_profile

        validate_build(result)
        validate_profile(result, catalog.profiles(options)[options.target_version])
    else:
        from .perimeter.streaming import validate

        validate(result)
    return result


def new_chunk(context, root, key, vertices, polygons, materials, indices, options, uvs=None):
    mesh = bpy.data.meshes.new("Minecraft edit section")
    mesh.from_pydata(vertices, [], polygons)
    mesh.update()
    for material in materials:
        mesh.materials.append(material)
    if indices:
        mesh.polygons.foreach_set("material_index", indices)
    if uvs is not None:
        layer = mesh.uv_layers.new(name="Minecraft block textures")
        layer.data.foreach_set("uv", uvs.ravel())
    obj = bpy.data.objects.new("Blocks " + ",".join(map(str, key)), mesh)
    obj.parent = root
    obj["mb_edit_preview"] = options.preview_token
    obj["mb_edit_chunk_key"] = list(key)
    root.users_collection[0].objects.link(obj)
    return obj


def chunkify(context, options, target):
    root = root_object(context, options, target)
    if not root:
        raise ValueError("Preview object is missing; regenerate it")
    if root.get("mb_edit_chunked"):
        return root
    mesh = root.data
    n = len(mesh.polygons)
    if not n:
        raise ValueError("Preview has no geometry")
    centers = np.empty(n * 3, np.float32)
    normals = np.empty(n * 3, np.float32)
    mesh.polygons.foreach_get("center", centers)
    mesh.polygons.foreach_get("normal", normals)
    points = (centers - normals * 1e-4).reshape(-1, 3)
    points = points[:, [0, 2, 1]] * np.array([1, 1, -1])
    if target == "PERIMETER":
        points += np.array([1, 1, 1])
    keys = np.floor(points / 16).astype(np.int32)
    unique, inverse = np.unique(keys, axis=0, return_inverse=True)
    coords = np.empty(len(mesh.vertices) * 3, np.float32)
    mesh.vertices.foreach_get("co", coords)
    coords = coords.reshape(-1, 3)
    loops = np.empty(len(mesh.loops), np.int32)
    mesh.loops.foreach_get("vertex_index", loops)
    totals = np.empty(n, np.int32)
    mesh.polygons.foreach_get("loop_total", totals)
    if not np.all(totals == 4):
        raise ValueError("Preview mesh topology changed; regenerate it before editing")
    loops = loops.reshape(-1, 4)
    mats = np.empty(n, np.int32)
    mesh.polygons.foreach_get("material_index", mats)
    uvs = None
    if mesh.uv_layers.active:
        uvs = np.empty(len(mesh.loops) * 2, np.float32)
        mesh.uv_layers.active.data.foreach_get("uv", uvs)
        uvs = uvs.reshape(n, 4, 2)
    created = []
    try:
        for index, key in enumerate(unique):
            selected = np.flatnonzero(inverse == index)
            vertices = coords[loops[selected]].reshape(-1, 3).tolist()
            used, mi = np.unique(mats[selected], return_inverse=True)
            polygons = np.arange(len(vertices)).reshape(-1, 4).tolist()
            created.append(
                new_chunk(
                    context,
                    root,
                    tuple(map(int, key)),
                    vertices,
                    polygons,
                    [mesh.materials[i] for i in used],
                    mi.tolist(),
                    options,
                    uvs[selected] if uvs is not None else None,
                )
            )
        root.data = bpy.data.meshes.new("Minecraft editable preview root")
        root["mb_edit_chunked"] = True
        if not mesh.users:
            bpy.data.meshes.remove(mesh)
    except Exception:
        for obj in created:
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if not mesh.users:
                bpy.data.meshes.remove(mesh)
        raise
    return root


def chunk_geometry(editor, key, target):
    low = tuple(v * 16 - 1 for v in key)
    fine = np.full((36, 36, 36), -1, np.int32)
    states = []
    ids = {}
    glass = []
    partials = []
    for x in range(18):
        for y in range(18):
            for z in range(18):
                pos = (low[0] + x, low[1] + y, low[2] + z)
                state = editor.cells.get(pos)
                if state is None:
                    continue
                if state not in ids:
                    ids[state] = len(states)
                    states.append(state)
                index = ids[state]
                if editor.materials[state][1] == "cover":
                    if all(1 <= v <= 16 for v in (x, y, z)):
                        partials.append((pos, index))
                    continue
                if is_glass(state):
                    if all(1 <= v <= 16 for v in (x, y, z)):
                        glass.append((pos, index))
                    continue
                mask = state_mask(state, editor.materials[state][1])
                for ox in range(2):
                    for oy in range(2):
                        for oz in range(2):
                            if mask & (1 << (ox + 2 * oz + 4 * oy)):
                                fine[x * 2 + ox, y * 2 + oy, z * 2 + oz] = index
    occupied = fine >= 0
    inside = np.zeros_like(occupied)
    inside[2:34, 2:34, 2:34] = True
    vertices = []
    faces = []
    indices = []
    for delta, corners in FACE_CORNERS:
        neighbor = np.roll(occupied, tuple(-d for d in delta), axis=(0, 1, 2))
        for coord in np.argwhere(occupied & ~neighbor & inside):
            start = len(vertices)
            vertices.extend(
                display(tuple(low[i] + (int(coord[i]) + corner[i]) / 2 for i in range(3)), target)
                for corner in corners
            )
            faces.append((start, start + 1, start + 2, start + 3))
            indices.append(int(fine[tuple(coord)]))
    for (x, y, z), index in glass:
        start = len(vertices)
        vertices.extend(
            display(p, target)
            for p in ((x, y + 1, z), (x, y + 1, z + 1), (x + 1, y + 1, z + 1), (x + 1, y + 1, z))
        )
        faces.append((start, start + 1, start + 2, start + 3))
        indices.append(index)
    from .perimeter.covers import boxes

    for pos, index in partials:
        for bounds in boxes(states[index]):
            for delta, corners in FACE_CORNERS:
                start = len(vertices)
                vertices.extend(
                    display(
                        tuple(
                            pos[i] + bounds[i] + (bounds[i + 3] - bounds[i]) * c[i]
                            for i in range(3)
                        ),
                        target,
                    )
                    for c in corners
                )
                faces.append((start, start + 1, start + 2, start + 3))
                indices.append(index)
    return vertices, faces, states, indices


def render_material(options, state, metadata):
    rgb, shape = metadata
    key = json.dumps([list(rgb), is_glass(state), emission(state)])
    existing = next(
        (
            m
            for m in bpy.data.materials
            if m.get("mb_edit_preview") == options.preview_token and m.get("mb_edit_color") == key
        ),
        None,
    )
    if existing:
        return existing
    mat = bpy.data.materials.new("Edit " + state.split(":")[-1])
    mat["mb_edit_preview"] = options.preview_token
    mat["mb_edit_color"] = key
    mat.use_nodes = True
    rgba = tuple(linear(v / 255) for v in rgb) + (0.18 if is_glass(state) else 1,)
    mat.diffuse_color = rgba
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = rgba
    shader.inputs["Alpha"].default_value = rgba[3]
    if is_glass(state):
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "DITHERED"
        else:
            mat.blend_method = "BLEND"
    if emission(state):
        shader.inputs["Emission Color"].default_value = rgba
        shader.inputs["Emission Strength"].default_value = 0.5
    return mat


def refresh_chunks(context, options, target, editor, affected):
    root = chunkify(context, options, target)
    keys = set()
    for pos in affected:
        keys.add(tuple(v // 16 for v in pos))
        for axis in range(3):
            for sign in (-1, 1):
                other = list(pos)
                other[axis] += sign
                keys.add(tuple(v // 16 for v in other))
    old = {tuple(o["mb_edit_chunk_key"]): o for o in root.children if "mb_edit_chunk_key" in o}
    updated = []
    for key in keys:
        vertices, faces, states, indices = chunk_geometry(editor, key, target)
        if faces:
            updated.append(
                new_chunk(
                    context,
                    root,
                    key,
                    vertices,
                    faces,
                    [render_material(options, s, editor.materials[s]) for s in states],
                    indices,
                    options,
                )
            )
        if key in old:
            obj = old[key]
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if not mesh.users:
                bpy.data.meshes.remove(mesh)
    options.edit_last_chunks = len(keys)
    if options.texture_preview:
        from .textured_preview import refresh

        try:
            refresh(context, options, target, editor, updated)
        except (ValueError, OSError, RuntimeError) as error:
            options.texture_status = "Texture preview needs refresh: " + str(error)


def update_cursor(options, context):
    if options.edit_cursor:
        target = options.edit_cursor.get("mb_edit_target", "MODEL")
        options.edit_cursor.location = display(
            tuple(v + 0.5 for v in options.edit_position), target
        )


def cursor(context, options, target):
    root = root_object(context, options, target)
    if not options.edit_cursor or options.edit_cursor.parent != root:
        obj = bpy.data.objects.new("Minecraft block cursor", None)
        root.users_collection[0].objects.link(obj)
        obj.parent = root
        obj.empty_display_type = "CUBE"
        obj.empty_display_size = 0.5
        obj.show_in_front = True
        obj.hide_render = True
        obj.color = (1, 0.5, 0.03, 1)
        obj["mb_edit_preview"] = options.preview_token
        obj["mb_edit_cursor"] = True
        obj["mb_edit_target"] = target
        options.edit_cursor = obj
    update_cursor(options, context)
    return options.edit_cursor


def cursor_position(options, target):
    if not options.edit_cursor:
        return tuple(options.edit_position)
    point = canonical(options.edit_cursor.location, target)
    return tuple(math.floor(v + 1e-5) for v in point)


def brush(options, target):
    row = next(
        (
            r
            for r in ui.eligible_rows(options)
            if r.name == options.edit_brush
            or r.state == options.edit_brush
            or r.state.split("[")[0] == options.edit_brush
        ),
        None,
    )
    if row is None:
        materials = material_options(options, target)
        if options.edit_brush in materials:
            return options.edit_brush
        raise ValueError("Choose an allowed block for the edit brush")
    state = row.state
    if row.shape == "slab":
        state = with_properties(state, type=options.edit_half)
    if row.shape == "stairs":
        state = with_properties(
            state, half=options.edit_half, facing=options.edit_facing, shape="straight"
        )
    return state


def pick(options, editor, pos):
    options.edit_position = pos
    options.edit_from = pos
    state = editor.cells.get(tuple(pos))
    if state:
        name, props = split_state(state)
        row = next((r for r in options.blocks if r.state.split("[")[0] == name), None)
        options.edit_brush = row.name if row else state
        options.edit_half = (
            props.get("half", props.get("type", "bottom"))
            if props.get("type") != "double"
            else "bottom"
        )
        options.edit_facing = props.get("facing", "north")
    return state


def commit(context, options, target, editor, affected):
    if target == "PERIMETER":
        from .protection_ui import invalidate

        invalidate(options)
    refresh_chunks(context, options, target, editor, affected)
    save_document(options, editor.document)
    _sessions[(context.scene.as_pointer(), target)] = (
        (options.snapshot.as_pointer(), options.manual_edits.as_string()),
        editor,
    )
    options.status = f"{len(editor.cells):,} blocks · {options.edit_count} manual edits · updated {options.edit_last_chunks} sections"


def generation_finished(context, options, target):
    options.edit_enabled = False
    if target == "PERIMETER":
        from .protection_ui import invalidate

        invalidate(options)
    if options.manual_edits:
        doc = document(options) if options.keep_manual_edits else editing.empty_document()
        doc["undo"] = []
        doc["redo"] = []
        save_document(options, doc)
        if doc["patches"]:
            editor = session(context, options, target)
            refresh_chunks(
                context,
                options,
                target,
                editor,
                {editing.position(text) for text in doc["patches"] if text not in editor.skipped},
            )
            if editor.skipped:
                options.status += f" · {len(editor.skipped)} edits skipped (outside size/palette)"
    if options.texture_preview:
        from .textured_preview import refresh

        try:
            refresh(context, options, target)
        except (ValueError, OSError, RuntimeError) as error:
            options.texture_status = "Texture preview needs refresh: " + str(error)


class MB_OT_edit_start(bpy.types.Operator):
    bl_idname = "minecraft_builder.edit_start"
    bl_label = "Enable Block Editing"
    bl_options = {"REGISTER", "UNDO"}
    target: EnumProperty(items=TARGETS)

    def execute(self, context):
        options = settings(context, self.target)
        try:
            session(context, options, self.target)
            chunkify(context, options, self.target)
            options.edit_enabled = True
            if not options.edit_brush:
                rows = ui.eligible_rows(options)
                if rows:
                    options.edit_brush = rows[0].name
            cursor(context, options, self.target)
            options.status = "Pick or place blocks in the viewport, or use the cursor coordinates"
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class MB_OT_edit_action(bpy.types.Operator):
    bl_idname = "minecraft_builder.edit_action"
    bl_label = "Edit Minecraft Block"
    bl_options = {"REGISTER", "UNDO"}
    target: EnumProperty(items=TARGETS)
    action: EnumProperty(
        items=[
            (s, s.title(), "")
            for s in ("PICK", "ADD", "REPLACE", "DELETE", "MOVE", "UNDO", "REDO", "CLEAR", "CURSOR")
        ]
    )

    def execute(self, context):
        options = settings(context, self.target)
        try:
            editor = session(context, options, self.target)
            if not options.edit_cursor:
                cursor(context, options, self.target)
            pos = cursor_position(options, self.target)
            options.edit_position = pos
            if self.action == "CURSOR":
                bpy.ops.object.select_all(action="DESELECT")
                options.edit_cursor.select_set(True)
                context.view_layer.objects.active = options.edit_cursor
                return {"FINISHED"}
            if self.action == "PICK":
                pick(options, editor, pos)
                return {"FINISHED"}
            if self.action in ("UNDO", "REDO"):
                affected = editor.undo(self.action == "REDO")
            elif self.action == "CLEAR":
                affected = editor.change(
                    {editing.position(s): editing.BASE for s in editor.document["patches"]}
                )
            else:
                if self.action in ("DELETE", "REPLACE") and pos not in editor.cells:
                    raise ValueError("No block at this position")
                if self.action in ("ADD", "MOVE") and pos in editor.cells:
                    raise ValueError("That position is occupied; use Replace to repaint it")
                if self.action == "MOVE":
                    source = tuple(options.edit_from)
                    if source not in editor.cells:
                        raise ValueError("Pick a block before moving it")
                    changes = {source: None, pos: editor.cells[source]}
                else:
                    state = None if self.action == "DELETE" else brush(options, self.target)
                    changes = {
                        point: state
                        for point in bulk.brush_positions(pos, options.edit_radius, editor.limits)
                        if (
                            point not in editor.cells
                            if self.action == "ADD"
                            else point in editor.cells
                        )
                    }
                affected = editor.change(changes)
                if self.action == "MOVE":
                    options.edit_from = pos
            commit(context, options, self.target, editor, affected)
        except (ValueError, RuntimeError, KeyError) as error:
            _sessions.pop((context.scene.as_pointer(), self.target), None)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class MB_OT_bulk_edit(bpy.types.Operator):
    bl_idname = "minecraft_builder.bulk_edit"
    bl_label = "Edit Selected Blocks"
    bl_options = {"REGISTER", "UNDO"}
    target: EnumProperty(items=TARGETS)
    action: EnumProperty(
        items=[
            (s, s.title(), "")
            for s in (
                "CORNER_A",
                "CORNER_B",
                "FILL",
                "REPAINT",
                "DELETE",
                "REPLACE",
                "COPY",
                "PASTE",
                "MIRROR",
            )
        ]
    )

    def execute(self, context):
        options = settings(context, self.target)
        try:
            editor = session(context, options, self.target)
            if self.action.startswith("CORNER_"):
                setattr(
                    options,
                    "edit_selection_" + self.action[-1].lower(),
                    cursor_position(options, self.target),
                )
                show_selection(context, options, self.target)
                return {"FINISHED"}
            a, b = tuple(options.edit_selection_a), tuple(options.edit_selection_b)
            if self.action == "COPY":
                data = bulk.copy(editor.cells, a, b, editor.limits)
                if not options.edit_clipboard:
                    options.edit_clipboard = bpy.data.texts.new("Minecraft block clipboard")
                options.edit_clipboard.clear()
                options.edit_clipboard.write(json.dumps(data, separators=(",", ":")))
                options.status = f"Copied {len(data['cells']):,} blocks"
                return {"FINISHED"}
            if self.action in ("PASTE", "MIRROR"):
                axis = "" if options.edit_mirror == "NONE" else options.edit_mirror
                if self.action == "MIRROR":
                    if not axis:
                        raise ValueError("Choose a mirror axis")
                    data = bulk.copy(editor.cells, a, b, editor.limits)
                    destination = bulk.bounds(a, b, editor.limits)[0]
                    changes = bulk.paste(
                        data, destination, editor.cells, editor.limits, True, True, axis
                    )
                else:
                    if not options.edit_clipboard:
                        raise ValueError("Copy a selection first")
                    data = json.loads(options.edit_clipboard.as_string())
                    changes = bulk.paste(
                        data,
                        cursor_position(options, self.target),
                        editor.cells,
                        editor.limits,
                        options.edit_paste_overwrite,
                        options.edit_paste_air,
                        axis,
                    )
            else:
                state = None if self.action == "DELETE" else brush(options, self.target)
                source = options.edit_replace_source
                row = next(
                    (r for r in options.blocks if r.name == source or r.state == source), None
                )
                if row:
                    source = row.state.split("[")[0]
                if self.action == "REPLACE" and not source:
                    raise ValueError("Choose the block to replace")
                changes = {
                    point: state
                    for point in bulk.positions(a, b, editor.limits)
                    if self.action == "FILL"
                    or point in editor.cells
                    and (
                        self.action != "REPLACE"
                        or editor.cells[point].split("[")[0] == source.split("[")[0]
                    )
                }
            affected = editor.change(changes)
            commit(context, options, self.target, editor, affected)
            show_selection(context, options, self.target)
        except (ValueError, RuntimeError, KeyError) as error:
            _sessions.pop((context.scene.as_pointer(), self.target), None)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


def show_selection(context, options, target):
    root = root_object(context, options, target)
    if not root:
        return
    obj = next((o for o in root.children if o.get("mb_selection_box")), None)
    if obj is None:
        obj = bpy.data.objects.new("Minecraft block selection", None)
        root.users_collection[0].objects.link(obj)
        obj.parent = root
        obj.empty_display_type = "CUBE"
        obj.empty_display_size = 1
        obj.show_in_front = True
        obj.hide_render = True
        obj["mb_selection_box"] = True
        obj["mb_edit_preview"] = options.preview_token
    low = tuple(min(a, b) for a, b in zip(options.edit_selection_a, options.edit_selection_b))
    high = tuple(max(a, b) for a, b in zip(options.edit_selection_a, options.edit_selection_b))
    obj.location = display(tuple((low[i] + high[i] + 1) / 2 for i in range(3)), target)
    size = tuple((high[i] - low[i] + 1) / 2 for i in range(3))
    obj.scale = (size[0], size[2], size[1])


class MB_OT_edit_view(bpy.types.Operator):
    bl_idname = "minecraft_builder.edit_view"
    bl_label = "Edit Blocks in Viewport"
    target: EnumProperty(items=TARGETS)
    start_mode: EnumProperty(
        items=[
            (s, label, "")
            for s, label in (
                ("CURRENT", "Current tool"),
                ("PICK", "Pick block"),
                ("SELECT", "Select area"),
            )
        ],
        default="CURRENT",
        options={"SKIP_SAVE"},
    )
    _drag = False
    _area = None
    _selection_first = None
    _previous_mode = None
    _key = None
    _scene = None

    def tool_header(self, options):
        if options.edit_mode == "SELECT":
            hint = (
                "Click the first corner block"
                if self._selection_first is None
                else "Click the opposite corner block"
            )
        else:
            hint = {
                "PICK": "Click a block to pick it",
                "ADD": "Click to add",
                "REPLACE": "Click to repaint",
                "DELETE": "Click to delete",
                "MOVE": "Drag a block to move it",
            }[options.edit_mode]
        self._area.header_text_set(
            "Block tool active: " + hint + " · Esc finishes · Middle mouse orbits"
        )

    def choose_tool(self, options, mode):
        self._drag = False
        self._selection_first = None
        if mode != "CURRENT":
            options.edit_mode = mode
        self._previous_mode = options.edit_mode
        self.tool_header(options)
        self._area.tag_redraw()

    def invoke(self, context, event):
        if not context.area or context.area.type != "VIEW_3D":
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            self.report({"ERROR"}, "Switch Blender to Object Mode before editing Minecraft blocks")
            return {"CANCELLED"}
        if bpy.ops.minecraft_builder.edit_start(target=self.target) != {"FINISHED"}:
            return {"CANCELLED"}
        options = settings(context, self.target)
        self._key = (context.window.as_pointer(), context.area.as_pointer())
        existing = active_view(context, self.target)
        if existing:
            existing.choose_tool(options, self.start_mode)
            return {"FINISHED"}
        previous = _view_tools.get(self._key)
        if previous:
            previous.finish()
        self._area = context.area
        self._scene = context.scene
        _view_tools[self._key] = self
        self.choose_tool(options, self.start_mode)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def finish(self):
        if _view_tools.get(self._key) == self:
            _view_tools.pop(self._key, None)
            try:
                self._area.header_text_set(None)
                self._area.tag_redraw()
            except ReferenceError:
                pass
        self._drag = False

    def local_ray(self, root, region, coord):
        """Convert the viewport ray to Minecraft coordinates in the preview object."""
        rv3d = self._area.spaces.active.region_3d
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        inverse = root.matrix_world.inverted()
        local_origin = canonical(inverse @ origin, self.target)
        local_direction = inverse.to_3x3() @ direction
        local_direction = (local_direction.x, local_direction.z, -local_direction.y)
        return local_origin, local_direction

    def drag_block(self, event, options, editor, local_origin, local_direction):
        """Preview a snapped drag, committing one move when the mouse is released."""
        if event.type in ("WHEELUPMOUSE", "WHEELDOWNMOUSE"):
            self._height += 1 if event.type == "WHEELUPMOUSE" else -1
        if abs(local_direction[1]) > 1e-8:
            distance = (self._height + 0.5 - local_origin[1]) / local_direction[1]
            pos = tuple(
                math.floor(local_origin[i] + distance * local_direction[i])
                if i != 1
                else self._height
                for i in range(3)
            )
            if all(0 <= v < editor.limits[i] for i, v in enumerate(pos)):
                options.edit_position = pos
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            if tuple(options.edit_position) != tuple(options.edit_from):
                bpy.ops.minecraft_builder.edit_action(target=self.target, action="MOVE")
            self._drag = False

    def select_corner(self, context, options, editor, pos):
        """Accumulate the two selection clicks without changing the generated build."""
        if self._selection_first is None:
            self._selection_first = pos
            options.edit_selection_a = pos
            options.edit_selection_b = pos
            options.status = "Area selection: click the opposite corner block"
        else:
            options.edit_selection_b = pos
            low, high = bulk.bounds(tuple(options.edit_selection_a), pos, editor.limits)
            options.status = f"Selected {math.prod(high[i] - low[i] + 1 for i in range(3)):,} cells; choose a brush and Repaint blocks or Fill box"
            self.choose_tool(options, "PICK")
        show_selection(context, options, self.target)
        self.tool_header(options)

    def modal(self, context, event):
        if _view_tools.get(self._key) != self:
            return {"FINISHED"}
        if context.scene != self._scene or context.mode != "OBJECT":
            self.finish()
            return {"FINISHED"}
        options = settings(context, self.target)
        if not options.edit_enabled or not options.edit_cursor or options.busy:
            self.finish()
            return {"FINISHED"}
        if options.edit_mode != self._previous_mode:
            self.choose_tool(options, "CURRENT")
        region = next((r for r in self._area.regions if r.type == "WINDOW"), None)
        if not region:
            return {"PASS_THROUGH"}
        coord = (event.mouse_x - region.x, event.mouse_y - region.y)
        # With region overlap enabled the sidebar lies INSIDE the WINDOW bounds.
        # Let Blender handle its buttons, fields, shortcuts and popup menus.
        over_ui = any(
            r.type != "WINDOW"
            and r.width > 1
            and r.height > 1
            and r.x <= event.mouse_x < r.x + r.width
            and r.y <= event.mouse_y < r.y + r.height
            for r in self._area.regions
        )
        if over_ui or not (0 <= coord[0] < region.width and 0 <= coord[1] < region.height):
            if self._drag and event.type == "LEFTMOUSE" and event.value == "RELEASE":
                self._drag = False
                options.edit_position = options.edit_from
            return {"PASS_THROUGH"}
        if event.type in ("ESC", "RIGHTMOUSE") and event.value == "PRESS":
            self.finish()
            return {"FINISHED"}
        if event.ctrl and event.type == "Z" and event.value == "PRESS":
            bpy.ops.minecraft_builder.edit_action(
                target=self.target, action="REDO" if event.shift else "UNDO"
            )
            return {"RUNNING_MODAL"}
        if event.type in ("B", "C") and event.value == "PRESS":
            bpy.ops.minecraft_builder.bulk_edit(
                target=self.target, action="CORNER_A" if event.type == "B" else "CORNER_B"
            )
            return {"RUNNING_MODAL"}
        shortcuts = {"V": "PICK", "A": "ADD", "R": "REPLACE", "D": "DELETE", "G": "MOVE"}
        if event.type in shortcuts and event.value == "PRESS":
            self.choose_tool(options, shortcuts[event.type])
            return {"RUNNING_MODAL"}
        if event.type not in ("LEFTMOUSE", "MOUSEMOVE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"):
            return {"PASS_THROUGH"}
        try:
            editor = session(context, options, self.target)
            root = root_object(context, options, self.target)
            local_origin, local_direction = self.local_ray(root, region, coord)
            if self._drag:
                self.drag_block(event, options, editor, local_origin, local_direction)
                return {"RUNNING_MODAL"}
            if event.type in ("WHEELUPMOUSE", "WHEELDOWNMOUSE"):
                return {"PASS_THROUGH"}
            hit = editing.ray_pick(
                editor.cells,
                editor.materials,
                editor.limits,
                local_origin,
                local_direction,
                is_glass if options.edit_through_glass else None,
            )
            if hit:
                pos, normal, state = hit
                if options.edit_mode == "ADD":
                    pos = tuple(pos[i] + normal[i] for i in range(3))
            elif options.edit_mode == "ADD" and abs(local_direction[1]) > 1e-8:
                distance = (options.edit_position[1] + 0.5 - local_origin[1]) / local_direction[1]
                if distance < 0:
                    return {"RUNNING_MODAL"}
                pos = tuple(
                    math.floor(local_origin[i] + distance * local_direction[i]) for i in range(3)
                )
            else:
                return {"RUNNING_MODAL"}
            if not all(0 <= v < editor.limits[i] for i, v in enumerate(pos)):
                return {"RUNNING_MODAL"}
            if event.type == "LEFTMOUSE" and event.value == "PRESS":
                # A picked block stays selected while moving to the sidebar.
                options.edit_position = pos
                if options.edit_mode == "SELECT":
                    self.select_corner(context, options, editor, pos)
                elif options.edit_mode == "MOVE":
                    pick(options, editor, pos)
                    self._height = pos[1]
                    self._drag = True
                else:
                    bpy.ops.minecraft_builder.edit_action(
                        target=self.target, action=options.edit_mode
                    )
            self._area.tag_redraw()
        except (ValueError, RuntimeError) as error:
            options.status = str(error)
        return {"RUNNING_MODAL"}


def draw(box, options, target):
    box.label(text="Live block editing", icon="EDITMODE_HLT")
    box.prop(options, "keep_manual_edits")
    if not options.snapshot:
        return
    box.operator("minecraft_builder.edit_start", icon="MESH_CUBE").target = target
    if options.edit_enabled:
        tool = active_view(bpy.context, target)
        box.label(
            text="Viewport tool active" if tool else "Viewport tool stopped",
            icon="PLAY" if tool else "PAUSE",
        )
        row = box.column(align=True)
        for mode, label in (("PICK", "Pick Block"), ("SELECT", "Select Area (2 Clicks)")):
            op = row.operator("minecraft_builder.edit_view", text=label)
            op.target = target
            op.start_mode = mode
        box.operator(
            "minecraft_builder.edit_view",
            text="Start / Resume Current Tool",
            icon="RESTRICT_SELECT_OFF",
        ).target = target
        box.label(text="Pick Block, then click in the 3D view.")
        box.label(text="Esc in the viewport ends the tool.")
        box.prop(options, "edit_mode", text="Tool")
        box.prop(options, "edit_through_glass")
        box.prop(options, "edit_radius")
        box.prop_search(options, "edit_brush", options, "blocks", text="Brush block")
        row = box.row(align=True)
        row.prop(options, "edit_half")
        row.prop(options, "edit_facing")
        box.label(text="Block coordinates (Minecraft Y up)")
        box.prop(options, "edit_position", text="")
        op = box.operator("minecraft_builder.edit_action", text="Select cursor (G to drag)")
        op.action = "CURSOR"
        op.target = target
        # Set target on every shared action, including cursor selection.
        for actions in (
            (("PICK", "Pick at cursor"), ("ADD", "Add here")),
            (("REPLACE", "Repaint"), ("DELETE", "Delete")),
            (("MOVE", "Move picked block here"),),
        ):
            row = box.row(align=True)
            for action, label in actions:
                op = row.operator("minecraft_builder.edit_action", text=label)
                op.action = action
                op.target = target
        box.label(text="Move: drag a picked block.")
        box.label(text="Mouse wheel changes its height.")
        selection = box.box()
        selection.label(text="Box selection and bulk edits")
        selection.label(text="Select Area, then click two corners.")
        selection.label(text="Or enter coordinates below.")
        for suffix in ("a", "b"):
            selection.prop(options, "edit_selection_" + suffix)
            op = selection.operator(
                "minecraft_builder.bulk_edit", text="Use cursor as corner " + suffix.upper()
            )
            op.target = target
            op.action = "CORNER_" + suffix.upper()
        for actions in (
            (("FILL", "Fill box"), ("REPAINT", "Repaint blocks"), ("DELETE", "Delete blocks")),
            (("COPY", "Copy"), ("PASTE", "Paste at cursor"), ("MIRROR", "Mirror in place")),
        ):
            row = selection.row(align=True)
            for action, label in actions:
                op = row.operator("minecraft_builder.bulk_edit", text=label)
                op.target = target
                op.action = action
        selection.prop_search(options, "edit_replace_source", options, "blocks")
        op = selection.operator(
            "minecraft_builder.bulk_edit", text="Replace matching blocks in box"
        )
        op.target = target
        op.action = "REPLACE"
        selection.prop(options, "edit_mirror")
        selection.prop(options, "edit_paste_overwrite")
        selection.prop(options, "edit_paste_air")
    if options.edit_count:
        box.label(text=f"{options.edit_count} saved block edits")
        row = box.row(align=True)
        for action, label in [
            ("UNDO", "Undo edit"),
            ("REDO", "Redo edit"),
            ("CLEAR", "Clear edits"),
        ]:
            op = row.operator("minecraft_builder.edit_action", text=label)
            op.target = target
            op.action = action
    if target == "PERIMETER":
        from .protection_ui import draw as protection_draw

        protection_draw(box, options)


@persistent
def clear_cache(*args):
    _sessions.clear()


class MB_PT_live_edit(bpy.types.Panel):
    bl_label = "Live Block Editor"
    bl_idname = "MB_PT_live_edit"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Minecraft"
    bl_order = -10

    @classmethod
    def poll(cls, context):
        return bool(context.scene.minecraft_builder.snapshot)

    def draw(self, context):
        options = context.scene.minecraft_builder
        box = self.layout.column()
        box.enabled = not options.busy
        draw(box, options, "MODEL")


CLASSES = (MB_OT_edit_start, MB_OT_edit_action, MB_OT_bulk_edit, MB_OT_edit_view, MB_PT_live_edit)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for handlers in (
        bpy.app.handlers.load_post,
        bpy.app.handlers.undo_post,
        bpy.app.handlers.redo_post,
    ):
        handlers.append(clear_cache)


def unregister():
    for tool in list(_view_tools.values()):
        tool.finish()
    for handlers in (
        bpy.app.handlers.load_post,
        bpy.app.handlers.undo_post,
        bpy.app.handlers.redo_post,
    ):
        if clear_cache in handlers:
            handlers.remove(clear_cache)
    clear_cache()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
