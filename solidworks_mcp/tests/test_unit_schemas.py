import asyncio
import unittest

from solidworks_mcp import server

LINEAR_UNITS = ["mm", "cm", "m", "inch"]
CANONICAL = {"type": "string", "enum": LINEAR_UNITS, "default": "mm"}
SESSION_DEFAULT = {"type": "string", "enum": LINEAR_UNITS}

# Units of another quantity or a wider dimension vocabulary, not linear model units.
DOMAIN_UNIT_TOOLS = {
    "set_units", "set_model_dimension", "edit_mate",
    "apply_force_load", "apply_pressure_load", "get_displacement_results", "get_reaction_results",
}


def _without_description(schema):
    return {key: value for key, value in schema.items() if key != "description"}


class UnitSchemaTests(unittest.TestCase):
    def test_linear_unit_fields_share_one_vocabulary(self):
        for item in asyncio.run(server.list_tools()):
            unit = item.inputSchema.get("properties", {}).get("unit")
            if unit is None or item.name in DOMAIN_UNIT_TOOLS:
                continue
            with self.subTest(tool=item.name):
                self.assertIn(_without_description(unit), (CANONICAL, SESSION_DEFAULT))


if __name__ == "__main__":
    unittest.main()
