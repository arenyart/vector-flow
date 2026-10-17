bl_info = {
    "name": "Illustrator Curves",
    "author": "Illustrator Curves contributors",
    "version": (1, 2, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Illustrator, Toolbar > Pen, Add > Curve",
    "description": "Pen tool, Pathfinder booleans, offset path, outline stroke, round corners, simplify, resample and remove doubles for curves",
    "category": "Add Curve",
}

try:
    import bpy
except ImportError:  # imported outside Blender, e.g. to use or test the geom package
    bpy = None

if bpy is not None:
    if "ops_pen" in locals():
        import importlib

        for _m in (geom, bridge, settings, ops_pathfinder, ops_path, ops_shapes, ops_pen, ui):  # noqa: F821
            importlib.reload(_m)

    from . import geom, bridge, settings, ops_pathfinder, ops_path, ops_shapes, ops_pen, ui  # noqa: F401

    _modules = (settings, ops_pathfinder, ops_path, ops_shapes, ops_pen, ui)


def register():
    for m in _modules:
        for cls in m.classes:
            bpy.utils.register_class(cls)
    settings.register_props()
    bpy.types.VIEW3D_MT_curve_add.append(ops_shapes.menu_func)
    bpy.types.VIEW3D_MT_edit_curve_context_menu.append(ui.edit_menu)
    bpy.types.VIEW3D_MT_object_context_menu.append(ui.object_menu)
    try:
        bpy.utils.register_tool(ops_pen.IlluPenTool, after={"builtin.transform"}, separator=True, group=False)
    except Exception as exc:  # toolbar may be unavailable (e.g. background mode)
        print("Illustrator Curves: pen tool not added to toolbar:", exc)


def unregister():
    try:
        bpy.utils.unregister_tool(ops_pen.IlluPenTool)
    except Exception:
        pass
    bpy.types.VIEW3D_MT_object_context_menu.remove(ui.object_menu)
    bpy.types.VIEW3D_MT_edit_curve_context_menu.remove(ui.edit_menu)
    bpy.types.VIEW3D_MT_curve_add.remove(ops_shapes.menu_func)
    settings.unregister_props()
    for m in reversed(_modules):
        for cls in reversed(m.classes):
            bpy.utils.unregister_class(cls)
