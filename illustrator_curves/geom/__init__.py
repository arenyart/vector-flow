"""Pure-Python 2D path geometry. Nothing in this package imports ``bpy``."""

from .path import Node, Path, paths_bounds, paths_diagonal, polygon_area  # noqa: F401
from .boolean import boolean  # noqa: F401
from .offset import offset_paths, outline_paths  # noqa: F401
from .fillet import fillet_path  # noqa: F401
from .fit import fit_polyline, simplify_path  # noqa: F401
from .resample import resample_path  # noqa: F401
