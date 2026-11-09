import unittest

from solidworks_mcp.workspace.selectors import (
    AmbiguousEntityError,
    EntityRef,
    resolve_entity,
)


class EntitySelectionTests(unittest.TestCase):
    def test_resolves_repeated_component_by_exact_instance_path(self):
        reference = EntityRef(
            document_id="assembly-1", revision="r4", configuration="Default",
            entity_kind="body", instance_path="Frame/Leg-2", entity_name="Body<1>",
        )
        candidates = [
            {"document_id": "assembly-1", "revision": "r4", "configuration": "Default",
             "entity_kind": "body", "instance_path": "Frame/Leg-1", "entity_name": "Body<1>"},
            {"document_id": "assembly-1", "revision": "r4", "configuration": "Default",
             "entity_kind": "body", "instance_path": "Frame/Leg-2", "entity_name": "Body<1>"},
        ]

        self.assertEqual(candidates[1], resolve_entity(reference, candidates))

    def test_rejects_suffix_matching_that_could_pick_wrong_instance(self):
        reference = EntityRef(
            document_id="assembly-1", revision="r4", configuration="Default",
            entity_kind="body", instance_path="Leg-2", entity_name="Body<1>",
        )
        candidates = [
            {"document_id": "assembly-1", "revision": "r4", "configuration": "Default",
             "entity_kind": "body", "instance_path": "Frame/Leg-2", "entity_name": "Body<1>"},
        ]

        with self.assertRaises(AmbiguousEntityError):
            resolve_entity(reference, candidates)


if __name__ == "__main__":
    unittest.main()
