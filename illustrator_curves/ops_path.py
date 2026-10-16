import math

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty

from . import bridge
from .geom.fillet import fillet_path
from .geom.fit import simplify_path
from .geom.offset import offset_paths, outline_paths
from .geom.resample import resample_path

JOINS = [
    ("MITER", "Miter", "Sharp corners, falling back to bevel past the miter limit"),
    ("ROUND", "Round", "Rounded corners"),
    ("BEVEL", "Bevel", "Corners cut off flat"),
]
CAPS = [
    ("BUTT", "Butt", "Stroke stops exactly at the end points"),
    ("ROUND", "Round", "Semicircular ends"),
    ("SQUARE", "Projecting", "Square ends extending half the width past the end points"),
]


def _poll_curves(context):
    return any(bridge.is_curve(o) for o in context.selected_objects) or bridge.is_curve(context.active_object)


def _targets(context):
    objs = bridge.selected_curves(context)
    act = context.active_object
    if bridge.is_curve(act) and act not in objs:
        objs.append(act)
    return objs


def _select_results(context, objs):
    for o in context.selected_objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    context.view_layer.objects.active = objs[-1]


def _mark_modified(paths):
    for p in paths:
        p.meta = dict(p.meta)
        p.meta["modified"] = True
    return paths


class _ResultMixin:
    keep_original: BoolProperty(name="Keep Original", default=True,
                                description="Add the result as a new object and keep the source")
    precision: FloatProperty(name="Precision", default=5e-4, min=1e-5, max=2e-2, precision=5, step=0.001,
                             description="Approximation accuracy relative to the size of the shape")

    def _emit(self, context, src, result, z, suffix):
        if self.keep_original:
            obj = bridge.new_object_like(context, src, "%s.%s" % (src.name, suffix))
            bridge.write_paths(obj.data, result, z)
            return obj
        bridge.write_paths(src.data, result, z)
        return src


class CURVE_OT_illu_offset(_ResultMixin, bpy.types.Operator):
    """Offset Path: grow or shrink shapes by a fixed distance"""

    bl_idname = "curve.illu_offset"
    bl_label = "Offset Path"
    bl_options = {"REGISTER", "UNDO"}

    distance: FloatProperty(name="Offset", default=0.1, soft_min=-10, soft_max=10, subtype="DISTANCE",
                            unit="LENGTH", description="Positive grows the shape, negative shrinks it")
    join: EnumProperty(name="Joins", items=JOINS, default="MITER")
    miter_limit: FloatProperty(name="Miter Limit", default=4.0, min=1.0, max=100.0)

    @classmethod
    def poll(cls, context):
        return _poll_curves(context)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "distance")
        layout.prop(self, "join")
        if self.join == "MITER":
            layout.prop(self, "miter_limit")
        layout.prop(self, "keep_original")
        layout.prop(self, "precision")

    def execute(self, context):
        prev = bridge.ensure_object_mode(context)
        made = []
        for obj in _targets(context):
            paths, z, _ = bridge.read_paths(obj)
            if not paths:
                continue
            tol = bridge.tolerance(paths, self.precision)
            res = offset_paths(paths, self.distance, self.join, self.miter_limit, tol)
            if not res:
                self.report({"WARNING"}, "%s: offset collapsed the shape" % obj.name)
                continue
            made.append(self._emit(context, obj, res, z, "Offset"))
        bridge.restore_mode(prev)
        if not made:
            return {"CANCELLED"}
        _select_results(context, made)
        return {"FINISHED"}


