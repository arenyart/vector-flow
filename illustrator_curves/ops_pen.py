"""Illustrator-style Pen tool for the 3D viewport."""

import math

import bpy
import gpu
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector
from mathutils.geometry import intersect_line_plane

from . import bridge
from .geom import bezier as bz
from .geom.path import Path
from .geom.pen import PenState, constrain_45

CLOSE_RADIUS_PX = 10.0
NAV_EVENTS = {
    "MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "WHEELINMOUSE", "WHEELOUTMOUSE",
    "TRACKPADPAN", "TRACKPADZOOM", "MOUSEROTATE", "MOUSESMARTZOOM", "NDOF_MOTION",
}

COL_PATH = (0.13, 0.55, 1.0, 1.0)
COL_PREVIEW = (0.13, 0.55, 1.0, 0.55)
COL_HANDLE = (0.85, 0.85, 0.85, 0.9)
COL_NODE = (1.0, 1.0, 1.0, 1.0)
COL_CLOSE = (1.0, 0.75, 0.1, 1.0)

STATUS = ("Click: corner point   Drag: smooth point   Alt-drag: break handle   Shift: 45°   "
          "Click first point: close   Backspace: undo point   Enter: finish path   Esc / Right-click: exit")


def _window_region(area):
    for r in area.regions:
        if r.type == "WINDOW":
            return r
    return None


def plane_matrix(context, rv3d, mode):
    cursor = context.scene.cursor
    if mode == "AUTO":
        mode = "VIEW" if (rv3d.view_perspective == "ORTHO" and rv3d.is_orthographic_side_view) else "XY"
    if mode == "XZ":
        rot = Matrix.Rotation(math.radians(90.0), 3, "X")
    elif mode == "YZ":
        rot = Matrix(((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)))
    elif mode == "VIEW":
        rot = rv3d.view_rotation.to_matrix()
    elif mode == "CURSOR":
        rot = cursor.matrix.to_3x3().normalized()
    else:
        rot = Matrix.Identity(3)
    return Matrix.Translation(cursor.location) @ rot.to_4x4()


