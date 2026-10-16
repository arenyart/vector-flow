import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty

from . import bridge
from .geom.boolean import boolean

OPERATIONS = [
    ("UNION", "Unite", "Merge all shapes into one outline", "SELECT_EXTEND", 0),
    ("DIFFERENCE", "Minus Front", "Subtract the other shapes from the active one", "SELECT_SUBTRACT", 1),
    ("INTERSECT", "Intersect", "Keep only the area shared by all shapes", "SELECT_INTERSECT", 2),
    ("EXCLUDE", "Exclude", "Keep areas covered by an odd number of shapes", "SELECT_DIFFERENCE", 3),
]
_LABELS = {k: label for k, label, *_ in OPERATIONS}


class CURVE_OT_illu_boolean(bpy.types.Operator):
    """Combine curve shapes like Illustrator's Pathfinder. With several objects selected the active
    object is the base; with a single object its splines are combined"""

    bl_idname = "curve.illu_boolean"
    bl_label = "Pathfinder"
    bl_options = {"REGISTER", "UNDO"}

    operation: EnumProperty(name="Operation", items=OPERATIONS, default="UNION")
    keep_originals: BoolProperty(name="Keep Originals", default=False,
                                 description="Keep the source objects instead of replacing them")
    precision: FloatProperty(name="Precision", default=2e-4, min=1e-6, max=1e-2, precision=5, step=0.001,
                             description="Intersection accuracy relative to the size of the shapes")

    @classmethod
    def description(cls, context, props):
        for key, label, desc, *_ in OPERATIONS:
            if props.operation == key:
                return "%s: %s" % (label, desc)
        return cls.__doc__

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bridge.is_curve(obj) and context.mode in {"OBJECT", "EDIT_CURVE"}

    def execute(self, context):
        prev = bridge.ensure_object_mode(context)
        active = context.active_object
        others = [o for o in bridge.selected_curves(context) if o is not active]
        inv = active.matrix_world.inverted()

        base, z, planar = bridge.read_paths(active)
        if others:
            groups = [base]
            for o in others:
                paths, _, ok = bridge.read_paths(o, inv @ o.matrix_world)
                planar = planar and ok
                groups.append(paths)
        else:
            groups = [[p] for p in base]
        groups = [g for g in groups if g]
        if len(groups) < 2:
            bridge.restore_mode(prev)
            self.report({"ERROR"}, "Select at least two curve objects, or one object with several splines")
            return {"CANCELLED"}
        if not planar:
            self.report({"WARNING"}, "Shapes are not coplanar; they were projected onto the active object's XY plane")

        tol = bridge.tolerance([p for g in groups for p in g], self.precision)
        result = boolean(groups, self.operation, tol)
        label = _LABELS[self.operation]
        if not result:
            bridge.restore_mode(prev)
            self.report({"WARNING"}, "%s produced an empty shape; nothing changed" % label)
            return {"CANCELLED"}

        for p in result:
            p.meta = {"material_index": base[0].meta.get("material_index", 0) if base else 0}
        obj = bridge.new_object_like(context, active, "%s.%s" % (active.name, label.replace(" ", "")))
        bridge.write_paths(obj.data, result, z)
        if not self.keep_originals:
            bridge.remove_objects([active] + others)
        bridge.make_active(context, obj)
        bridge.restore_mode(prev)
        self.report({"INFO"}, "%s: %d path(s)" % (label, len(result)))
        return {"FINISHED"}


classes = (CURVE_OT_illu_boolean,)
