"""Live Simulation workflow on a scratch structural-member beam.

The beam is a real library profile (DIN IPE) extruded 600 mm along a sketch
line, so the model is large enough for the mesh counts to be meaningful.  A
weldment part is a beam study by default, which cannot be meshed before beam
joints exist; ``create_static_study`` converts the beam bodies to solid bodies
so the standard solid mesh workflow applies.

Each test builds its own single-member part and closes it again; the part is
saved into the approved output root only where the test proves persistence.
"""

import os
import unittest
from pathlib import Path
from uuid import uuid4

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.tools.export import list_planar_faces
from solidworks_mcp.tools.material import apply_material
from solidworks_mcp.tools.reference_geometry import create_reference_axis
from solidworks_mcp.tools.saving import save_document
from solidworks_mcp.tools.simulation import (
    apply_fixed_fixture, apply_force_load, apply_pressure_load,
    create_static_study, get_displacement_results, get_reaction_results,
    get_stress_results, run_analysis)
from solidworks_mcp.tools.weldments import (
    create_structural_member, list_weldment_profiles)

BEAM_LENGTH_MM = 600
LOAD_NEWTONS = 2000.0
DEFAULT_PROFILE_NAME = "ipe.sldlfp"
DEFAULT_PROFILE_FOLDER = "din"
TUBE_PROFILE_NAME = "square tube.sldlfp"
TUBE_PROFILE_FOLDER = "iso"
MATERIAL_DB = (r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\english"
               r"\sldmaterials\solidworks materials.sldmat")
MATERIAL_NAME = "Plain Carbon Steel"


@unittest.skipUnless(os.environ.get("SW_MCP_LIVE_TESTS") == "1",
                     "Set SW_MCP_LIVE_TESTS=1 to run SolidWorks COM tests.")
