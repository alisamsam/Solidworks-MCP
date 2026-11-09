import tempfile
import unittest
from pathlib import Path

from solidworks_mcp.stdlib_sync import (
    DEFAULT_DATA_ROOTS,
    STANDARD_IDS,
    build_catalog,
    find_data_root,
    normalize_type,
    walk_standards,
)


def _make_toolbox(root: Path, standards=("ISO", "DIN")):
    (root / "browser").mkdir(parents=True)
    for std in standards:
        base = root / "browser" / std
        keys = base / "bolts and screws" / "hex bolts and screws"
        keys.mkdir(parents=True)
        (keys / f"hex screw gradeab_{std.lower()}.sldprt").write_bytes(b"")
        (keys / f"hex bolt gradeab_{std.lower()}.sldprt").write_bytes(b"")
        nuts = base / "nuts" / "hex nuts"
        nuts.mkdir(parents=True)
        (nuts / f"hex nut style 1 gradeab_{std.lower()}.sldprt").write_bytes(b"")
        # a file that is not a part must be ignored
        (nuts / "readme.txt").write_text("not a part")
    # custom favourites tree
    custom = root / "Toolbox" / "ISO" / "washers" / "plain washers"
    custom.mkdir(parents=True)
    (custom / "plain washer normal grade a_iso.sldprt").write_bytes(b"")


class NormalizeTypeTests(unittest.TestCase):
    def test_strips_the_standard_suffix(self):
        self.assertEqual(
            "hex screw gradeab",
            normalize_type("hex screw gradeab_iso.sldprt", "iso"),
        )

    def test_ansi_metric_suffix(self):
        self.assertEqual(
            "socket head cap screw",
            normalize_type("socket head cap screw_am.sldprt", "ansi metric"),
        )

    def test_file_without_known_suffix_is_kept(self):
        self.assertEqual(
            "my part",
            normalize_type("my part.sldprt", "iso"),
        )


class WalkStandardsTests(unittest.TestCase):
    def test_unknown_folder_is_not_a_standard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "browser" / "lang").mkdir(parents=True)  # not a standard
            (root / "browser" / "ISO").mkdir(parents=True)
            found = walk_standards(directory, None)
            self.assertEqual(["ISO"], [f for _, f, _ in found])

    def test_standard_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _make_toolbox(root)
            found = walk_standards(directory, ["DIN"])
            self.assertEqual(["DIN"], [f for _, f, _ in found])


class BuildCatalogTests(unittest.TestCase):
    def test_catalog_walk_covers_browser_and_custom(self):
        with tempfile.TemporaryDirectory() as directory:
            _make_toolbox(Path(directory))
            rows = build_catalog(directory)
            rels = {r["rel"] for r in rows}
            self.assertIn(
                "bolts and screws/hex bolts and screws/hex screw gradeab_iso.sldprt",
                rels,
            )
            self.assertIn(
                "bolts and screws/hex bolts and screws/hex bolt gradeab_din.sldprt",
                rels,
            )
            # custom favourites tree is included with source=custom
            custom = [r for r in rows if r["source"] == "custom"]
            self.assertEqual(1, len(custom))
            self.assertTrue(custom[0]["rel"].endswith(
                "plain washer normal grade a_iso.sldprt"))
            # no .txt rows
            self.assertTrue(all(r["file"].endswith(".sldprt") for r in rows))

    def test_standard_id_is_canonical(self):
        with tempfile.TemporaryDirectory() as directory:
            _make_toolbox(Path(directory))
            rows = build_catalog(directory)
            stds = {r["standard"] for r in rows}
            self.assertIn("ISO", stds)
            self.assertIn("DIN", stds)
            self.assertTrue(stds <= set(STANDARD_IDS.values()))

    def test_filter_limits_standards(self):
        with tempfile.TemporaryDirectory() as directory:
            _make_toolbox(Path(directory))
            rows = build_catalog(directory, ["ISO"])
            self.assertTrue(all(r["standard"] == "ISO" for r in rows))


class FindDataRootTests(unittest.TestCase):
    def test_override_wins(self):
        self.assertEqual(r"C:\x", find_data_root(r"C:\x", registry_reader=lambda: None))

    def test_registry_reader_is_used_when_no_override(self):
        hit = []

        def reader():
            hit.append(True)
            return r"C:\real"

        result = find_data_root(None, registry_reader=reader)
        self.assertEqual(r"C:\real", result)
        self.assertEqual([True], hit)

    def test_falls_back_to_defaults(self):
        def reader():
            return None

        # no override, no registry -> first existing default wins, else ""
        result = find_data_root(None, registry_reader=reader)
        self.assertTrue(result == "" or result in DEFAULT_DATA_ROOTS)


if __name__ == "__main__":
    unittest.main()