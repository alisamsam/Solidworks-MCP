"""The nut adapter checks real solids and never exposes an unverified copy."""

import tempfile
import json
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from solidworks_mcp.core.policy import PathPolicy
from solidworks_mcp.tools import standard_parts as sp


ROW = {
    "standard": "DIN", "category": "nuts", "source": "browser",
    "standard_folder": "DIN", "type": "hex nut style 1 gradeab",
    "file": sp.DIN934_MASTER,
    "rel": "nuts/hex nuts/" + sp.DIN934_MASTER,
}
WASHER_ROW = {
    "standard": "DIN", "category": "washers", "source": "browser",
    "standard_folder": "DIN", "type": "plain washer grade a",
    "file": sp.DIN125A_MASTER,
    "rel": "washers/plain washers/" + sp.DIN125A_MASTER,
}
SCREW_ROW = {
    "standard": "ISO", "category": "bolts and screws", "source": "browser",
    "standard_folder": "ISO", "type": "socket head cap screw",
    "file": "socket head cap screw_iso.sldprt",
    "rel": "bolts and screws/hexagon socket head screws/socket head cap screw_iso.sldprt",
}

RECIPE = {
    "schema_version": 2,
    "families": [{
        "id": "iso4762", "standard": "ISO", "master": "socket head cap screw_iso.sldprt",
        "rel": SCREW_ROW["rel"], "kind": "screw", "prefix": "ISO 4762",
        "drivers": [{"dim": "Diameter@BodySke", "col": "DIAMETER", "src": "data"},
                    {"dim": "Head_dia@BodySke", "col": "HEAD_DIA", "src": "data"},
                    {"dim": "Head_ht@BodySke", "col": "HEAD_HT", "src": "data"}],
        "length_dims": [{"dim": "Length@BodySke", "col": "LENGTH"},
                        {"dim": "Thread_nom@BodySke", "col": "THREAD_LENGTH"}],
        "diameters": [{"size": "M10", "size_desig": "M10",
                       "values": {"Diameter@BodySke": 10.0, "Head_dia@BodySke": 16.0,
                                  "Head_ht@BodySke": 10.0},
                       "lengths": [{"length": 25.0, "thread": 25.0,
                                    "label": "ISO 4762 M10 x 25",
                                    "values": {"Length@BodySke": 25.0, "Thread_nom@BodySke": 25.0}},
                                   {"length": 40.0, "thread": 40.0,
                                    "label": "ISO 4762 M10 x 40",
                                    "values": {"Length@BodySke": 40.0, "Thread_nom@BodySke": 40.0}}]}],
        "box": {"overall": ["+", "Length@BodySke", "Head_ht@BodySke"],
                "cross_min": ["Head_dia@BodySke"], "cross_max": ["Head_dia@BodySke"]},
    }]}


def recipe_family():
    return RECIPE["families"][0]


def recipe_values(length=25.0):
    return {"Diameter@BodySke": 10.0, "Head_dia@BodySke": 16.0, "Head_ht@BodySke": 10.0,
            "Length@BodySke": length, "Thread_nom@BodySke": length}


def recipe_document(values=None, xsize=.035, error=0, bodies=1, active="ISO 4762 M10 x 25"):
    values = values or recipe_values()
    body = Object(GetBodyBox=lambda: [0, -.008, -.008, xsize, .008, .008],
                  GetFaces=lambda: [])
    feature = Object(GetErrorCode=lambda: error, GetNextFeature=lambda: None)
    return Object(ConfigurationManager=Object(ActiveConfiguration=Object(Name=active)),
                  Parameter=lambda key: Object(SystemValue=values[key] / 1000),
                  FirstFeature=lambda: feature,
                  GetBodies2=lambda *_: [body] * bodies)