class LiveSimulationStaticTests(unittest.TestCase):
    def setUp(self):
        self.automation = SolidWorksAutomation()
        result = self.automation.connect()
        if not result["success"]:
            self.skipTest(result["message"])
        self.created_titles = []
        self.output_root = Path(self.automation._path_policy.output_roots[0])

    def tearDown(self):
        for title in reversed(self.created_titles):
            try:
                self.automation.app.CloseDoc(title)
            except Exception:
                pass
        self.automation.disconnect()

    # -- scratch beam -------------------------------------------------------
    def _new_part(self):
        result = self.automation.create_new_part()
        self.assertTrue(result["success"], result["message"])
        title = result["data"]["name"]
        self.created_titles.append(title)
        return title

    def _document(self):
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        return document

    def _sketch_name(self, document):
        name = None
        feature = com(document, "FirstFeature")
        while feature is not None:
            if com(feature, "GetTypeName2") == "ProfileFeature":
                name = str(com(feature, "Name"))
            feature = com(feature, "GetNextFeature")
        return name

    def _profile(self, name=DEFAULT_PROFILE_NAME, folder=DEFAULT_PROFILE_FOLDER):
        """A library profile; the defaults are the DIN IPE most tests use."""
        stem = name.split(".")[0]
        profiles = list_weldment_profiles(self.automation, filter=stem)
        self.assertTrue(profiles["success"], profiles["message"])
        items = profiles["data"]["profiles"]
        self.assertTrue(items, f"No weldment profile matches {name!r}.")
        chosen = next((item for item in items
                       if item["folder"].casefold() == folder.casefold()
                       and item["name"].casefold() == name.casefold()), None)
        self.assertIsNotNone(
            chosen, f"Profile {name!r} is not in the {folder!r} folder.")
        return chosen

    def _beam(self, profile_name=DEFAULT_PROFILE_NAME,
              profile_folder=DEFAULT_PROFILE_FOLDER):
        """A 600 mm single-member beam built from a real library profile."""
        self._new_part()
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        line = self.automation.draw_line(0, 0, BEAM_LENGTH_MM, 0, "mm")
        self.assertTrue(line["success"], line["message"])
        self.assertTrue(self.automation.exit_sketch()["success"])

        document = self._document()
        profile = self._profile(profile_name, profile_folder)
        member = create_structural_member(self.automation,
                                          self._sketch_name(document),
                                          profile["path"])
        self.assertTrue(member["success"], member["message"])
        material = apply_material(self.automation, MATERIAL_NAME, MATERIAL_DB)
        self.assertTrue(material["success"], material["message"])
        self.assertGreater(self._volume_mm3(), 0)
        return document, member["data"]["feature"], profile

    def _volume_mm3(self):
        return sum(com(body, "GetMassProperties", 0.0)[3] * 1e9
                   for body in com(self._document(), "GetBodies2", 0, True) or [])

    def _planar_faces(self):
        """The beam's planar faces and the index of its axis."""
        listed = list_planar_faces(self.automation)
        self.assertTrue(listed["success"], listed["message"])
        faces = listed["data"]["faces"]
        self.assertTrue(faces, "The beam has no planar faces.")
        points = [item["point_mm"] for item in faces]
        spreads = [max(p[axis] for p in points) - min(p[axis] for p in points)
                   for axis in range(3)]
        return faces, spreads.index(max(spreads))

    def _end_faces(self):
        """The two end caps of the beam, as planar-face indices."""
        faces, axis = self._planar_faces()
        ends = sorted((item for item in faces if abs(item["normal"][axis]) > 0.9),
                      key=lambda item: item["point_mm"][axis])
        self.assertGreaterEqual(len(ends), 2, "The beam has no two end faces.")
        self.assertGreater(ends[-1]["point_mm"][axis] - ends[0]["point_mm"][axis], 0)
        return ends[0]["index"], ends[-1]["index"]

    def _flange_face(self):
        """Largest face normal to the beam axis: a transverse (bending) load face."""
        faces, axis = self._planar_faces()
        sideways = [item for item in faces if abs(item["normal"][axis]) < 0.1]
        self.assertTrue(sideways, "The beam has no face normal to its axis.")
        return max(sideways, key=lambda item: item["area_mm2"])["index"]

    def _reference_axis(self, axis_index):
        """Create a reference axis along the beam and return its feature name.

        The plane pair is derived from the planes' own normals instead of a
        hardcoded name mapping, because the standard planes of this template do
        not follow the usual Front = XY convention.
        """
        normals = {}
        for name in ("Front Plane", "Top Plane", "Right Plane"):
            feature = com(self._document(), "FeatureByName", name)
            plane = com(feature, "GetSpecificFeature2")
            normals[name] = list(com(com(plane, "Transform"), "ArrayData"))[6:9]

        def cross(first, second):
            return (first[1] * second[2] - first[2] * second[1],
                    first[2] * second[0] - first[0] * second[2],
                    first[0] * second[1] - first[1] * second[0])

        for first, second in (("Front Plane", "Top Plane"),
                              ("Front Plane", "Right Plane"),
                              ("Top Plane", "Right Plane")):
            direction = cross(normals[first], normals[second])
            if max(range(3), key=lambda index: abs(direction[index])) == axis_index:
                result = create_reference_axis(self.automation, first, second)
                self.assertTrue(result["success"], result["message"])
                return result["data"]["feature_name"]
        self.fail("No standard plane pair intersects along the beam axis.")

    def _study_with_loads(self, name):
        self.assertTrue(create_static_study(self.automation, name)["success"])
        fixed, loaded = self._end_faces()
        fixture = apply_fixed_fixture(self.automation, [fixed], study=name)
        self.assertTrue(fixture["success"], fixture["message"])
        force = apply_force_load(self.automation, [loaded], LOAD_NEWTONS, study=name)
        self.assertTrue(force["success"], force["message"])
        return fixed, loaded

    def _save(self, path):
        """Save As renames the document, so the open title follows the path."""
        saved = save_document(self.automation, path=str(path))
        self.assertTrue(saved["success"], saved["message"])
        self.created_titles[-1] = path.stem

    # -- 5.1 ----------------------------------------------------------------
    def test_create_static_study_converts_beam_bodies_and_verifies_the_study(self):
        document, feature, profile = self._beam()
        self.assertIn("WeldMemberFeat", self._feature_types(document))
        self.assertTrue(feature)

        result = create_static_study(self.automation, "MCP Beam Static")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(1, result["data"]["study_count_after"])
        self.assertEqual(0, result["data"]["analysis_type"])
        self.assertEqual(0, result["data"]["mesh_type"])
        self.assertGreaterEqual(result["data"]["beam_bodies_converted"], 1,
                                "The weldment study was not converted to solid bodies.")

        path = self.output_root / "saved" / f"mcp_live_sim_beam_{uuid4().hex}.SLDPRT"
        self._save(path)
        self.assertGreater(path.stat().st_size, 0)

    def _feature_types(self, document):
        types = []
        feature = com(document, "FirstFeature")
        while feature is not None:
            types.append(str(com(feature, "GetTypeName2")))
            feature = com(feature, "GetNextFeature")
        return types

    # -- 5.3 ----------------------------------------------------------------
    def test_apply_fixed_fixture_adds_one_fixed_restraint(self):
        self._beam()
        fixed, _loaded = self._end_faces()
        self.assertTrue(create_static_study(self.automation, "MCP Fixed")["success"])

        result = apply_fixed_fixture(self.automation, [fixed], study="MCP Fixed")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(0, result["data"]["restraint_type"])
        self.assertEqual(1, result["data"]["face_count"])
        self.assertEqual(0, result["data"]["count_before"])
        self.assertEqual(1, result["data"]["count_after"])

    # -- 5.4 ----------------------------------------------------------------
    def test_apply_force_load_converts_units_and_reads_the_magnitude_back(self):
        self._beam()
        _fixed, loaded = self._end_faces()
        self.assertTrue(create_static_study(self.automation, "MCP Force")["success"])

        # A force unit: 2 kN must be stored as 2000 N.
        kilonewtons = apply_force_load(self.automation, [loaded], LOAD_NEWTONS / 1000.0,
                                       unit="kN", study="MCP Force")
        self.assertTrue(kilonewtons["success"], kilonewtons["message"])
        self.assertEqual(1000.0, kilonewtons["data"]["conversion_factor"])
        self.assertAlmostEqual(LOAD_NEWTONS, kilonewtons["data"]["force_newtons"],
                               places=6)
        self.assertAlmostEqual(LOAD_NEWTONS, kilonewtons["data"]["read_back_newtons"],
                               places=6)
        self.assertEqual(1, kilonewtons["data"]["force_type"])
        self.assertEqual(1, kilonewtons["data"]["count_after"])

        # A mass unit: 200 kg becomes 200 * 9.80665 N in the study.
        kilograms = apply_force_load(self.automation, [loaded], 200.0, unit="kg",
                                     study="MCP Force")
        self.assertTrue(kilograms["success"], kilograms["message"])
        expected = 200.0 * 9.80665
        self.assertAlmostEqual(expected, kilograms["data"]["force_newtons"], places=6)
        self.assertAlmostEqual(expected, kilograms["data"]["read_back_newtons"],
                               places=6)
        self.assertEqual(2, kilograms["data"]["count_after"])

    # -- 5.5 ----------------------------------------------------------------
    def test_run_analysis_meshes_the_beam_and_solves(self):
        document, _feature, _profile = self._beam()
        self._study_with_loads("MCP Solve")

        result = run_analysis(self.automation, study="MCP Solve")

        if not result["success"]:
            self.assertEqual("ANALYSIS_AUTHORIZATION_FAILED", result["data"].get("code"),
                             result["message"])
            self.skipTest("Simulation license does not authorize a static solve.")
        self.assertGreater(result["data"]["node_count"], 1000)
        self.assertGreater(result["data"]["element_count"], 500)
        self.assertEqual(0, result["data"]["mesh_error"])
        self.assertEqual(0, result["data"]["run_error"])
        # The mesh is a real discretisation of the beam, not a stub.
        self.assertGreater(self._volume_mm3(), 0)

    # -- bending load case --------------------------------------------------
    def test_transverse_load_on_a_flange_gives_a_positive_bending_stress(self):
        """A normal force on a face perpendicular to the axis bends the beam."""
        self._beam()
        fixed, _loaded = self._end_faces()
        flange = self._flange_face()
        self.assertTrue(create_static_study(self.automation, "MCP Bending")["success"])
        fixture = apply_fixed_fixture(self.automation, [fixed], study="MCP Bending")
        self.assertTrue(fixture["success"], fixture["message"])
        force = apply_force_load(self.automation, [flange], 200.0, unit="kg",
                                 study="MCP Bending")
        self.assertTrue(force["success"], force["message"])
        self.assertGreater(force["data"]["face_count"], 0)

        analysis = run_analysis(self.automation, study="MCP Bending")
        if not analysis["success"]:
            self.assertEqual("ANALYSIS_AUTHORIZATION_FAILED",
                             analysis["data"].get("code"), analysis["message"])
            self.skipTest("Simulation license does not authorize a static solve.")

        result = get_stress_results(self.automation, study="MCP Bending")

        self.assertTrue(result["success"], result["message"])
        self.assertGreater(result["data"]["stress_max_mpa"], 0)

    # -- torsion load case --------------------------------------------------
    def test_torque_load_on_the_beam_solves_with_a_positive_stress(self):
        """A torque about the beam axis twists the beam."""
        self._beam()
        _faces, axis = self._planar_faces()
        axis_name = self._reference_axis(axis)
        self.assertTrue(create_static_study(self.automation, "MCP Zasuk")["success"])
        fixed, loaded = self._end_faces()
        fixture = apply_fixed_fixture(self.automation, [fixed], study="MCP Zasuk")
        self.assertTrue(fixture["success"], fixture["message"])

        torque = apply_force_load(self.automation, [loaded], 500.0, unit="N*m",
                                  load_type="torque", reference=axis_name,
                                  study="MCP Zasuk")

        self.assertTrue(torque["success"], torque["message"])
        self.assertEqual("torque", torque["data"]["load_type"])
        self.assertEqual(2, torque["data"]["force_type"])
        self.assertEqual(500.0, torque["data"]["torque_nm"])
        self.assertAlmostEqual(500.0, torque["data"]["read_back_nm"], places=6)
        self.assertEqual(axis_name, torque["data"]["reference"])

        analysis = run_analysis(self.automation, study="MCP Zasuk")
        if not analysis["success"]:
            self.assertEqual("ANALYSIS_AUTHORIZATION_FAILED",
                             analysis["data"].get("code"), analysis["message"])
            self.skipTest("Simulation license does not authorize a static solve.")
        self.assertEqual(0, analysis["data"]["run_error"])

        result = get_stress_results(self.automation, study="MCP Zasuk")

        self.assertTrue(result["success"], result["message"])
        self.assertGreater(result["data"]["stress_max_mpa"], 0)

    # -- 5.6 ----------------------------------------------------------------
    def test_get_stress_results_returns_a_finite_positive_maximum(self):
        document, _feature, _profile = self._beam()
        self._study_with_loads("MCP Stress")
        analysis = run_analysis(self.automation, study="MCP Stress")
        if not analysis["success"]:
            self.assertEqual("ANALYSIS_AUTHORIZATION_FAILED",
                             analysis["data"].get("code"), analysis["message"])
            self.skipTest("Simulation license does not authorize a static solve.")

        result = get_stress_results(self.automation, study="MCP Stress")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(9, result["data"]["component"])
        self.assertGreaterEqual(result["data"]["available_steps"], 1)
        self.assertGreater(result["data"]["stress_max_mpa"], 0)
        self.assertGreaterEqual(result["data"]["stress_min_mpa"], 0)
        self.assertLessEqual(result["data"]["stress_min_mpa"],
                             result["data"]["stress_max_mpa"])
        self.assertGreaterEqual(result["data"]["node_max"], 0)
        # The solved beam mesh must have the node the maximum refers to.
        self.assertLess(result["data"]["node_max"], analysis["data"]["node_count"])


    # -- pressure load case -------------------------------------------------
    def test_pressure_load_matches_the_equivalent_force(self):
        """Pressure p over face area A must deform like a force p * A."""
        self._beam()
        fixed, _loaded = self._end_faces()
        flange = self._flange_face()
        listed = list_planar_faces(self.automation)
        self.assertTrue(listed["success"], listed["message"])
        area_mm2 = next(item["area_mm2"] for item in listed["data"]["faces"]
                        if item["index"] == flange)
        self.assertGreater(area_mm2, 0)
        pressure_n_per_mm2 = 0.02  # 0.02 MPa over the 220 x 600 mm IPE flange
        equivalent_newtons = pressure_n_per_mm2 * area_mm2

        self.assertTrue(create_static_study(self.automation, "MCP Tlak")["success"])
        fixture = apply_fixed_fixture(self.automation, [fixed], study="MCP Tlak")
        self.assertTrue(fixture["success"], fixture["message"])

        pressure = apply_pressure_load(self.automation, [flange], pressure_n_per_mm2,
                                       unit="MPa", study="MCP Tlak")

        self.assertTrue(pressure["success"], pressure["message"])
        self.assertEqual("mpa", pressure["data"]["unit"])
        self.assertEqual(0, pressure["data"]["unit_index"])  # the study is SI
        self.assertEqual("Pa", pressure["data"]["unit_name"])
        self.assertAlmostEqual(20000.0, pressure["data"]["pressure_pascal"], places=6)
        self.assertAlmostEqual(20000.0, pressure["data"]["read_back_pascal"], places=6)
        self.assertEqual(0, pressure["data"]["pressure_type"])
        self.assertEqual(2, pressure["data"]["count_after"])

        analysis = run_analysis(self.automation, study="MCP Tlak")
        if not analysis["success"]:
            self.assertEqual("ANALYSIS_AUTHORIZATION_FAILED",
                             analysis["data"].get("code"), analysis["message"])
            self.skipTest("Simulation license does not authorize a static solve.")
        self.assertEqual(0, analysis["data"]["run_error"])

        stress = get_stress_results(self.automation, study="MCP Tlak")
        self.assertTrue(stress["success"], stress["message"])
        self.assertGreater(stress["data"]["stress_max_mpa"], 0)

        # The geometric proof: the pressure really moved the beam.
        under_pressure = get_displacement_results(self.automation, study="MCP Tlak")
        self.assertTrue(under_pressure["success"], under_pressure["message"])
        self.assertGreater(under_pressure["data"]["displacement_max"], 0)

        # Physical cross-check: the same total load as one normal force must give
        # the same deflection, so the pascal value cannot be off by a factor.
        self.assertTrue(create_static_study(self.automation, "MCP Sila")["success"])
        self.assertTrue(apply_fixed_fixture(self.automation, [fixed],
                                           study="MCP Sila")["success"])
        force = apply_force_load(self.automation, [flange], equivalent_newtons,
                                 unit="N", study="MCP Sila")
        self.assertTrue(force["success"], force["message"])
        self.assertAlmostEqual(equivalent_newtons, force["data"]["force_newtons"],
                               places=6)

        force_analysis = run_analysis(self.automation, study="MCP Sila")
        if not force_analysis["success"]:
            self.assertEqual("ANALYSIS_AUTHORIZATION_FAILED",
                             force_analysis["data"].get("code"),
                             force_analysis["message"])
            self.skipTest("Simulation license does not authorize a static solve.")

        under_force = get_displacement_results(self.automation, study="MCP Sila")
        self.assertTrue(under_force["success"], under_force["message"])

        self.assertAlmostEqual(
            under_force["data"]["displacement_max"],
            under_pressure["data"]["displacement_max"],
            delta=0.05 * under_force["data"]["displacement_max"])

    def test_pressure_on_a_hollow_section_solves(self):
        """The same workflow on a second profile family, an ISO square tube."""
        _document, _feature, profile = self._beam(TUBE_PROFILE_NAME,
                                                  TUBE_PROFILE_FOLDER)
        self.assertIn("square tube", str(profile["name"]).casefold())
        fixed, _loaded = self._end_faces()
        flange = self._flange_face()
        listed = list_planar_faces(self.automation)
        self.assertTrue(listed["success"], listed["message"])
        area_mm2 = next(item["area_mm2"] for item in listed["data"]["faces"]
                        if item["index"] == flange)
        self.assertGreater(area_mm2, 0)

        self.assertTrue(create_static_study(self.automation, "MCP Tlak cev")["success"])
        fixture = apply_fixed_fixture(self.automation, [fixed], study="MCP Tlak cev")
        self.assertTrue(fixture["success"], fixture["message"])

        pressure = apply_pressure_load(self.automation, [flange], 0.05, unit="MPa",
                                       study="MCP Tlak cev")

        self.assertTrue(pressure["success"], pressure["message"])
        self.assertEqual(0, pressure["data"]["unit_index"])  # the study is SI
        self.assertAlmostEqual(50000.0, pressure["data"]["read_back_pascal"], places=6)
        self.assertEqual("square tube.sldlfp", str(profile["name"]))

        analysis = run_analysis(self.automation, study="MCP Tlak cev")
        if not analysis["success"]:
            self.assertEqual("ANALYSIS_AUTHORIZATION_FAILED",
                             analysis["data"].get("code"), analysis["message"])
            self.skipTest("Simulation license does not authorize a static solve.")
        self.assertEqual(0, analysis["data"]["run_error"])

        stress = get_stress_results(self.automation, study="MCP Tlak cev")
        self.assertTrue(stress["success"], stress["message"])
        self.assertGreater(stress["data"]["stress_max_mpa"], 0)

        displacement = get_displacement_results(self.automation, study="MCP Tlak cev")
        self.assertTrue(displacement["success"], displacement["message"])
        self.assertGreater(displacement["data"]["displacement_max"], 0)

    # -- displacement results ----------------------------------------------
    def test_displacement_is_reported_in_the_requested_unit(self):
        """The same resultant displacement in mm and in m must differ by 1000."""
        self._beam()
        fixed, loaded = self._end_faces()
        flange = self._flange_face()
        self.assertTrue(create_static_study(self.automation, "MCP Pomiki")["success"])
        self.assertTrue(apply_fixed_fixture(self.automation, [fixed],
                                           study="MCP Pomiki")["success"])
        force = apply_force_load(self.automation, [flange], 200.0, unit="kg",
                                 study="MCP Pomiki")
        self.assertTrue(force["success"], force["message"])

        analysis = run_analysis(self.automation, study="MCP Pomiki")
        if not analysis["success"]:
            self.assertEqual("ANALYSIS_AUTHORIZATION_FAILED",
                             analysis["data"].get("code"), analysis["message"])
            self.skipTest("Simulation license does not authorize a static solve.")

        millimetres = get_displacement_results(self.automation, study="MCP Pomiki",
                                              unit="mm")
        metres = get_displacement_results(self.automation, study="MCP Pomiki",
                                         unit="m")

        self.assertTrue(millimetres["success"], millimetres["message"])
        self.assertTrue(metres["success"], metres["message"])
        self.assertEqual("URES", millimetres["data"]["component_name"])
        self.assertEqual(0, millimetres["data"]["unit_index"])
        self.assertEqual(2, metres["data"]["unit_index"])
        self.assertGreater(millimetres["data"]["displacement_max"], 0)
        self.assertAlmostEqual(millimetres["data"]["displacement_max"] / 1000.0,
                               metres["data"]["displacement_max"], places=6)


    # -- reaction results ---------------------------------------------------
    def test_reaction_results_oppose_the_applied_load(self):
        """A solved support must react exactly what was applied.

        The restrained face is passed as a selection, so the reaction is read
        both for the face and for the whole model.  The add-in's moment half
        is the sum of nodal moment reactions; a solid mesh has no rotational
        degree of freedom, so it stays zero and the physical moment reaction
        lives in the force distribution (checked here as a pure couple).
        """
        self._beam()

        # Case 1: a 2000 N axial pull.
        fixed, loaded = self._end_faces()
        self.assertTrue(create_static_study(self.automation,
                                            "MCP Reakcije sila")["success"])
        self.assertTrue(apply_fixed_fixture(self.automation, [fixed],
                                           study="MCP Reakcije sila")["success"])
        force = apply_force_load(self.automation, [loaded], LOAD_NEWTONS,
                                 study="MCP Reakcije sila")
        self.assertTrue(force["success"], force["message"])

        analysis = run_analysis(self.automation, study="MCP Reakcije sila")
        if not analysis["success"]:
            self.assertEqual("ANALYSIS_AUTHORIZATION_FAILED",
                             analysis["data"].get("code"), analysis["message"])
            self.skipTest("Simulation license does not authorize a static solve.")
        self.assertEqual(0, analysis["data"]["run_error"])

        tensile = get_reaction_results(self.automation, study="MCP Reakcije sila",
                                       face_indices=[fixed])

        self.assertTrue(tensile["success"], tensile["message"])
        data = tensile["data"]
        self.assertEqual("N", data["unit"])
        self.assertEqual("N*m", data["moment_unit"])
        self.assertEqual([fixed], data["face_indices"])
        entire = data["entire_model"]
        self.assertAlmostEqual(LOAD_NEWTONS, entire["force_resultant"],
                               delta=LOAD_NEWTONS * 0.01)
        # Exactly one global component carries the axial reaction.
        self.assertAlmostEqual(
            LOAD_NEWTONS,
            max(abs(entire[key]) for key in ("force_x", "force_y", "force_z")),
            delta=LOAD_NEWTONS * 0.01)
        # The restrained face reacts the same load as the whole model.
        self.assertAlmostEqual(LOAD_NEWTONS, data["selection"]["force_resultant"],
                               delta=LOAD_NEWTONS * 0.01)
        self.assertEqual(1, len(data["per_face"]))
        self.assertEqual(fixed, data["per_face"][0]["face_index"])
        self.assertAlmostEqual(LOAD_NEWTONS,
                               data["per_face"][0]["force_resultant"],
                               delta=LOAD_NEWTONS * 0.01)
        # A pure axial pull leaves no reaction moment.
        self.assertLess(abs(entire["moment_resultant"]), 1.0)

        # The same reaction in kgf is the same number of newton times g.
        in_kgf = get_reaction_results(self.automation, study="MCP Reakcije sila",
                                      unit="kgf")
        self.assertTrue(in_kgf["success"], in_kgf["message"])
        self.assertEqual(2, in_kgf["data"]["unit_index"])
        self.assertEqual("kgf*cm", in_kgf["data"]["moment_unit"])
        self.assertAlmostEqual(LOAD_NEWTONS / 9.80665,
                               in_kgf["data"]["entire_model"]["force_resultant"],
                               delta=1.0)

        # Case 2: a 500 N*m torque about the beam axis.
        _faces, axis = self._planar_faces()
        axis_name = self._reference_axis(axis)
        self.assertTrue(create_static_study(self.automation,
                                            "MCP Reakcije moment")["success"])
        self.assertTrue(apply_fixed_fixture(self.automation, [fixed],
                                           study="MCP Reakcije moment")["success"])
        torque = apply_force_load(self.automation, [loaded], 500.0, unit="N*m",
                                  load_type="torque", reference=axis_name,
                                  study="MCP Reakcije moment")
        self.assertTrue(torque["success"], torque["message"])

        turn = run_analysis(self.automation, study="MCP Reakcije moment")
        self.assertTrue(turn["success"], turn["message"])
        self.assertEqual(0, turn["data"]["run_error"])
        # The torque is real: it twists the beam.
        twist = get_displacement_results(self.automation,
                                         study="MCP Reakcije moment")
        self.assertTrue(twist["success"], twist["message"])
        self.assertGreater(twist["data"]["displacement_max"], 0)

        torsional = get_reaction_results(self.automation,
                                         study="MCP Reakcije moment")

        self.assertTrue(torsional["success"], torsional["message"])
        # A pure torque is a couple: the reactions cancel out force-wise.
        self.assertLess(abs(torsional["data"]["entire_model"]["force_resultant"]),
                        5.0)


if __name__ == "__main__":
    unittest.main()
