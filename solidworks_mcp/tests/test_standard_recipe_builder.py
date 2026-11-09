"""Regression tests for the Toolbox data transfer, without a CAD connection."""
import unittest
import copy
from unittest.mock import patch

from scripts import build_std_size_recipes as builder
from scripts.build_std_size_recipes import dim_unit
from solidworks_mcp.tools import standard_parts as sp


class RecipeTransferTests(unittest.TestCase):
    def build_fixture(self, conflicting=False, alternate=""):
        def grid(number, dim, col, source="", kind="Hidden"):
            return {"Grid_Item_Number": number, "Grid_Item_Name": "", "Dimension": dim,
                    "ValueList": "{[" + col + "]}", "AltDataSource": source,
                    "Grid_Item_Type": kind}
        cfg = [grid(1, "", "SIZE"),
               grid(10, "Length@BodySke", "LENGTH", "+DATA_MAIN_LENGTHS", "NUMERIC_COMBO"),
               grid(20, "Diameter@BodySke", "DIAMETER", alternate),
               grid(30, "Key_eng@Hex", "KEY_ENG", "+DATA_MAIN_LENGTHS"),
               grid(40, "Minor_dia@BodySke", "THD_MINOR", "+DATA_THRD")]
        threads = [{"THD_DIA": 8, "TPU": 1.25, "THD_MINOR": 6.6}]
        if conflicting:
            threads.append({"THD_DIA": 8, "TPU": 1.25, "THD_MINOR": 7.0})
        tables = {"ISO_CFG_MAIN": cfg,
                  "ISO_DATA_MAIN": [{"SIZE": "M8", "PITCH": 1.25, "DIAMETER": 8}],
                  "ISO_DATA_THRD": threads,
                  "ISO_DATA_MAIN_LENGTHS": [{"SIZE": "M8", "LENGTH": 10, "KEY_ENG": 4}]}
        row = {"ConfigurationTable": "+CFG_MAIN", "DataTable": "+DATA_MAIN"}
        with patch.object(builder, "find_row", return_value=row), \
                patch.object(builder, "read_table", side_effect=lambda _db, t: ([], tables[t])):
            return builder.build_family(None, "ISO_TYPE_BS", "test.sldprt", "fixture", "ISO test")

    def test_builder_preserves_all_declared_sources_and_length_columns(self):
        family, error = self.build_fixture()
        self.assertIsNone(error)
        values = family["diameters"][0]["lengths"][0]["values"]
        self.assertEqual({"Length@BodySke": 10, "Key_eng@Hex": 4}, values)
        self.assertEqual("ISO_DATA_THRD", family["drivers"][1]["source_table"])

    def test_builder_rejects_conflicting_thread_matches_and_unknown_source(self):
        with self.assertRaisesRegex(ValueError, "conflicting thread"):
            self.build_fixture(conflicting=True)
        with self.assertRaisesRegex(ValueError, "unsupported alternate"):
            self.build_fixture(alternate="+DATA_OTHER")

    def test_flange_is_a_length_not_an_angle(self):
        for name in ("Flange_dia@Sketch6", "Flange_thickness@Sketch6",
                     "Flange_fillet_radius@FlangeFillet"):
            self.assertEqual("mm", dim_unit(name, "FLANGE_DIA"))
        self.assertEqual("deg", dim_unit("Cone_ang@BodySke", "CONE_ANG"))
        self.assertEqual("deg", dim_unit("Head_ang@BodySke", "HEAD_ANG"))
        self.assertEqual("count", dim_unit("NumTeeth@Pattern", "NumberOfTeeth"))

    def test_all_length_dependent_columns_are_transferred_by_name(self):
        family = {
            "kind": "screw",
            "length_dims": [{"dim": name} for name in
                            ("Length@BodySke", "Cone_ang@BodySke", "Key_eng@Hex")],
            "diameters": [{"values": {"Diameter@BodySke": 8}, "lengths": [{
                "label": "ISO 4027 M8 x 10", "length": 10, "thread": None,
                "values": {"Length@BodySke": 10, "Cone_ang@BodySke": 90,
                           "Key_eng@Hex": 4}}]}],
        }
        label, values = next(sp._family_size_entries(family))
        self.assertEqual("ISO 4027 M8 x 10", label)
        self.assertEqual(90, values["Cone_ang@BodySke"])
        self.assertEqual(4, values["Key_eng@Hex"])
        self.assertEqual(8, values["Diameter@BodySke"])
        del family["diameters"][0]["lengths"][0]["values"]["Key_eng@Hex"]
        self.assertEqual([], list(sp._family_size_entries(family)))

    def test_invalid_units_and_fractional_counts_are_rejected(self):
        with self.assertRaises(ValueError):
            sp._system_value("inch", 10)
        with self.assertRaises(ValueError):
            sp._system_value("count", 3.5)
        self.assertEqual(6, sp._system_value("count", 6))

    def test_missing_non_box_driver_is_not_available_or_preparable(self):
        from solidworks_mcp.tests.test_din934_nut import recipe_family
        family = copy.deepcopy(recipe_family())
        del family["diameters"][0]["values"]["Diameter@BodySke"]
        self.assertEqual([], list(sp._family_size_entries(family)))
        self.assertIsNone(sp._prepare_recipe(None, None, {}, family, "bad", {}))
        nut = {"kind": "size", "drivers": [{"dim": "Tap_drill@Sketch"}],
               "sizes": [{"label": "Nut M10", "values": {"Width_flats@Sketch": 17}}]}
        self.assertEqual([], list(sp._family_size_entries(nut)))


if __name__ == "__main__":
    unittest.main()
