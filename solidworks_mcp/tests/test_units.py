import unittest

from solidworks_mcp.core.contracts import QuantityValidationError
from solidworks_mcp.utils.units import Unit, UnitConverter


class UnitConverterContractTests(unittest.TestCase):
    def test_25_4_millimeters_equals_one_inch(self):
        converter = UnitConverter("mm")

        self.assertAlmostEqual(1.0, converter.convert(25.4, "mm", "inch"), places=12)


class UnknownUnitTests(unittest.TestCase):
    """A typo in a unit must fail loudly, not become millimetres.

    Previously an unknown unit logged a warning and fell back to millimetres,
    so ``draw_line(..., unit="furlong")`` drew a valid 50 mm line and reported
    "50.00furlong" as if the unit had been honoured.
    """

    def test_to_meters_refuses_an_unknown_unit(self):
        converter = UnitConverter("mm")

        with self.assertRaises(QuantityValidationError) as raised:
            converter.to_meters(50, "furlong")

        self.assertIn("furlong", str(raised.exception))
        self.assertIn("Supported units", str(raised.exception))

    def test_from_meters_and_convert_refuse_an_unknown_unit(self):
        converter = UnitConverter("mm")

        with self.assertRaises(QuantityValidationError):
            converter.from_meters(0.05, "furlong")
        with self.assertRaises(QuantityValidationError):
            converter.convert(50, "mm", "furlong")

    def test_a_non_string_unit_is_refused(self):
        converter = UnitConverter("mm")

        with self.assertRaises(QuantityValidationError):
            converter.to_meters(50, 42)

    def test_an_unknown_default_unit_is_refused_at_construction(self):
        with self.assertRaises(QuantityValidationError):
            UnitConverter("furlong")

    def test_none_still_means_the_document_default(self):
        converter = UnitConverter("mm")

        self.assertAlmostEqual(0.05, converter.to_meters(50), places=12)

    def test_known_units_and_aliases_still_convert(self):
        converter = UnitConverter("mm")

        cases = (("mm", 50.0, 0.05), ("millimeters", 50.0, 0.05),
                 ("cm", 5.0, 0.05), ("m", 0.05, 0.05),
                 ("inch", 1.0, 0.0254), ("in", 1.0, 0.0254),
                 ("\"", 1.0, 0.0254), ("ft", 1.0, 0.3048))
        for unit, value, expected in cases:
            with self.subTest(unit=unit):
                self.assertAlmostEqual(expected, converter.to_meters(value, unit),
                                       places=12)

    def test_a_unit_enum_is_accepted(self):
        converter = UnitConverter("mm")

        self.assertAlmostEqual(0.05, converter.to_meters(50, Unit.MILLIMETER),
                               places=12)

    def test_default_unit_can_be_switched_and_is_validated(self):
        converter = UnitConverter("mm")

        converter.default_unit = "inch"

        self.assertIs(Unit.INCH, converter.default_unit)
        self.assertAlmostEqual(0.0254, converter.to_meters(1.0), places=12)
        with self.assertRaises(QuantityValidationError):
            converter.default_unit = "furlong"


if __name__ == "__main__":
    unittest.main()