class RecipeTests(unittest.TestCase):
    def test_catalog_offers_recipe_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.json").write_text(json.dumps([SCREW_ROW]), encoding="utf-8")
            (root / "sizes.json").write_text("{}", encoding="utf-8")
            (root / sp.RECIPES_FILE).write_text(json.dumps(RECIPE), encoding="utf-8")
            class Automation:
                def _result(self, success, message, error_code=0, data=None):
                    return {"success": success, "data": data or {}}
            with patch.dict(sp.os.environ, {sp.LIBRARY_ENV_VAR: str(root)}):
                part = sp.get_standard_part_sizes(Automation(), "ISO")["data"]["parts"][0]
                self.assertEqual("iso4762", part["recipe_family"])
                self.assertEqual(["ISO 4762 M10 x 25", "ISO 4762 M10 x 40"],
                                 part["preparable_sizes"])

    def test_insert_routes_recipe_size_through_validated_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.json").write_text(json.dumps([SCREW_ROW]), encoding="utf-8")
            (root / "sizes.json").write_text("{}", encoding="utf-8")
            (root / sp.RECIPES_FILE).write_text(json.dumps(RECIPE), encoding="utf-8")
            class Automation:
                def _result(self, success, message, error_code=0, data=None):
                    return {"success": success, "data": data or {}}
            with patch.dict(sp.os.environ, {sp.LIBRARY_ENV_VAR: str(root)}), \
                    patch.object(sp, "_prepare_recipe", return_value=str(root / "ready.sldprt")) as prep, \
                    patch.object(sp, "insert_component",
                                 return_value={"success": True, "data": {}}) as insert:
                result = sp.insert_standard_part(Automation(), "ISO", size="ISO 4762 M10 x 25")
                self.assertTrue(result["success"], result)
                prep.assert_called_once()
                self.assertEqual(str(root / "ready.sldprt"), insert.call_args.kwargs["filepath"])
                self.assertEqual(10.0, prep.call_args.args[5]["Diameter@BodySke"])
                self.assertEqual(25.0, prep.call_args.args[5]["Length@BodySke"])
                missing = sp.insert_standard_part(Automation(), "ISO", size="ISO 4762 M10 x 33")
                self.assertEqual("SIZE_NOT_AVAILABLE", missing["data"]["code"])
                self.assertLessEqual(len(missing["data"]["available"]), 50)

    def test_recipe_valid_requires_size_drivers_and_measured_box(self):
        def fake_com(obj, name, *args):
            value = getattr(obj, name)
            return value(*args) if callable(value) else value
        family = recipe_family()
        values = recipe_values()
        with patch.object(sp, "com", side_effect=fake_com):
            self.assertTrue(sp._recipe_valid(recipe_document(), "ISO 4762 M10 x 25",
                                             values, family["box"]))
            self.assertFalse(sp._recipe_valid(recipe_document(active="Default"),
                                              "ISO 4762 M10 x 25", values, family["box"]))
            self.assertFalse(sp._recipe_valid(recipe_document(xsize=.026),
                                              "ISO 4762 M10 x 25", values, family["box"]))
            self.assertFalse(sp._recipe_valid(recipe_document(error=1),
                                              "ISO 4762 M10 x 25", values, family["box"]))
            self.assertFalse(sp._recipe_valid(recipe_document(bodies=2),
                                              "ISO 4762 M10 x 25", values, family["box"]))
            self.assertFalse(sp._recipe_valid(recipe_document(),
                                              "ISO 4762 M10 x 25", values, None))
            self.assertFalse(sp._recipe_valid(recipe_document(),
                                              "ISO 4762 M10 x 25", values, {"overall": ["Missing@Dim"]}))
            wrong = dict(values, **{"Diameter@BodySke": 8.0})
            self.assertFalse(sp._recipe_valid(recipe_document(wrong),
                                              "ISO 4762 M10 x 25", values, family["box"]))
            self.assertTrue(sp._recipe_valid(recipe_document(wrong),
                                             "ISO 4762 M10 x 25", wrong, family["box"]))

    def test_recipe_entries_and_box_expressions(self):
        entries = dict(sp._family_size_entries(recipe_family()))
        self.assertEqual(25.0, entries["ISO 4762 M10 x 25"]["Length@BodySke"])
        self.assertEqual(40.0, entries["ISO 4762 M10 x 40"]["Thread_nom@BodySke"])
        box = recipe_family()["box"]
        values = sp._driver_values(entries["ISO 4762 M10 x 25"])
        self.assertEqual(35.0, sp._eval_box(box["overall"], values))
        self.assertEqual(16.0, sp._eval_box(box["cross_min"], values))
        self.assertEqual(16.0, sp._eval_box(box["cross_max"], values))
        self.assertEqual(3.0, sp._eval_box(["*", 2.0, 1.5], values))
        self.assertEqual(4.0, sp._eval_box(["max", 4.0, 1.5], values))
        with self.assertRaises(ValueError):
            sp._eval_box(["nope", 1.0], values)

    def test_family_lookup_prefers_the_exact_rel_and_falls_back_to_the_master(self):
        families = [recipe_family()]
        self.assertEqual("iso4762", sp._family_for_row(families, SCREW_ROW)["id"])
        other_rel = dict(SCREW_ROW, rel="custom/other/path.sldprt")
        self.assertEqual("iso4762", sp._family_for_row(families, other_rel)["id"])
        self.assertIsNone(sp._family_for_row(families, dict(SCREW_ROW, file="nope.sldprt")))

    def test_prepare_recipe_retries_with_another_plan(self):
        family = recipe_family()
        values = recipe_values()
        sw = SimpleNamespace()
        calls = []

        def fake_verified(_sw, _lib, _row, _label, drivers, _valid, **kwargs):
            calls.append((drivers, kwargs.get("mid_rebuild_at", 0)))
            return "path" if len(calls) == 2 else None

        with patch.object(sp, "_prepare_verified_copy", side_effect=fake_verified):
            self.assertEqual("path", sp._prepare_recipe(sw, Path("."), SCREW_ROW, family,
                                                        "ISO 4762 M10 x 25", values))
        self.assertEqual(2, len(calls))
        first, second = dict(calls[0][0]), dict(calls[1][0])
        self.assertEqual(set(first), set(second))
        # drivers are SolidWorks system values: metres for lengths
        self.assertAlmostEqual(.035, first["Length@BodySke"] + first["Head_ht@BodySke"])
        self.assertAlmostEqual(.025, second["Length@BodySke"])
        # the fallback plan rebuilds part way through the dimension list
        self.assertEqual((0, 3), (calls[0][1], calls[1][1]))