class CURVE_OT_illu_outline_stroke(_ResultMixin, bpy.types.Operator):
    """Outline Stroke: turn paths into filled outlines of the given stroke width"""

    bl_idname = "curve.illu_outline_stroke"
    bl_label = "Outline Stroke"
    bl_options = {"REGISTER", "UNDO"}

    width: FloatProperty(name="Width", default=0.05, min=0.0, soft_max=5.0, subtype="DISTANCE", unit="LENGTH")
    join: EnumProperty(name="Joins", items=JOINS, default="ROUND")
    cap: EnumProperty(name="Caps", items=CAPS, default="BUTT")
    miter_limit: FloatProperty(name="Miter Limit", default=4.0, min=1.0, max=100.0)
    use_bevel_depth: BoolProperty(name="Use Curve Bevel", default=False,
                                  description="Use twice the curve's bevel depth as the width when it is set")

    @classmethod
    def poll(cls, context):
        return _poll_curves(context)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "use_bevel_depth")
        row = layout.row()
        row.active = not self.use_bevel_depth
        row.prop(self, "width")
        layout.prop(self, "join")
        if self.join == "MITER":
            layout.prop(self, "miter_limit")
        layout.prop(self, "cap")
        layout.prop(self, "keep_original")
        layout.prop(self, "precision")

    def execute(self, context):
        prev = bridge.ensure_object_mode(context)
        made = []
        for obj in _targets(context):
            paths, z, _ = bridge.read_paths(obj)
            if not paths:
                continue
            width = self.width
            if self.use_bevel_depth and obj.data.bevel_depth > 0:
                width = obj.data.bevel_depth * 2.0
            tol = bridge.tolerance(paths, self.precision)
            res = outline_paths(paths, width, self.join, self.cap, self.miter_limit, tol)
            if not res:
                continue
            out = self._emit(context, obj, res, z, "Outline")
            if out.data.bevel_depth and (self.use_bevel_depth or not self.keep_original):
                out.data.bevel_depth = 0.0
            out.data.dimensions = "2D"
            if out.data.fill_mode not in {"BOTH", "FRONT", "BACK"}:
                out.data.fill_mode = "BOTH"
            made.append(out)
        bridge.restore_mode(prev)
        if not made:
            self.report({"WARNING"}, "Nothing to outline")
            return {"CANCELLED"}
        _select_results(context, made)
        return {"FINISHED"}


class CURVE_OT_illu_fillet(bpy.types.Operator):
    """Round, chamfer or scoop corners. In Edit Mode only selected points are affected"""

    bl_idname = "curve.illu_fillet"
    bl_label = "Round Corners"
    bl_options = {"REGISTER", "UNDO"}

    radius: FloatProperty(name="Radius", default=0.1, min=0.0, soft_max=5.0, subtype="DISTANCE", unit="LENGTH")
    mode: EnumProperty(name="Corner", items=[
        ("ROUND", "Round", "Circular arc tangent to both sides"),
        ("INVERTED", "Inverted Round", "Concave arc centred on the corner"),
        ("CHAMFER", "Chamfer", "Straight cut"),
    ], default="ROUND")
    min_angle: FloatProperty(name="Corner Threshold", default=math.radians(5.0), min=0.0, max=math.radians(179.0),
                             subtype="ANGLE", description="Points that bend less than this are left alone")

    @classmethod
    def poll(cls, context):
        return _poll_curves(context) and context.mode in {"OBJECT", "EDIT_CURVE"}

    def execute(self, context):
        prev = bridge.ensure_object_mode(context)
        edit = prev == "EDIT_CURVE"
        objs = [context.active_object] if edit else _targets(context)
        total = 0
        for obj in objs:
            paths, z, _ = bridge.read_paths(obj)
            out = []
            changed = False
            for p in paths:
                if edit and not any(n.selected for n in p.nodes):
                    out.append(p)
                    continue
                q = fillet_path(p, self.radius, self.mode, selected_only=edit, min_angle=self.min_angle)
                if len(q.nodes) != len(p.nodes):
                    changed = True
                    total += len(q.nodes) - len(p.nodes)
                    _mark_modified([q])
                    out.append(q)
                else:
                    out.append(p)
            if changed:
                bridge.write_paths(obj.data, out, z)
        bridge.restore_mode(prev)
        if not total:
            self.report({"INFO"}, "No corners found" + (" among the selected points" if edit else ""))
        return {"FINISHED"}


