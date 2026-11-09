import unittest

from solidworks_mcp.inspection.documents import inspect_dependencies


class Extension:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def GetDependencies(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return self.payload


class Document:
    def __init__(self, payload=None, extension_error=None, fallback=None):
        self.Extension = Extension(payload, extension_error)
        self.fallback = fallback
        self.fallback_calls = []

    def GetDependencies2(self, *args):
        self.fallback_calls.append(args)
        return self.fallback


class DependencyInspectionTests(unittest.TestCase):
    def test_parses_name_path_pairs_from_extension_api(self):
        document = Document(("Bracket-1", r"C:\project\Bracket.SLDPRT",
                             "Layout", r"C:\project\Layout.SLDPRT"))

        report = inspect_dependencies(document)

        self.assertEqual("IModelDocExtension.GetDependencies", report["source_method"])
        self.assertEqual((True, False, False, True, True), document.Extension.calls[0])
        self.assertEqual(2, len(report["dependencies"]))
        self.assertEqual(r"C:\project\Bracket.SLDPRT", report["dependencies"][0]["path"])
        self.assertEqual("known", report["dependencies"][0]["state"])
        self.assertEqual([], report["unresolved"])

    def test_keeps_broken_reference_with_empty_path(self):
        report = inspect_dependencies(Document(("MissingPart-1", "")))

        self.assertEqual(1, len(report["dependencies"]))
        self.assertIsNone(report["dependencies"][0]["path"])
        self.assertEqual("unresolved", report["dependencies"][0]["state"])
        self.assertIn("MissingPart-1", report["unresolved"][0])

    def test_odd_payload_keeps_final_name_as_unresolved(self):
        report = inspect_dependencies(Document(("Part-1", r"C:\Part.SLDPRT", "Orphan")))

        self.assertEqual(2, len(report["dependencies"]))
        self.assertEqual("Orphan", report["dependencies"][1]["name"])
        self.assertEqual("unresolved", report["dependencies"][1]["state"])
        self.assertFalse(report["complete"])

    def test_falls_back_only_after_extension_failure_and_records_it(self):
        document = Document(
            extension_error=RuntimeError("new API unavailable"),
            fallback=("LegacyPart", r"C:\legacy\Part.SLDPRT"),
        )

        report = inspect_dependencies(document)

        self.assertEqual("IModelDoc2.GetDependencies2", report["source_method"])
        self.assertEqual([(True, False, False)], document.fallback_calls)
        self.assertIn("fallback", report["evidence"][0].lower())


if __name__ == "__main__":
    unittest.main()
