import unittest

from solidworks_mcp.workspace.drawing_contracts import (
    DrawingLayoutError,
    DrawingViewRef,
    validate_drawing_layout,
)


class DrawingContractTests(unittest.TestCase):
    def test_configuration_and_revision_are_preserved_for_each_view(self):
        view = DrawingViewRef(
            view_id="front", document_id="stair-assembly", revision="r7",
            configuration="Manufacturing", orientation="Front",
            center_x_mm=100, center_y_mm=80, width_mm=60, height_mm=40,
        )

        validated = validate_drawing_layout([view], sheet_width_mm=297, sheet_height_mm=210)

        self.assertEqual("Manufacturing", validated[0].configuration)
        self.assertEqual("r7", validated[0].revision)

    def test_overlapping_views_are_rejected_before_drawing_mutation(self):
        views = [
            DrawingViewRef("front", "stair", "r7", "Default", "Front", 100, 80, 80, 60),
            DrawingViewRef("right", "stair", "r7", "Default", "Right", 120, 80, 80, 60),
        ]

        with self.assertRaises(DrawingLayoutError):
            validate_drawing_layout(views, sheet_width_mm=297, sheet_height_mm=210)


if __name__ == "__main__":
    unittest.main()