class CURVE_OT_illu_simplify(bpy.types.Operator):
    """Simplify: refit paths with fewer points while keeping sharp corners. In Edit Mode only splines with selected points are affected"""

    bl_idname = "curve.illu_simplify"
    bl_label = "Simplify Path"
    bl_options = {"REGISTER", "UNDO"}

    tolerance: FloatProperty(name="Tolerance", default=2e-3, min=1e-5, max=0.1, precision=4, step=0.01,
                             description="Maximum deviation relative to the size of the shape")
    corner_angle: FloatProperty(name="Corner Angle", default=math.radians(40.0), min=math.radians(1.0),
                                max=math.radians(179.0), subtype="ANGLE",
                                description="Bends sharper than this stay as corners")

    @classmethod
    def poll(cls, context):
        return _poll_curves(context) and context.mode in {"OBJECT", "EDIT_CURVE"}

    def execute(self, context):
        prev = bridge.ensure_object_mode(context)
        edit = prev == "EDIT_CURVE"
        objs = [context.active_object] if edit else _targets(context)
        before = after = 0
        for obj in objs:
            paths, z, _ = bridge.read_paths(obj)
            err = bridge.tolerance(paths, self.tolerance)
            out = []
            for p in paths:
                if edit and not any(n.selected for n in p.nodes):
                    out.append(p)
                    continue
                q = simplify_path(p, err, self.corner_angle)
                before += len(p.nodes)
                after += len(q.nodes)
                out.append(_mark_modified([q])[0])
            bridge.write_paths(obj.data, out, z)
        bridge.restore_mode(prev)
        self.report({"INFO"}, "Simplify: %d → %d points" % (before, after))
        return {"FINISHED"}


class CURVE_OT_illu_resample(bpy.types.Operator):
    """Resample: redistribute points evenly along each path. In Edit Mode only splines with selected points are affected"""

    bl_idname = "curve.illu_resample"
    bl_label = "Resample Path"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(name="Mode", items=[
        ("COUNT", "Count", "Use this many points, spaced evenly by length"),
        ("LENGTH", "Length", "Place a point about every given distance"),
    ], default="COUNT")
    count: IntProperty(name="Points", default=16, min=2, max=10000,
                       description="Number of points on each path")
    spacing: FloatProperty(name="Spacing", default=0.1, min=1e-5, soft_max=10.0, subtype="DISTANCE",
                           unit="LENGTH", description="Target distance between points")
    smooth: BoolProperty(name="Smooth", default=True,
                         description="Fit a smooth curve through the new points. Off keeps straight segments")
    keep_corners: BoolProperty(name="Keep Corners", default=True,
                               description="Leave sharp corners where they are and resample the spans between them")
    corner_angle: FloatProperty(name="Corner Angle", default=math.radians(35.0), min=math.radians(1.0),
                                max=math.radians(179.0), subtype="ANGLE",
                                description="Bends sharper than this stay put")

    @classmethod
    def poll(cls, context):
        return _poll_curves(context) and context.mode in {"OBJECT", "EDIT_CURVE"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "mode")
        if self.mode == "COUNT":
            layout.prop(self, "count")
        else:
            layout.prop(self, "spacing")
        layout.prop(self, "smooth")
        layout.prop(self, "keep_corners")
        if self.keep_corners:
            layout.prop(self, "corner_angle")

    def execute(self, context):
        prev = bridge.ensure_object_mode(context)
        edit = prev == "EDIT_CURVE"
        objs = [context.active_object] if edit else _targets(context)
        before = after = 0
        for obj in objs:
            paths, z, _ = bridge.read_paths(obj)
            out = []
            for p in paths:
                if edit and not any(n.selected for n in p.nodes):
                    out.append(p)
                    continue
                before += len(p.nodes)
                if self.mode == "COUNT":
                    q = resample_path(p, count=self.count, smooth=self.smooth,
                                      keep_corners=self.keep_corners, corner_angle=self.corner_angle)
                else:
                    q = resample_path(p, spacing=self.spacing, smooth=self.smooth,
                                      keep_corners=self.keep_corners, corner_angle=self.corner_angle)
                after += len(q.nodes)
                out.append(_mark_modified([q])[0])
            bridge.write_paths(obj.data, out, z)
        bridge.restore_mode(prev)
        self.report({"INFO"}, "Resample: %d → %d points" % (before, after))
        return {"FINISHED"}


classes = (
    CURVE_OT_illu_offset,
    CURVE_OT_illu_outline_stroke,
    CURVE_OT_illu_fillet,
    CURVE_OT_illu_simplify,
    CURVE_OT_illu_resample,
)