class CURVE_OT_illu_pen(bpy.types.Operator):
    """Draw Bezier paths like Illustrator's Pen tool: click for corners, drag for smooth points"""

    bl_idname = "curve.illu_pen"
    bl_label = "Pen Tool"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D" and context.mode in {"OBJECT", "EDIT_CURVE"}

    # ---------------------------------------------------------------- setup
    def invoke(self, context, event):
        self.area = context.area
        self.region = _window_region(context.area)
        if self.region is None:
            return {"CANCELLED"}
        self.rv3d = self.region.data
        settings = context.scene.illu_settings
        self.settings = settings
        self.prev_mode = context.mode
        active = context.active_object
        if self.prev_mode == "EDIT_CURVE":
            bpy.ops.object.mode_set(mode="OBJECT")

        use_active = bridge.is_curve(active) and (settings.pen_target == "ACTIVE" or self.prev_mode == "EDIT_CURVE")
        if use_active:
            self.target = active
            self.matrix = active.matrix_world.copy()
        else:
            self.target = None
            self.matrix = plane_matrix(context, self.rv3d, settings.pen_plane)
        self.matrix_inv = self.matrix.inverted_safe()

        self.state = PenState()
        self.cursor = None
        self.hover_close = False
        self.committed = 0
        self.drag_origin = None

        self._handle = bpy.types.SpaceView3D.draw_handler_add(self._draw, (), "WINDOW", "POST_PIXEL")
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(STATUS)
        self.area.header_text_set("Pen Tool")

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            mx, my, inside = self._mouse(event)
            if inside:
                self._press(context, event, mx, my)
        return {"RUNNING_MODAL"}

    def _cleanup(self, context):
        if getattr(self, "_handle", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
            self._handle = None
        context.workspace.status_text_set(None)
        self.area.header_text_set(None)
        self.area.tag_redraw()
        if self.prev_mode == "EDIT_CURVE" and bridge.is_curve(context.active_object):
            bpy.ops.object.mode_set(mode="EDIT")

    # ---------------------------------------------------------------- input
    def _mouse(self, event):
        r = self.region
        mx, my = event.mouse_x - r.x, event.mouse_y - r.y
        return mx, my, (0 <= mx < r.width and 0 <= my < r.height)

    def _to_plane(self, mx, my):
        origin = view3d_utils.region_2d_to_origin_3d(self.region, self.rv3d, (mx, my))
        direction = view3d_utils.region_2d_to_vector_3d(self.region, self.rv3d, (mx, my))
        normal = (self.matrix.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
        if abs(direction.normalized().dot(normal)) < 1e-4:
            return None
        hit = intersect_line_plane(origin, origin + direction, self.matrix.translation, normal)
        if hit is None:
            return None
        local = self.matrix_inv @ hit
        return (local.x, local.y)

    def _to_screen(self, p):
        world = self.matrix @ Vector((p[0], p[1], 0.0))
        return view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, world)

    def _near_first(self, mx, my):
        if len(self.state) < 2:
            return False
        s = self._to_screen(self.state.nodes[0].co)
        return s is not None and math.hypot(s.x - mx, s.y - my) <= CLOSE_RADIUS_PX

    def _press(self, context, event, mx, my):
        if self._near_first(mx, my):
            self._commit(context, closed=True)
            return
        p = self._to_plane(mx, my)
        if p is None:
            return
        if event.shift and len(self.state):
            p = constrain_45(self.state.nodes[-1].co, p)
        self.state.add(p)
        self.drag_origin = p

    def modal(self, context, event):
        self.area.tag_redraw()
        if event.type in NAV_EVENTS or event.type.startswith("NDOF") or (
                event.type.startswith("NUMPAD_") and event.type != "NUMPAD_ENTER"):
            return {"PASS_THROUGH"}

        mx, my, inside = self._mouse(event)

        if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            p = self._to_plane(mx, my) if inside else None
            self.hover_close = inside and not self.state.dragging and self._near_first(mx, my)
            if p is not None:
                if self.state.dragging:
                    node = self.state.nodes[-1].co
                    if event.shift:
                        p = constrain_45(node, p)
                    self.state.drag(p, cusp=event.alt)
                    self.cursor = None
                else:
                    if event.shift and len(self.state):
                        p = constrain_45(self.state.nodes[-1].co, p)
                    self.cursor = p
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE":
            if not inside and not self.state.dragging:
                return {"PASS_THROUGH"}
            if event.value == "PRESS":
                self._press(context, event, mx, my)
            elif event.value == "RELEASE":
                self.state.release()
            return {"RUNNING_MODAL"}

        if event.value != "PRESS":
            return {"RUNNING_MODAL"}

        if event.type in {"BACK_SPACE", "DEL"}:
            self.state.pop()
        elif event.type in {"RET", "NUMPAD_ENTER", "SPACE"}:
            self._commit(context, closed=False)
        elif event.type == "C" and len(self.state) >= 2:
            self._commit(context, closed=True)
        elif event.type in {"ESC", "RIGHTMOUSE"}:
            self._commit(context, closed=False)
            self._cleanup(context)
            return {"FINISHED"} if self.committed else {"CANCELLED"}
        return {"RUNNING_MODAL"}

    # ---------------------------------------------------------------- output
    def _target_object(self, context):
        if self.target is not None and self.target.name in bpy.data.objects:
            return self.target
        curve = bridge.new_curve_data("Path")
        if not self.settings.pen_fill:
            curve.fill_mode = "NONE"
        obj = bpy.data.objects.new("Path", curve)
        obj.matrix_world = self.matrix
        context.collection.objects.link(obj)
        bridge.make_active(context, obj)
        return obj

    def _commit(self, context, closed):
        if len(self.state) < 2:
            self.state.reset()
            return
        path = Path(self.state.resolved(closed), closed, {"modified": True})
        obj = self._target_object(context)
        bridge.write_paths(obj.data, [path], 0.0, clear=False)
        self.committed += 1
        self.state.reset()
        self.hover_close = False

    # ---------------------------------------------------------------- drawing
    def _draw(self):
        if bpy.context.region is None or bpy.context.region.as_pointer() != self.region.as_pointer():
            return
        state = self.state
        if not len(state) and self.cursor is None:
            return
        closing = self.hover_close
        preview = self.cursor if (not state.dragging and not closing and len(state)) else None
        nodes = state.resolved(closed=closing, cursor=preview)
        k = len(nodes)

        lines_done, lines_preview = [], []
        segs = []
        for i in range(k - 1):
            segs.append(((nodes[i].co, nodes[i].hr, nodes[i + 1].hl, nodes[i + 1].co), preview is not None and i == k - 2))
        if closing and k >= 2:
            segs.append(((nodes[-1].co, nodes[-1].hr, nodes[0].hl, nodes[0].co), True))
        for seg, is_preview in segs:
            pts = [self._to_screen(bz.point(seg, t / 32.0)) for t in range(33)]
            target = lines_preview if is_preview else lines_done
            for a, b in zip(pts, pts[1:]):
                if a is not None and b is not None:
                    target.extend(((a.x, a.y, 0.0), (b.x, b.y, 0.0)))

        handle_lines, handle_pts, node_pts = [], [], []
        real = nodes[:len(state)]
        for i, n in enumerate(real):
            s = self._to_screen(n.co)
            if s is None:
                continue
            node_pts.append((s, COL_CLOSE if (i == 0 and closing) else COL_NODE, 4.0 if i else 5.0))
            if i >= len(real) - 2:
                for h, t in ((n.hl, n.hl_type), (n.hr, n.hr_type)):
                    if t in {"ALIGNED", "FREE"}:
                        hs = self._to_screen(h)
                        if hs is not None:
                            handle_lines.extend(((s.x, s.y, 0.0), (hs.x, hs.y, 0.0)))
                            handle_pts.append(hs)

        gpu.state.blend_set("ALPHA")
        line_shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
        line_shader.bind()
        line_shader.uniform_float("viewportSize", (self.region.width, self.region.height))
        for coords, color, width in ((lines_done, COL_PATH, 2.0), (lines_preview, COL_PREVIEW, 1.5),
                                     (handle_lines, COL_HANDLE, 1.0)):
            if coords:
                line_shader.uniform_float("lineWidth", width)
                line_shader.uniform_float("color", color)
                batch_for_shader(line_shader, "LINES", {"pos": coords}).draw(line_shader)

        flat = gpu.shader.from_builtin("UNIFORM_COLOR")
        flat.bind()

        def quads(points, size):
            tris = []
            for p in points:
                x, y = p.x, p.y
                a, b, c, d = (x - size, y - size, 0), (x + size, y - size, 0), (x + size, y + size, 0), (x - size, y + size, 0)
                tris.extend((a, b, c, a, c, d))
            return tris

        if handle_pts:
            flat.uniform_float("color", COL_HANDLE)
            batch_for_shader(flat, "TRIS", {"pos": quads(handle_pts, 2.5)}).draw(flat)
        for s, color, size in node_pts:
            flat.uniform_float("color", COL_PATH)
            batch_for_shader(flat, "TRIS", {"pos": quads([s], size + 1.0)}).draw(flat)
            flat.uniform_float("color", color)
            batch_for_shader(flat, "TRIS", {"pos": quads([s], size - 0.5)}).draw(flat)
        gpu.state.blend_set("NONE")


class IlluPenTool(bpy.types.WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_idname = "illustrator_curves.pen"
    bl_label = "Pen"
    bl_description = "Draw Bezier paths: click for corners, drag for smooth points, click the first point to close"
    bl_icon = "ops.curve.draw"
    bl_widget = None
    bl_keymap = (
        (CURVE_OT_illu_pen.bl_idname, {"type": "LEFTMOUSE", "value": "PRESS"}, None),
    )

    def draw_settings(context, layout, tool):
        s = context.scene.illu_settings
        layout.prop(s, "pen_target", text="")
        layout.prop(s, "pen_plane", text="")
        layout.prop(s, "pen_fill")


classes = (CURVE_OT_illu_pen,)
