"""Build a demo scene with every tool: blender --python examples/showcase.py"""

import os
import sys

import bpy
from mathutils import Quaternion

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

if not hasattr(bpy.ops.curve, "illu_boolean") or "illu_settings" not in dir(bpy.types.Scene):
    import illustrator_curves

    illustrator_curves.register()

PALETTE = [
    (0.98, 0.45, 0.30, 1), (0.25, 0.60, 0.95, 1), (0.98, 0.78, 0.25, 1),
    (0.45, 0.80, 0.50, 1), (0.70, 0.45, 0.90, 1), (0.95, 0.55, 0.75, 1),
]


def only(*objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


def at(x, y):
    bpy.context.scene.cursor.location = (x, y, 0)


def color(obj, i):
    obj.color = PALETTE[i % len(PALETTE)]
    return obj


def label(text, x, y, size=0.32):
    curve = bpy.data.curves.new(text, "FONT")
    curve.body = text
    curve.size = size
    curve.align_x = "CENTER"
    obj = bpy.data.objects.new(text, curve)
    obj.location = (x, y, 0)
    obj.color = (0.85, 0.85, 0.85, 1)
    bpy.context.collection.objects.link(obj)


def build():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)

    # Pathfinder row
    for i, (op, name) in enumerate([("UNION", "Unite"), ("DIFFERENCE", "Minus Front"),
                                    ("INTERSECT", "Intersect"), ("EXCLUDE", "Exclude")]):
        x = i * 3.2
        at(x - 0.35, 3.0)
        bpy.ops.curve.illu_add_rectangle(width=1.6, height=1.6, corner_radius=0.2)
        a = bpy.context.active_object
        at(x + 0.45, 3.4)
        bpy.ops.curve.illu_add_ellipse(radius_x=0.85, radius_y=0.85)
        b = bpy.context.active_object
        only(a, b)
        bpy.ops.curve.illu_boolean(operation=op)
        color(bpy.context.active_object, i)
        label(name, x, 1.6)

    # Offset / outline row
    at(0, -1)
    bpy.ops.curve.illu_add_star(points=5, radius_outer=1, radius_inner=0.45)
    star = color(bpy.context.active_object, 2)
    only(star)
    bpy.ops.curve.illu_offset(distance=0.18, join="ROUND")
    outer = color(bpy.context.active_object, 0)
    outer.location.z = -0.01
    label("Offset Path", 0, -2.6)

    curve = bpy.data.curves.new("Wave", "CURVE")
    curve.dimensions = "2D"
    sp = curve.splines.new("BEZIER")
    sp.bezier_points.add(3)
    for k, bp in enumerate(sp.bezier_points):
        bp.co = (-1.2 + k * 0.8, -1 + (0.5 if k % 2 else -0.5), 0)
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    wave = bpy.data.objects.new("Wave", curve)
    wave.location = (3.2, 0, 0)
    bpy.context.collection.objects.link(wave)
    only(wave)
    bpy.ops.curve.illu_outline_stroke(width=0.25, cap="ROUND", join="ROUND", keep_original=False)
    color(bpy.context.active_object, 1)
    label("Outline Stroke", 3.2, -2.6)

    at(6.4, -1)
    bpy.ops.curve.illu_add_polygon(sides=6, radius=1)
    hexa = color(bpy.context.active_object, 3)
    only(hexa)
    bpy.ops.curve.illu_fillet(radius=0.3, mode="ROUND")
    label("Round Corners", 6.4, -2.6)

    at(9.6, -1)
    bpy.ops.curve.illu_add_rectangle(width=1.8, height=1.8)
    rect = color(bpy.context.active_object, 4)
    only(rect)
    bpy.ops.curve.illu_fillet(radius=0.45, mode="INVERTED")
    label("Inverted Round", 9.6, -2.6)

    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            space = area.spaces.active
            space.shading.color_type = "OBJECT"
            space.overlay.show_floor = False
            space.overlay.show_axis_x = False
            space.overlay.show_axis_y = False
            space.show_region_ui = True
            r3d = space.region_3d
            r3d.view_perspective = "ORTHO"
            r3d.view_rotation = Quaternion((1, 0, 0, 0))
            r3d.view_location = (5.6, 0.4, 0)
            r3d.view_distance = 11
            for region in area.regions:
                if region.type == "UI":
                    try:
                        region.active_panel_category = "Illustrator"
                    except Exception:
                        pass
    bpy.ops.object.select_all(action="DESELECT")
    at(0, 0)
    return None


if bpy.app.background:
    build()
else:
    bpy.app.timers.register(build, first_interval=0.5)
