"""
Tool modules, one per domain.

Importing this package runs the @tool decorators and fills the registry.
Add a module here when its part is implemented.
"""

from . import connection  # noqa: F401
from . import routing  # noqa: F401
from . import routing_create  # noqa: F401
from . import routing_components  # noqa: F401
from . import routing_measure  # noqa: F401
from . import routing_edit  # noqa: F401
from . import routing_articles  # noqa: F401
from . import routing_library  # noqa: F401
from . import routing_settings  # noqa: F401
from . import routing_path  # noqa: F401
from . import routing_active_edit  # noqa: F401
from . import export  # noqa: F401
from . import weldments  # noqa: F401
from . import sheetmetal  # noqa: F401
from . import sheetmetal_bodies  # noqa: F401
from . import sheetmetal_hem  # noqa: F401
from . import assembly  # noqa: F401
from . import component_edges  # noqa: F401
from . import cutlist  # noqa: F401
from . import cutlist_bodies  # noqa: F401
from . import save_bodies  # noqa: F401
from . import hole_catalog  # noqa: F401
from . import drawings  # noqa: F401
from . import inspection  # noqa: F401
from . import patterns  # noqa: F401
from . import measurements  # noqa: F401
from . import views  # noqa: F401
from . import history  # noqa: F401
from . import reference_geometry  # noqa: F401
from . import advanced_features  # noqa: F401
from . import surface_features  # noqa: F401
from . import properties  # noqa: F401
from . import configurations  # noqa: F401
from . import project_copy  # noqa: F401
from . import model_edit  # noqa: F401
from . import body_features  # noqa: F401
from . import appearance  # noqa: F401
from . import material  # noqa: F401
from . import equations  # noqa: F401
from . import sketch_edit  # noqa: F401
from . import sketch_entities  # noqa: F401
from . import sketch_create  # noqa: F401
from . import drawing_annotations  # noqa: F401
from . import saving  # noqa: F401
from . import imports  # noqa: F401
from . import standard_parts  # noqa: F401
from . import simulation  # noqa: F401
from . import parameter_workspace  # noqa: F401
from . import parameter_batch  # noqa: F401
from . import project_lifecycle  # noqa: F401
from . import cad_workflows  # noqa: F401
from . import engineering_planners  # noqa: F401
from . import manufacturing_package  # noqa: F401
from . import session  # noqa: F401
from . import features_basic  # noqa: F401
from . import sketch_basic  # noqa: F401
from . import documents  # noqa: F401

__all__ = ["export", "weldments", "sheetmetal", "assembly", "cutlist", "drawings", "inspection", "patterns", "measurements", "views", "history", "reference_geometry", "advanced_features", "surface_features", "properties", "configurations", "body_features", "appearance", "material", "equations", "sketch_edit", "sketch_entities", "drawing_annotations", "saving", "imports", "standard_parts", "simulation"]

from . import construction_geometry  # noqa: F401
from . import component_svg  # noqa: F401
from . import sheetmetal_body_export  # noqa: F401
from . import assembly_documentation  # noqa: F401
from . import manufacturing_bodies  # noqa: F401
from . import assembly_exports  # noqa: F401
from . import documentation_drawing  # noqa: F401
