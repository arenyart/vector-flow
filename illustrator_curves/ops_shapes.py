import bpy
from bpy.props import EnumProperty, FloatProperty, IntProperty
from bpy_extras import object_utils

from . import bridge
from .geom import shapes

CORNERS = [
    ("ROUND", "Round", ""),
    ("INVERTED", "Inverted Round", ""),
    ("CHAMFER", "Chamfer", ""),
]


class _ShapeMixin(object_utils.AddObjectHelper):
    bl_options = {"REGISTER", "UNDO"}
    shape_name = "Shape"

    def build(self):
        raise NotImplementedError

    def execute(self, context):
        path = self.build()
        path.meta = {"modified": True}
        if context.mode == "EDIT_CURVE" and bridge.is_curve(context.active_object):
            obj = context.active_object
            bpy.ops.object.mode_set(mode="OBJECT")
            local = obj.matrix_world.inverted() @ context.scene.cursor.location
            path = path.transformed(lambda p: (p[0] + local.x, p[1] + local.y))
            for sp in obj.data.splines:
                for bp in sp.bezier_points:
                    bp.select_control_point = bp.select_left_handle = bp.select_right_handle = False
                for p in sp.points:
                    p.select = False
            bridge.write_paths(obj.data, [path], local.z, clear=False, select=True)
            bpy.ops.object.mode_set(mode="EDIT")
            return {"FINISHED"}
        curve = bridge.new_curve_data(self.shape_name)
        bridge.write_paths(curve, [path])
        object_utils.object_data_add(context, curve, operator=self)
        return {"FINISHED"}


class CURVE_OT_illu_add_rectangle(_ShapeMixin, bpy.types.Operator):
    """Add a rectangle, optionally with rounded corners"""

    bl_idname = "curve.illu_add_rectangle"
    bl_label = "Rectangle"
    shape_name = "Rectangle"

    width: FloatProperty(name="Width", default=2.0, min=1e-4, subtype="DISTANCE", unit="LENGTH")
    height: FloatProperty(name="Height", default=1.0, min=1e-4, subtype="DISTANCE", unit="LENGTH")
    corner_radius: FloatProperty(name="Corner Radius", default=0.0, min=0.0, subtype="DISTANCE", unit="LENGTH")
    corner_mode: EnumProperty(name="Corners", items=CORNERS, default="ROUND")

    def build(self):
        return shapes.rectangle(self.width, self.height, self.corner_radius, self.corner_mode)


class CURVE_OT_illu_add_ellipse(_ShapeMixin, bpy.types.Operator):
    """Add an ellipse made of four Bezier segments"""

    bl_idname = "curve.illu_add_ellipse"
    bl_label = "Ellipse"
    shape_name = "Ellipse"

    radius_x: FloatProperty(name="Radius X", default=1.0, min=1e-4, subtype="DISTANCE", unit="LENGTH")
    radius_y: FloatProperty(name="Radius Y", default=1.0, min=1e-4, subtype="DISTANCE", unit="LENGTH")

    def build(self):
        return shapes.ellipse(self.radius_x, self.radius_y)


class CURVE_OT_illu_add_polygon(_ShapeMixin, bpy.types.Operator):
    """Add a regular polygon"""

    bl_idname = "curve.illu_add_polygon"
    bl_label = "Polygon"
    shape_name = "Polygon"

    sides: IntProperty(name="Sides", default=6, min=3, max=256)
    radius: FloatProperty(name="Radius", default=1.0, min=1e-4, subtype="DISTANCE", unit="LENGTH")
    corner_radius: FloatProperty(name="Corner Radius", default=0.0, min=0.0, subtype="DISTANCE", unit="LENGTH")
    corner_mode: EnumProperty(name="Corners", items=CORNERS, default="ROUND")

    def build(self):
        return shapes.polygon(self.sides, self.radius, self.corner_radius, self.corner_mode)


class CURVE_OT_illu_add_star(_ShapeMixin, bpy.types.Operator):
    """Add a star"""

    bl_idname = "curve.illu_add_star"
    bl_label = "Star"
    shape_name = "Star"

    points: IntProperty(name="Points", default=5, min=2, max=256)
    radius_outer: FloatProperty(name="Outer Radius", default=1.0, min=1e-4, subtype="DISTANCE", unit="LENGTH")
    radius_inner: FloatProperty(name="Inner Radius", default=0.45, min=1e-4, subtype="DISTANCE", unit="LENGTH")
    corner_radius: FloatProperty(name="Corner Radius", default=0.0, min=0.0, subtype="DISTANCE", unit="LENGTH")
    corner_mode: EnumProperty(name="Corners", items=CORNERS, default="ROUND")

    def build(self):
        return shapes.star(self.points, self.radius_outer, self.radius_inner, self.corner_radius, self.corner_mode)


classes = (
    CURVE_OT_illu_add_rectangle,
    CURVE_OT_illu_add_ellipse,
    CURVE_OT_illu_add_polygon,
    CURVE_OT_illu_add_star,
)


def menu_func(self, context):
    layout = self.layout
    layout.separator()
    layout.label(text="Illustrator Shapes")
    layout.operator(CURVE_OT_illu_add_rectangle.bl_idname, icon="MESH_PLANE")
    layout.operator(CURVE_OT_illu_add_ellipse.bl_idname, icon="MESH_CIRCLE")
    layout.operator(CURVE_OT_illu_add_polygon.bl_idname, icon="SEQ_CHROMA_SCOPE")
    layout.operator(CURVE_OT_illu_add_star.bl_idname, icon="SOLO_OFF")
