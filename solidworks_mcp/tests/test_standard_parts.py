import json
import tempfile
import unittest
from pathlib import Path

from solidworks_mcp.core.policy import OperationClass, PathPolicy
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools import standard_parts as sp

# a small synthetic library, mirroring scripts/sync_standard_library.py output
INDEX_ROWS = [
    {
        "standard": "ISO", "standard_folder": "ISO",
        "category": "bolts and screws", "subcategory": "hex bolts and screws",
        "type": "hex screw gradeab", "file": "hex screw gradeab_iso.sldprt",
        "rel": "bolts and screws/hex bolts and screws/hex screw gradeab_iso.sldprt",
        "source": "browser",
        "path": r"C:\toolbox\browser\ISO\bolts and screws\hex bolts and screws\hex screw gradeab_iso.sldprt",
    },
    {
        "standard": "ISO", "standard_folder": "ISO",
        "category": "bolts and screws", "subcategory": "hexagon socket head screws",
        "type": "socket head cap screw", "file": "socket head cap screw_iso.sldprt",
        "rel": "bolts and screws/hexagon socket head screws/socket head cap screw_iso.sldprt",
        "source": "browser",
        "path": r"C:\toolbox\browser\ISO\bolts and screws\hexagon socket head screws\socket head cap screw_iso.sldprt",
    },
    {
        "standard": "DIN", "standard_folder": "DIN",
        "category": "bolts and screws", "subcategory": "hexagon socket head screws",
        "type": "socket head cap screw", "file": "socket head cap screw 4762_din.sldprt",
        "rel": "bolts and screws/hexagon socket head screws/socket head cap screw 4762_din.sldprt",
        "source": "browser",
        "path": r"C:\toolbox\browser\DIN\bolts and screws\hexagon socket head screws\socket head cap screw 4762_din.sldprt",
    },
]

SIZES = {
    "bolts and screws/hexagon socket head screws/socket head cap screw_iso.sldprt": [
        "ISO 4762 M10 x 16 - 16N", "ISO 4762 M10 x 100 - 32N",
    ],
    "bolts and screws/hexagon socket head screws/socket head cap screw 4762_din.sldprt": [
        "DIN 912 M20x1.5 x 30 --- 30N",
    ],
}


class Automation:
    def __init__(self, app=None):
        self.app = app

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "error_code": int(error_code),
                "data": data or {}}


