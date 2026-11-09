import tempfile
import unittest
from pathlib import Path
from unittest import mock

from solidworks_mcp.core.policy import OperationClass, PathPolicy
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools import session
from solidworks_mcp.tools.session import close_saved_outputs, restart_solidworks, session_health


class App:
    def __init__(self):
        self.exit_calls = 0
        self.closed = []
        self.on_close = None

    def GetProcessID(self):
        return 4242

    def ExitApp(self):
        self.exit_calls += 1

    def CloseDoc(self, name):
        self.closed.append(name)
        if self.on_close is not None:
            self.on_close(name)


class Automation:
    def __init__(self, root, documents, connected=True):
        self._path_policy = PathPolicy(output_roots=[Path(root)],
                                       protected_roots=[Path(root) / "protected"])
        self.app = App()
        self.is_connected = connected
        self.documents = documents
        self.kept_loaded = set()   # paths that stay loaded after CloseDoc (referenced elsewhere)
        self.app.on_close = self._drop
        self.calls = []
        self._document_session = "bound"

    def _drop(self, path):
        if path not in self.kept_loaded:
            self.documents = [d for d in self.documents if d.get("path") != path]

    def list_open_documents(self):
        return {"success": True, "message": "",
                "data": {"documents": self.documents, "complete": True, "unresolved": []}}

    def disconnect(self):
        self.calls.append("disconnect")
        self.is_connected = False

    def connect(self):
        self.calls.append("connect")
        self.is_connected = True
        return {"success": True, "message": "Connected"}

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message,
                "error_code": int(error_code), "data": data or {}}


class RegistrationTests(unittest.TestCase):
    def test_restart_is_a_session_operation(self):
        self.assertIn("restart_solidworks", {item.name for item in registered_tools()})
        self.assertIs(OperationClass.SESSION, operation_class_for("restart_solidworks"))


