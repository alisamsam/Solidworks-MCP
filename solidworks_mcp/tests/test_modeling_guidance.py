import asyncio
import json
import unittest
from unittest.mock import patch

from solidworks_mcp import server
from solidworks_mcp.knowledge import library


class ModelingGuidanceTests(unittest.TestCase):
    def test_initialization_exposes_instructions_and_resources(self):
        options = server.server.create_initialization_options()
        self.assertIn('get_modeling_guide', options.instructions)
        self.assertIsNotNone(options.capabilities.resources)

    def test_every_catalog_entry_can_be_read(self):
        entries = library.catalog()
        self.assertGreater(len(entries), 25)
        self.assertEqual(len(entries), len({e['id'] for e in entries}))
        for entry in entries:
            with self.subTest(topic=entry['id']):
                topic = library.topic_for_uri(entry['uri'])
                data = library.read_topic(topic, set())
                self.assertTrue(data['content'].strip())
                self.assertEqual(data['topic'], topic)

    def test_guide_distinguishes_recommended_and_available_tools(self):
        data = library.read_topic('workflow/part', {'create_sketch'})
        self.assertIn('create_sketch', data['available_tools'])
        self.assertIn('extrude_sketch', data['unavailable_tools'])
        self.assertEqual(data['guide_status'], 'guidance_not_live_workflow_verification')

    def test_unknown_or_external_paths_are_rejected(self):
        for name in ['../../config.json', 'C:/Windows/win.ini', 'missing', '']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                library.read_topic(name, set())
        for uri in ['file:///C:/Windows/win.ini', 'solidworks://guides/../../config.json',
                    'solidworks://other/expert', 'solidworks://guides/expert?file=secret']:
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                library.topic_for_uri(uri)

    def test_tool_and_resource_serve_same_source_without_touching_cad(self):
        with patch.object(server.sw_automation, 'get_active_doc', side_effect=AssertionError('CAD touched')):
            response = asyncio.run(server.call_tool('get_modeling_guide', {'topic': 'workflow/part'}))
            self.assertIn('[SUCCESS]', response[0].text)
            resources = asyncio.run(server.read_modeling_resource('solidworks://guides/workflow/part'))
        data = json.loads(list(resources)[0].content)
        self.assertIn(data['content_sha256'], response[0].text)
        self.assertIn('extrude_sketch', data['available_tools'])

    def test_invalid_tool_topic_returns_error_not_cad_action(self):
        response = asyncio.run(server.call_tool('get_modeling_guide', {'topic': '../config.json'}))
        self.assertIn('[ERROR]', response[0].text)

    def test_resource_index_matches_topic_catalog(self):
        resources = asyncio.run(server.list_modeling_resources())
        expected = {entry['uri'] for entry in library.catalog()} | {'solidworks://guides/index'}
        self.assertEqual({str(r.uri) for r in resources}, expected)

    def test_expert_links_resolve_to_registered_resources(self):
        data = library.read_topic('expert', set())
        self.assertIn('solidworks://guides/reference/detail-levels', data['content'])
        self.assertIn('modules/07-weldments', data['related_topics'])


if __name__ == '__main__':
    unittest.main()