class LibraryCase(unittest.TestCase):
    """Sets up a temp library and points the module at it via the env var."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "index.json").write_text(
            json.dumps(INDEX_ROWS), encoding="utf-8")
        (self.root / "sizes.json").write_text(
            json.dumps(SIZES), encoding="utf-8")
        self._old = sp.os.environ.get(sp.LIBRARY_ENV_VAR)
        sp.os.environ[sp.LIBRARY_ENV_VAR] = str(self.root)

    def tearDown(self):
        if self._old is None:
            sp.os.environ.pop(sp.LIBRARY_ENV_VAR, None)
        else:
            sp.os.environ[sp.LIBRARY_ENV_VAR] = self._old
        self._tmp.cleanup()


class RegistrationTests(unittest.TestCase):
    def test_tools_are_registered(self):
        names = {item.name for item in registered_tools()}
        for expected in ("list_standard_parts", "get_standard_part_sizes",
                         "insert_standard_part", "standard_library_status"):
            self.assertIn(expected, names)

    def test_operation_classes(self):
        self.assertIs(OperationClass.READ,
                      operation_class_for("list_standard_parts"))
        self.assertIs(OperationClass.READ,
                      operation_class_for("get_standard_part_sizes"))
        self.assertIs(OperationClass.MUTATE,
                      operation_class_for("insert_standard_part"))
        self.assertIs(OperationClass.READ,
                      operation_class_for("standard_library_status"))


class ListStandardPartsTests(LibraryCase):
    def test_summary_counts_per_standard(self):
        sw = Automation()
        result = sp.list_standard_parts(sw)
        self.assertTrue(result["success"], result["message"])
        standards = result["data"]["standards"]
        self.assertEqual(2, standards["ISO"]["part_count"])
        self.assertEqual(1, standards["DIN"]["part_count"])

    def test_filter_by_standard(self):
        result = sp.list_standard_parts(Automation(), standard="ISO")
        self.assertTrue(result["success"], result["message"])
        self.assertTrue(all(p["standard"] == "ISO"
                            for p in result["data"]["parts"]))

    def test_unknown_standard_reports_clean_error(self):
        result = sp.list_standard_parts(Automation(), standard="GOST")
        self.assertFalse(result["success"])
        self.assertEqual("STANDARD_NOT_FOUND", result["data"]["code"])

    def test_missing_library_reports_not_found(self):
        with tempfile.TemporaryDirectory() as empty:
            old = sp.os.environ.get(sp.LIBRARY_ENV_VAR)
            sp.os.environ[sp.LIBRARY_ENV_VAR] = empty
            try:
                result = sp.list_standard_parts(Automation())
            finally:
                if old is None:
                    sp.os.environ.pop(sp.LIBRARY_ENV_VAR, None)
                else:
                    sp.os.environ[sp.LIBRARY_ENV_VAR] = old
        self.assertFalse(result["success"])
        self.assertEqual("STANDARD_LIBRARY_NOT_FOUND", result["data"]["code"])


class GetSizesTests(LibraryCase):
    def test_returns_materialised_sizes(self):
        result = sp.get_standard_part_sizes(
            Automation(), standard="ISO", type="socket head cap")
        self.assertTrue(result["success"], result["message"])
        parts = result["data"]["parts"]
        self.assertEqual(1, len(parts))
        self.assertEqual(2, parts[0]["size_count"])
        self.assertIn("ISO 4762 M10 x 16 - 16N", parts[0]["sizes"])

    def test_part_without_sizes_reports_empty(self):
        result = sp.get_standard_part_sizes(
            Automation(), standard="ISO", type="hex screw")
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(0, result["data"]["parts"][0]["size_count"])


class InsertStandardPartTests(LibraryCase):
    def test_preparation_reuses_existing_copy_without_touching_master(self):
        row = INDEX_ROWS[1]
        target = sp._sized_cache_path(self.root, row, SIZES[row["rel"]][0])
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing")
        sw = Automation()
        sw._path_policy = PathPolicy([self.root])

        result = sp._prepare_sized_copy(sw, self.root, row, SIZES[row["rel"]][0])

        self.assertEqual(str(target), result)
        self.assertEqual(b"existing", target.read_bytes())

    def test_preparation_denied_outside_approved_library(self):
        row = INDEX_ROWS[1]
        sw = Automation()
        sw._path_policy = PathPolicy([self.root / "other-output"])

        result = sp._prepare_sized_copy(sw, self.root, row, SIZES[row["rel"]][0])

        self.assertIsNone(result)
        self.assertFalse((self.root / "sized").exists())

    def test_fastener_without_size_never_inserts_preview_geometry(self):
        # a real source copy lets the resolver pick the portable part
        source_dir = self.root / "source" / "ISO" / "bolts and screws" \
            / "hex bolts and screws"
        source_dir.mkdir(parents=True)
        (source_dir / "hex screw gradeab_iso.sldprt").write_bytes(b"part")

        calls = []

        def fake_insert(sw, **kwargs):
            calls.append(kwargs)
            return {"success": True, "message": "inserted", "data": {"name": "part-1"}}

        sp.insert_component = fake_insert
        try:
            result = sp.insert_standard_part(Automation(), standard="ISO",
                                             type="hex screw")
        finally:
            sp.insert_component = _original_insert_component

        self.assertFalse(result["success"])
        self.assertEqual("SIZE_REQUIRED", result["data"]["code"])
        self.assertEqual([], calls)

    def test_scanned_fastener_size_cannot_bypass_geometry_validation(self):
        source_dir = self.root / "source" / "ISO" / "bolts and screws" \
            / "hexagon socket head screws"
        source_dir.mkdir(parents=True)
        (source_dir / "socket head cap screw_iso.sldprt").write_bytes(b"part")
        prepared = self.root / "sized" / "ISO" / "prepared.sldprt"

        def prepare(sw, lib, row, size):
            self.assertEqual("ISO 4762 M10 x 16 - 16N", size)
            prepared.parent.mkdir(parents=True, exist_ok=True)
            prepared.write_bytes(b"prepared")
            return str(prepared)

        calls = []
        sp._prepare_sized_copy = prepare
        sp.insert_component = lambda sw, **kwargs: (
            calls.append(kwargs) or
            {"success": True, "message": "inserted", "data": {"name": "x"}})
        try:
            result = sp.insert_standard_part(
                Automation(), standard="ISO", type="socket head cap",
                size="ISO 4762 M10 x 16 - 16N")
        finally:
            sp._prepare_sized_copy = _original_prepare_sized_copy
            sp.insert_component = _original_insert_component

        self.assertFalse(result["success"])
        self.assertEqual("SIZE_REQUIRES_VALIDATOR", result["data"]["code"])
        self.assertEqual([], calls)
        self.assertFalse(prepared.exists())

    def test_size_preparation_failure_reports_clean_error(self):
        sp._prepare_sized_copy = lambda sw, lib, row, size: None
        try:
            result = sp.insert_standard_part(
                Automation(), standard="ISO", type="socket head cap",
                size="ISO 4762 M10 x 16 - 16N")
        finally:
            sp._prepare_sized_copy = _original_prepare_sized_copy

        self.assertFalse(result["success"])
        self.assertEqual("SIZE_REQUIRES_VALIDATOR", result["data"]["code"])

    def test_unknown_size_reports_available_sizes(self):
        result = sp.insert_standard_part(
            Automation(), standard="ISO", type="socket head cap",
            size="M99")
        self.assertFalse(result["success"])
        self.assertEqual("SIZE_NOT_AVAILABLE", result["data"]["code"])
        self.assertEqual(2, result["data"]["available_count"])

    def test_ambiguous_without_file_reports_candidates(self):
        # two parts share the type across standards when no standard is given
        result = sp.insert_standard_part(Automation(), standard="",
                                         type="socket head cap")
        self.assertFalse(result["success"])
        self.assertEqual("AMBIGUOUS_STANDARD_PART", result["data"]["code"])
        self.assertTrue(result["data"]["candidates"])

    def test_missing_row_reports_not_found(self):
        result = sp.insert_standard_part(Automation(), standard="GB")
        self.assertFalse(result["success"])
        self.assertEqual("STANDARD_PART_NOT_FOUND", result["data"]["code"])


class StatusTests(LibraryCase):
    def test_reports_counts_and_command(self):
        result = sp.standard_library_status(Automation())
        self.assertTrue(result["success"], result["message"])
        data = result["data"]
        self.assertTrue(data["index_present"])
        self.assertEqual(3, data["index_count"])
        self.assertEqual(2, data["parts_with_sizes"])
        self.assertIn("sync_standard_library.py", data["rebuild_command"])


_original_insert_component = sp.insert_component
_original_prepare_sized_copy = sp._prepare_sized_copy

if __name__ == "__main__":
    unittest.main()