class SessionHealthTests(unittest.TestCase):
    def test_disconnected_session_reports_only_that(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual({"connected": False}, session_health(Automation(root, [], False)))

    def test_connected_session_reports_monitor_counters(self):
        from solidworks_mcp.session_monitor import monitor

        with tempfile.TemporaryDirectory() as root:
            with mock.patch.object(session, "dedicated_gpu_mb", return_value=100.0),                     mock.patch.object(monitor, "snapshot",
                                      return_value={"documents_opened": 5,
                                                    "documents_closed": 4,
                                                    "gpu_dedicated_mb": 100.0}):
                health = session_health(Automation(root, []))
        self.assertEqual(4, health["counters"]["documents_closed"])

    def test_high_gpu_memory_recommends_restart(self):
        with tempfile.TemporaryDirectory() as root:
            sw = Automation(root, [{"title": "Part1", "path": ""}])
            with mock.patch.object(session, "dedicated_gpu_mb", return_value=5000.0):
                health = session_health(sw)
        self.assertEqual(4242, health["process_id"])
        self.assertEqual(1, health["open_documents"])
        self.assertTrue(health["restart_recommended"])
        self.assertIn("restart_solidworks", health["hint"])

    def test_unknown_gpu_memory_does_not_recommend_restart(self):
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.object(session, "dedicated_gpu_mb", return_value=None):
                health = session_health(Automation(root, []))
        self.assertFalse(health["restart_recommended"])


class RestartTests(unittest.TestCase):
    def _saved(self, root, name="out.SLDPRT"):
        return {"title": name, "path": str(Path(root) / name), "unsaved_changes": False}

    def test_refuses_unsaved_modified_and_foreign_documents(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as other:
            documents = [
                {"title": "Part1", "path": "", "unsaved_changes": True},
                {"title": "dirty", "path": str(Path(root) / "dirty.SLDPRT"), "unsaved_changes": True},
                {"title": "user", "path": str(Path(other) / "user.SLDASM"), "unsaved_changes": False},
                {"title": "ref", "path": str(Path(root) / "protected" / "r.SLDPRT"),
                 "unsaved_changes": False},
                self._saved(root),
            ]
            sw = Automation(root, documents)
            result = restart_solidworks(sw, confirm=True)
        self.assertFalse(result["success"])
        reasons = {item["title"]: item["reason"] for item in result["data"]["blockers"]}
        self.assertEqual({"Part1": "never saved", "dirty": "unsaved changes",
                          "user": "outside the approved output roots",
                          "ref": "outside the approved output roots"}, reasons)
        self.assertEqual(0, sw.app.exit_calls)

    def test_without_confirm_only_reports_what_would_close(self):
        with tempfile.TemporaryDirectory() as root:
            sw = Automation(root, [self._saved(root)])
            with mock.patch.object(session, "dedicated_gpu_mb", return_value=100.0):
                result = restart_solidworks(sw)
        self.assertFalse(result["success"])
        self.assertEqual(["out.SLDPRT"], result["data"]["would_close"])
        self.assertEqual(0, sw.app.exit_calls)

    def test_confirmed_restart_exits_waits_and_reconnects(self):
        with tempfile.TemporaryDirectory() as root:
            sw = Automation(root, [self._saved(root)])
            with mock.patch.object(session, "dedicated_gpu_mb", return_value=100.0), \
                    mock.patch.object(session, "_wait_for_exit", return_value=True) as wait:
                result = restart_solidworks(sw, confirm=True)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(1, sw.app.exit_calls)
        wait.assert_called_once_with(4242, 60)
        self.assertEqual(["disconnect", "connect"], sw.calls)
        self.assertNotEqual("bound", sw._document_session)
        self.assertEqual(["out.SLDPRT"], result["data"]["closed"])

    def test_process_that_does_not_exit_is_not_reconnected(self):
        with tempfile.TemporaryDirectory() as root:
            sw = Automation(root, [])
            with mock.patch.object(session, "dedicated_gpu_mb", return_value=100.0), \
                    mock.patch.object(session, "_wait_for_exit", return_value=False):
                result = restart_solidworks(sw, confirm=True)
        self.assertFalse(result["success"])
        self.assertIn("did not exit", result["message"])
        self.assertEqual(["disconnect"], sw.calls)

    def test_not_connected_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            result = restart_solidworks(Automation(root, [], False), confirm=True)
        self.assertFalse(result["success"])


class CloseSavedOutputsTests(unittest.TestCase):
    def _documents(self, root, other):
        return [
            {"title": "Part1", "path": "", "unsaved_changes": True},
            {"title": "out.SLDPRT", "path": str(Path(root) / "out.SLDPRT"), "unsaved_changes": False},
            {"title": "user.SLDASM", "path": str(Path(other) / "user.SLDASM"),
             "unsaved_changes": False},
        ]

    def test_registered_as_session_operation(self):
        self.assertIs(OperationClass.SESSION, operation_class_for("close_saved_outputs"))

    def test_without_confirm_only_lists(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as other:
            sw = Automation(root, self._documents(root, other))
            result = close_saved_outputs(sw)
        self.assertTrue(result["success"])
        self.assertEqual(["out.SLDPRT"], [item["title"] for item in result["data"]["would_close"]])
        self.assertEqual(2, len(result["data"]["kept"]))
        self.assertEqual([], sw.app.closed)

    def test_confirm_closes_only_saved_outputs(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as other:
            sw = Automation(root, self._documents(root, other))
            result = close_saved_outputs(sw, confirm=True)
            expected = str(Path(root) / "out.SLDPRT")
        self.assertTrue(result["success"])
        self.assertEqual([expected], sw.app.closed)
        self.assertEqual(["out.SLDPRT"], result["data"]["closed"])

    def test_assembly_is_kept_while_a_part_has_unsaved_changes(self):
        with tempfile.TemporaryDirectory() as root:
            documents = [
                {"title": "dirty.SLDPRT", "path": str(Path(root) / "dirty.SLDPRT"),
                 "unsaved_changes": True},
                {"title": "asm.SLDASM", "path": str(Path(root) / "asm.SLDASM"),
                 "unsaved_changes": False},
                {"title": "part.SLDPRT", "path": str(Path(root) / "part.SLDPRT"),
                 "unsaved_changes": False},
            ]
            sw = Automation(root, documents)
            listing = close_saved_outputs(sw)
            result = close_saved_outputs(sw, confirm=True)
            part = str(Path(root) / "part.SLDPRT")
        self.assertEqual(["part.SLDPRT"], [d["title"] for d in listing["data"]["would_close"]])
        self.assertEqual([part], sw.app.closed)
        self.assertEqual(["part.SLDPRT"], result["data"]["closed"])
        reasons = {item["title"]: item["reason"] for item in result["data"]["kept"]}
        self.assertEqual("unsaved changes", reasons["dirty.SLDPRT"])
        self.assertEqual("depends on unsaved dirty.SLDPRT", reasons["asm.SLDASM"])

    def test_document_changed_since_listing_is_not_closed(self):
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root) / "out.SLDPRT")
            sw = Automation(root, [{"title": "out.SLDPRT", "path": path, "unsaved_changes": False}])
            first = sw.list_open_documents

            def listing_then_edit():
                result = first()
                sw.documents = [{"title": "out.SLDPRT", "path": path, "unsaved_changes": True}]
                return result

            sw.list_open_documents = listing_then_edit
            result = close_saved_outputs(sw, confirm=True)
        self.assertEqual([], sw.app.closed)
        self.assertEqual([], result["data"]["closed"])
        self.assertEqual("changed since listing",
                         {i["title"]: i["reason"] for i in result["data"]["kept"]}["out.SLDPRT"])

    def test_document_that_stays_loaded_is_reported_as_kept(self):
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root) / "out.SLDPRT")
            sw = Automation(root, [{"title": "out.SLDPRT", "path": path, "unsaved_changes": False}])
            sw.kept_loaded.add(path)
            result = close_saved_outputs(sw, confirm=True)
        self.assertEqual([], result["data"]["closed"])
        self.assertEqual("still loaded (referenced)",
                         {i["title"]: i["reason"] for i in result["data"]["kept"]}["out.SLDPRT"])

    def test_incomplete_listing_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            sw = Automation(root, [])
            sw.list_open_documents = lambda: {"success": True, "message": "",
                                              "data": {"documents": [], "complete": False}}
            result = close_saved_outputs(sw, confirm=True)
        self.assertFalse(result["success"])

    def test_not_connected_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertFalse(close_saved_outputs(Automation(root, [], False))["success"])


if __name__ == "__main__":
    unittest.main()
