import bpy

from . import bridge
from .ops_pathfinder import OPERATIONS


class VIEW3D_PT_illu_draw(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Illustrator"
    bl_label = "Draw"

    def draw(self, context):
        layout = self.layout
        s = context.scene.illu_settings
        col = layout.column(align=True)
        col.scale_y = 1.4
        col.operator("curve.illu_pen", text="Pen Tool", icon="GREASEPENCIL")
        col = layout.column(align=True)
        col.prop(s, "pen_target", text="")
        col.prop(s, "pen_plane", text="")
        layout.prop(s, "pen_fill")

        layout.label(text="Shapes")
        grid = layout.grid_flow(columns=2, align=True, even_columns=True)
        grid.operator("curve.illu_add_rectangle", icon="MESH_PLANE")
        grid.operator("curve.illu_add_ellipse", icon="MESH_CIRCLE")
        grid.operator("curve.illu_add_polygon", icon="SEQ_CHROMA_SCOPE")
        grid.operator("curve.illu_add_star", icon="SOLO_OFF")


class VIEW3D_PT_illu_pathfinder(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Illustrator"
    bl_label = "Pathfinder"

    def draw(self, context):
        layout = self.layout
        n = len(bridge.selected_curves(context))
        act = context.active_object
        grid = layout.grid_flow(columns=2, align=True, even_columns=True)
        for key, label, _desc, icon, _ in OPERATIONS:
            grid.operator("curve.illu_boolean", text=label, icon=icon).operation = key
        box = layout.box()
        box.scale_y = 0.8
        if not bridge.is_curve(act):
            box.label(text="Select curve objects", icon="INFO")
        elif n >= 2:
            box.label(text="Base: %s (+%d)" % (act.name, n - 1), icon="OBJECT_DATA")
        else:
            box.label(text="Combining splines of %s" % act.name, icon="CURVE_DATA")


class VIEW3D_PT_illu_path(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Illustrator"
    bl_label = "Path"

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.operator("curve.illu_offset", icon="MOD_SKIN")
        col.operator("curve.illu_chisel", icon="MOD_BEVEL")
        col.operator("curve.illu_outline_stroke", icon="MOD_OUTLINE")
        col = layout.column(align=True)
        col.operator("curve.illu_fillet", icon="SPHERECURVE").mode = "ROUND"
        col.operator("curve.illu_fillet", text="Chamfer Corners", icon="LINCURVE").mode = "CHAMFER"
        col.operator("curve.illu_simplify", icon="MOD_DECIM")
        col.operator("curve.illu_resample", icon="MOD_LENGTH")
        col.operator("curve.illu_remove_doubles", icon="X")
        if context.mode == "EDIT_CURVE":
            layout.label(text="Edit Mode: selected points only", icon="RESTRICT_SELECT_OFF")


def edit_menu(self, context):
    layout = self.layout
    layout.separator()
    layout.operator("curve.illu_fillet", icon="SPHERECURVE")
    layout.operator("curve.illu_simplify", icon="MOD_DECIM")
    layout.operator("curve.illu_resample", icon="MOD_LENGTH")
    layout.operator("curve.illu_remove_doubles", icon="X")


def object_menu(self, context):
    if not bridge.is_curve(context.active_object):
        return
    layout = self.layout
    layout.separator()
    layout.menu("VIEW3D_MT_illu_pathfinder")
    layout.operator("curve.illu_offset", icon="MOD_SKIN")
    layout.operator("curve.illu_chisel", icon="MOD_BEVEL")
    layout.operator("curve.illu_outline_stroke", icon="MOD_OUTLINE")


class VIEW3D_MT_illu_pathfinder(bpy.types.Menu):
    bl_label = "Pathfinder"

    def draw(self, context):
        for key, label, _desc, icon, _ in OPERATIONS:
            self.layout.operator("curve.illu_boolean", text=label, icon=icon).operation = key


classes = (
    VIEW3D_PT_illu_draw,
    VIEW3D_PT_illu_pathfinder,
    VIEW3D_PT_illu_path,
    VIEW3D_MT_illu_pathfinder,
)
