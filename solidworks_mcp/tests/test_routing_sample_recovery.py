import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("routing_recovery", Path(__file__).resolve().parents[2] / "scripts/stage_native_routing_sample.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SampleRecoveryTests(unittest.TestCase):
    def test_preserves_relative_path_not_ambiguous_basename(self):
        old = MODULE.OLD / "samples/tutorial/routing-pipes"
        self.assertEqual((MODULE.SAMPLE / "filter.sldprt").resolve(), MODULE.resolve_reference(old / "filter.sldprt"))
        self.assertEqual((MODULE.SAMPLE / "fittings/filter.sldprt").resolve(), MODULE.resolve_reference(old / "fittings/filter.sldprt"))

    def test_library_prefix_is_separate(self):
        old = MODULE.OLD / "sldworks/data/design library/routing/piping/tees/tee.sldprt"
        self.assertEqual((MODULE.LIBRARY / "piping/tees/tee.sldprt").resolve(), MODULE.resolve_reference(old))

    def test_single_shipped_valve_alias_is_not_a_general_basename_search(self):
        old = Path(r"C:\Users\HC8\Desktop\Repaired Data\Ball Valve.SLDPRT")
        self.assertEqual((MODULE.SAMPLE / "fittings/Ball Valve.SLDPRT").resolve(), MODULE.resolve_reference(old))
        with self.assertRaises(ValueError):
            MODULE.resolve_reference(Path(r"C:\Users\someone\Desktop\Ball Valve.SLDPRT"))

    def test_unknown_and_escape_rejected(self):
        for path in (Path("C:/unrelated/filter.sldprt"), MODULE.OLD / "samples/tutorial/routing-pipes/../../../../other.sldprt"):
            with self.assertRaises(ValueError):
                MODULE.resolve_reference(path)

    def test_assembly_empty_and_malformed_reads_fail_closed(self):
        for raw in (None, [], ["name"], ["name", ""]):
            with self.assertRaises(ValueError):
                MODULE.decode_references(raw, MODULE.SAMPLE / "finalskid.sldasm")
        self.assertEqual([], MODULE.decode_references(None, MODULE.SAMPLE / "pipe.sldprt"))

    def test_replacement_retains_exact_original_string(self):
        raw = str(MODULE.OLD / "samples/tutorial/routing-pipes/pipe.sldprt")
        result = MODULE.decode_references(["pipe", raw], MODULE.SAMPLE / "finalskid.sldasm")
        self.assertEqual(raw, result[0][0])
        self.assertEqual((MODULE.SAMPLE / "pipe.sldprt").resolve(), result[0][1])

    def test_incomplete_or_empty_sample_graph_cannot_be_verified(self):
        root = MODULE.SAMPLE / "finalskid.sldasm"
        for graph in ({}, {root: []}, {root: [("dummy", MODULE.SAMPLE / "pipe.sldprt")]}):
            with self.assertRaises(RuntimeError):
                MODULE.require_sample_members(graph)
