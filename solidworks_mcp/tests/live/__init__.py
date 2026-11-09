"""Opt-in live SolidWorks COM tests.

SolidWorks does not return the graphics memory of a closed document window
until it restarts: about 36 MB per document when the last window closes (the
whole graphics area is rebuilt), about 8 MB while another window stays open.
A full live run opens hundreds of scratch documents, so discovery of this
package keeps one empty, unsaved anchor part open for the whole run.  The
anchor is never saved and is closed after the last live test.
"""

import os
import unittest


class _GraphicsAnchorSuite(unittest.TestSuite):
    def run(self, result, debug=False):
        app, title = _open_anchor()
        try:
            return super().run(result, debug)
        finally:
            if app is not None:
                try:
                    app.CloseDoc(title)
                except Exception:
                    pass


def _open_anchor():
    try:
        import win32com.client

        app = win32com.client.GetActiveObject("SldWorks.Application")
        # swDefaultTemplatePart = 8
        document = app.NewDocument(app.GetUserPreferenceStringValue(8), 0, 0, 0)
        return app, document.GetTitle
    except Exception:
        return None, None


def load_tests(loader, standard_tests, pattern):
    this_dir = os.path.dirname(__file__)
    standard_tests.addTests(loader.discover(start_dir=this_dir, pattern=pattern or "test*.py"))
    if os.environ.get("SW_MCP_LIVE_TESTS") != "1":
        return standard_tests
    return _GraphicsAnchorSuite([standard_tests])
