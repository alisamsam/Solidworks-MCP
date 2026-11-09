"""Planar face listing and DXF face axes use the face normal (B25)."""

import unittest
from unittest.mock import patch

from solidworks_mcp.tools.export import (
    _face_plane_axes, export_face_to_dxf, list_planar_faces,
)


class Surface:
    def __init__(self, params):
        self.PlaneParams = params

    def IsPlane(self):
        return True


class Face:
    """ISurface.PlaneParams may point against the outward IFace2.Normal."""

    def __init__(self, face_normal, surface_params, area=0.01):
        self.Normal = face_normal
        self.surface = Surface(surface_params)
        self.area = area

    def GetSurface(self):
        return self.surface

    def GetArea(self):
        return self.area


class Body:
    Name = "Body1"

    def __init__(self, faces):
        self.faces = faces

    def GetFaces(self):
        return self.faces


class Document:
    def __init__(self, faces):
        self.body = Body(faces)

    def GetType(self):
        return 1

    def GetBodies2(self, body_type, visible_only):
        return [self.body]

    def GetPathName(self):
        return ""


class Automation:
    def __init__(self, document):
        self.document = document

    def get_active_doc(self):
        return self.document, None

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "data": data or {}}


# The +X end cap of a box whose surface reports the -X plane normal (live, §33).
END_CAP = Face((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.04, 0.0, 0.0))


class PlanarFaceNormalTests(unittest.TestCase):
    @patch('solidworks_mcp.tools.export.require_output_write',return_value=None)
    @patch('solidworks_mcp.tools.export._get_planar_face_by_index',return_value=END_CAP)
    @patch('solidworks_mcp.tools.export._face_plane_axes',return_value=((1,0,0),(0,0,0),None,None))
    def test_missing_straight_outer_edge_returns_defined_error(self,*mocks):
        from types import MethodType
        doc=Document([END_CAP]);doc.GetPathName=MethodType(lambda d:'saved.sldprt',doc)
        result=export_face_to_dxf(Automation(doc),0,'out.dxf')
        self.assertFalse(result['success']);self.assertIn('axes',result['message'])
    def test_listed_normal_is_the_outward_face_normal(self):
        result = list_planar_faces(Automation(Document([END_CAP])))

        self.assertTrue(result["success"], result["message"])
        face = result["data"]["faces"][0]
        self.assertEqual([1.0, 0.0, 0.0], face["normal"])
        self.assertEqual([40.0, 0.0, 0.0], face["point_mm"])

    @patch("solidworks_mcp.tools.export._longest_edge_direction",
           return_value=(0.0, 1.0, 0.0))
    def test_dxf_axes_look_at_the_face_from_outside(self, _edge):
        normal, point, xdir, ydir = _face_plane_axes(END_CAP)

        self.assertEqual((1.0, 0.0, 0.0), normal)
        self.assertEqual((0.04, 0.0, 0.0), point)
        self.assertEqual((0.0, 1.0, 0.0), xdir)
        # Right-handed x, y, normal: y = normal x x = (0, 0, 1).
        self.assertEqual((0.0, 0.0, 1.0), tuple(v + 0.0 for v in ydir))

    @patch("solidworks_mcp.tools.export.require_output_write", return_value=None)
    def test_face_export_refuses_an_unsaved_part_with_a_clear_code(self, _guard):
        # ExportToDWG2 needs the model path; unsaved it fails silently (§18.3).
        result = export_face_to_dxf(Automation(Document([END_CAP])), 0, "C:/out/face.dxf")

        self.assertFalse(result["success"])
        self.assertEqual("UNSAVED_DOCUMENT", result["data"]["code"])