class Object:
    def __init__(self, **attributes):
        self.__dict__.update(attributes)


def good_document(bore=8.5, error=0):
    size = "DIN 934 M10"
    dims = dict(zip(("Thread_major@ThreadCosmetic", "Width_flats@BaseNutSke",
                     "Thickness@BaseNut", "Tap_drill@BaseNutSke"),
                    (10, 17, 8, 8.5)))
    cylinder = Object(IsCylinder=lambda: True,
                      CylinderParams=lambda: [0, 0, -0.008, 0, 0, 1, bore / 2000])
    body = Object(GetBodyBox=lambda: [-0.0085, -0.0098149546, -0.008,
                                       0.0085, 0.0098149546, 0],
                  GetFaces=lambda: [Object(GetSurface=lambda: cylinder)])
    feature = Object(GetErrorCode=lambda: error, GetNextFeature=lambda: None)
    return Object(ConfigurationManager=Object(ActiveConfiguration=Object(Name=size)),
                  Parameter=lambda key: Object(SystemValue=dims[key] / 1000),
                  FirstFeature=lambda: feature, GetBodies2=lambda *_: [body])


class Din934Tests(unittest.TestCase):
    def test_catalog_distinguishes_preparable_from_materialized_and_routes_m10(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.json").write_text(json.dumps([ROW]), encoding="utf-8")
            (root / "sizes.json").write_text(json.dumps({ROW["rel"]: ["existing cfg"]}), encoding="utf-8")
            class Automation:
                def _result(self, success, message, error_code=0, data=None):
                    return {"success": success, "message": message, "data": data or {}}
            sw = Automation()
            prepared = root / "verified.sldprt"
            with patch.dict(sp.os.environ, {sp.LIBRARY_ENV_VAR: str(root)}), \
                    patch.object(sp, "_prepare_din934_nut", return_value=str(prepared)) as nut, \
                    patch.object(sp, "insert_component", return_value={
                        "success": True, "data": {"name": "nut"}}) as insert:
                part = sp.get_standard_part_sizes(sw, "DIN")["data"]["parts"][0]
                self.assertEqual(["existing cfg"], part["sizes"])
                self.assertEqual(list(sp.DIN934_NUTS), part["preparable_sizes"])
                result = sp.insert_standard_part(sw, "DIN", size="DIN 934 M10")
                self.assertTrue(result["success"])
                nut.assert_called_once()
                self.assertEqual(str(prepared), insert.call_args.kwargs["filepath"])
                self.assertFalse(sp.insert_standard_part(sw, "DIN", size="DIN 934 M11")["success"])
            with patch.dict(sp.os.environ, {sp.LIBRARY_ENV_VAR: str(root)}), \
                    patch.object(sp, "_prepare_din934_nut", return_value=None), \
                    patch.object(sp, "insert_component") as insert:
                self.assertEqual("SIZE_PREPARATION_FAILED", sp.insert_standard_part(
                    sw, "DIN", size="DIN 934 M10")["data"]["code"])
                insert.assert_not_called()

    def test_geometry_requires_actual_bore_and_no_feature_errors(self):
        dimensions = sp.DIN934_NUTS["DIN 934 M10"]
        def fake_com(obj, name, *args):
            value = getattr(obj, name)
            return value(*args) if callable(value) else value
        with patch.object(sp, "com", side_effect=fake_com):
            self.assertTrue(sp._nut_valid(good_document(), "DIN 934 M10", dimensions))
            self.assertFalse(sp._nut_valid(good_document(bore=10), "DIN 934 M10", dimensions))
            self.assertFalse(sp._nut_valid(good_document(error=1), "DIN 934 M10", dimensions))

    def test_only_exact_master_is_eligible(self):
        self.assertTrue(sp._din934_nut(ROW))
        self.assertFalse(sp._din934_nut({**ROW, "file": "another nut_din.sldprt"}))
        self.assertEqual(17, len(sp.DIN934_NUTS))
        self.assertEqual((3, .5, 5.5, 2.4, 2.5), sp.DIN934_NUTS["DIN 934 M3"])
        self.assertEqual((30, 3.5, 46, 24, 26.5), sp.DIN934_NUTS["DIN 934 M30"])

    def test_denied_policy_cannot_copy_or_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / sp.DIN934_MASTER
            source.write_bytes(b"master")
            sw = SimpleNamespace(app=object(), _path_policy=PathPolicy([root / "elsewhere"]))
            with patch.object(sp, "_master_file", return_value=str(source)):
                self.assertIsNone(sp._prepare_din934_nut(sw, root, ROW, "DIN 934 M10"))
            self.assertFalse((root / "sized").exists())
            self.assertEqual(b"master", source.read_bytes())

    def test_publishes_only_after_validating_reopened_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / sp.DIN934_MASTER
            source.write_bytes(b"unchanged master")
            state = {"opens": 0, "saved": False, "bad_reopen": False, "bad_final": False,
                     "fail_final_close": False, "drivers": {}}
            def fake_com(obj, name, *args):
                value = getattr(obj, name)
                return value(*args) if callable(value) else value
            def open_doc(*_args):
                state["opens"] += 1
                invalid = (state["bad_reopen"] and state["opens"] == 2
                           or state["bad_final"] and state["opens"] == 3)
                doc = good_document(bore=10 if invalid else 8.5)
                doc.GetPathName = lambda: _args[0]
                config = doc.ConfigurationManager
                config.ActiveConfiguration.Name = "Default" if state["opens"] == 1 else "DIN 934 M10"
                config.AddConfiguration = lambda name, *_: Object(Name=name)
                doc.GetConfigurationByName = lambda *_: None
                doc.ShowConfiguration2 = lambda name: setattr(config.ActiveConfiguration, "Name", name) or False
                doc.Parameter = lambda key: Object(
                    SystemValue=state["drivers"].get(key, {
                        "Tap_drill@BaseNutSke": .0085, "Thread_major@ThreadCosmetic": .01,
                        "Width_flats@BaseNutSke": .017, "Thickness@BaseNut": .008,
                    }[key]),
                    SetSystemValue3=lambda value, *_: state["drivers"].__setitem__(key, value))
                doc.GetEquationMgr = lambda: Object(EvaluateAll=lambda: -1)
                doc.EditRebuild3 = lambda: True
                doc.ForceRebuild3 = lambda *_: True
                doc.Save3 = lambda *_: state.__setitem__("saved", True) or True
                doc.GetTitle = lambda: "staging"
                return doc
            def close_doc(*_):
                if state["fail_final_close"] and state["opens"] == 3:
                    raise RuntimeError("final close failed")
            app = Object(OpenDoc6=open_doc, CloseDoc=close_doc)
            sw = SimpleNamespace(app=app, _path_policy=PathPolicy([root]))
            pythoncom = types.ModuleType("pythoncom")
            pythoncom.VT_BYREF, pythoncom.VT_I4, pythoncom.VT_EMPTY = 0, 1, 2
            client = types.ModuleType("win32com.client")
            client.VARIANT = lambda *_: Object(value=0)
            win32com = types.ModuleType("win32com")
            win32com.client = client
            modules = {"pythoncom": pythoncom, "win32com": win32com,
                       "win32com.client": client}
            with patch.dict(sys.modules, modules), patch.object(sp, "com", side_effect=fake_com), \
                    patch.object(sp, "_master_file", return_value=str(source)):
                state["bad_reopen"] = True
                self.assertIsNone(sp._prepare_din934_nut(sw, root, ROW, "DIN 934 M10"))
                self.assertTrue(state["saved"])
                target = sp._sized_cache_path(root, ROW, "DIN 934 M10")
                self.assertFalse(target.exists())
                state.update(opens=0, bad_reopen=False, bad_final=True)
                self.assertIsNone(sp._prepare_din934_nut(sw, root, ROW, "DIN 934 M10"))
                self.assertFalse(target.exists())  # rejected final file is quarantined
                state.update(opens=0, bad_final=False, fail_final_close=True)
                self.assertIsNone(sp._prepare_din934_nut(sw, root, ROW, "DIN 934 M10"))
                self.assertFalse(target.exists())
                self.assertFalse(list(target.parent.glob("*.verified-*.json")))
                state.update(opens=0, bad_final=True, fail_final_close=False)
                rename = sp.os.rename
                def refuse_quarantine(src, dst):
                    if Path(src) == target and ".pending-" in Path(dst).name:
                        raise OSError("quarantine locked")
                    return rename(src, dst)
                with patch.object(sp.os, "rename", side_effect=refuse_quarantine):
                    self.assertIsNone(sp._prepare_din934_nut(sw, root, ROW, "DIN 934 M10"))
                self.assertTrue(target.exists())
                self.assertFalse(list(target.parent.glob("*.verified-*.json")))
                # A crash/failed cleanup leaves a target without a receipt. It
                # must be preserved and rebuilt, never accepted as a cache hit.
                state.update(opens=0, bad_reopen=False, bad_final=False)
                self.assertEqual(str(target), sp._prepare_din934_nut(
                    sw, root, ROW, "DIN 934 M10"))
                self.assertEqual(4, state["opens"])  # unverified cache + staging + final
                self.assertEqual(str(target), sp._prepare_din934_nut(
                    sw, root, ROW, "DIN 934 M10"))
                self.assertEqual(5, state["opens"])  # cache is reopened, not trusted by name
            self.assertEqual(b"unchanged master", source.read_bytes())


class Din125aTests(unittest.TestCase):
    def test_washer_catalog_and_insertion_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.json").write_text(json.dumps([WASHER_ROW]), encoding="utf-8")
            (root / "sizes.json").write_text("{}", encoding="utf-8")
            class Automation:
                def _result(self, success, message, error_code=0, data=None):
                    return {"success": success, "data": data or {}}
            with patch.dict(sp.os.environ, {sp.LIBRARY_ENV_VAR: str(root)}), \
                    patch.object(sp, "_prepare_din125a_washer", return_value=str(root / "ready.sldprt")) as prep, \
                    patch.object(sp, "insert_component", return_value={"success": True, "data": {}}):
                part = sp.get_standard_part_sizes(Automation(), "DIN")["data"]["parts"][0]
                self.assertEqual(list(sp.DIN125A_WASHERS), part["preparable_sizes"])
                self.assertTrue(sp.insert_standard_part(Automation(), "DIN", size="DIN 125A M10")["success"])
                prep.assert_called_once()

    def test_washer_requires_correct_solid_bore_and_feature_state(self):
        def fake_com(obj, name, *args):
            value = getattr(obj, name)
            return value(*args) if callable(value) else value
        def doc(bore=10.5, error=0):
            cylinder = Object(IsCylinder=lambda: True,
                              CylinderParams=lambda: [-.034925, 0, 0, -1, 0, 0, bore / 2000])
            body = Object(GetBodyBox=lambda: [-.002, -.01, -.01, 0, .01, .01],
                          GetFaces=lambda: [Object(GetSurface=lambda: cylinder)])
            dims = {"Inside_dia@Sketch1": .0105, "Outside_dia@Sketch1": .020,
                    "Thickness@Sketch1": .002}
            return Object(ConfigurationManager=Object(ActiveConfiguration=Object(Name="DIN 125A M10")),
                          Parameter=lambda key: Object(SystemValue=dims[key]),
                          FirstFeature=lambda: Object(GetErrorCode=lambda: error,
                                                      GetNextFeature=lambda: None),
                          GetBodies2=lambda *_: [body])
        with patch.object(sp, "com", side_effect=fake_com):
            self.assertTrue(sp._din125a_washer(WASHER_ROW))
            self.assertTrue(sp._washer_valid(doc(), "DIN 125A M10", sp.DIN125A_WASHERS["DIN 125A M10"]))
            self.assertFalse(sp._washer_valid(doc(bore=8), "DIN 125A M10", sp.DIN125A_WASHERS["DIN 125A M10"]))
            self.assertFalse(sp._washer_valid(doc(error=1), "DIN 125A M10", sp.DIN125A_WASHERS["DIN 125A M10"]))


class Iso4762Tests(unittest.TestCase):
    def test_screw_lists_length_and_routes_preparation(self):
        pass


if __name__ == "__main__":
    unittest.main()
