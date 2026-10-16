import bpy
from bpy.props import BoolProperty, EnumProperty


class IlluSettings(bpy.types.PropertyGroup):
    pen_plane: EnumProperty(
        name="Plane",
        description="Plane new paths are drawn on",
        items=[
            ("AUTO", "Auto", "Active curve's plane, the view plane in axis-aligned ortho views, otherwise ground (XY)"),
            ("XY", "Top (XY)", "Ground plane through the 3D cursor"),
            ("XZ", "Front (XZ)", "Front plane through the 3D cursor"),
            ("YZ", "Side (YZ)", "Side plane through the 3D cursor"),
            ("VIEW", "View", "Plane facing the viewport through the 3D cursor"),
            ("CURSOR", "3D Cursor", "XY plane of the 3D cursor's rotation"),
        ],
        default="AUTO",
    )
    pen_target: EnumProperty(
        name="Target",
        description="Where finished paths go",
        items=[
            ("NEW", "New Object", "Every finished path becomes its own object (best for Pathfinder)"),
            ("ACTIVE", "Active Curve", "Add paths as splines of the active curve object"),
        ],
        default="NEW",
    )
    pen_fill: BoolProperty(name="Fill New Paths", default=True,
                           description="New curve objects are 2D with filled faces")


classes = (IlluSettings,)


def register_props():
    bpy.types.Scene.illu_settings = bpy.props.PointerProperty(type=IlluSettings)


def unregister_props():
    del bpy.types.Scene.illu_settings
