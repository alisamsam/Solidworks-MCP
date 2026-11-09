import unittest
from types import SimpleNamespace
from solidworks_mcp.automation.documents import DocumentOperations
class Doc:
 def __init__(self,path,following=None):self.path=path;self.following=following
 def GetTitle(self):return 'same title'
 def GetType(self):return 2
 def GetPathName(self):return self.path
 def GetSaveFlag(self):return True
 def GetNext(self):return self.following
class SW(DocumentOperations):
 is_connected=True
 def __init__(self,first):self._sw_app=SimpleNamespace(GetFirstDocument=first)
 def _result(self,success,message,error_code=0,data=None):return {'success':success,'data':data or {}}
class InventoryTests(unittest.TestCase):
 def test_same_titles_preserve_exact_paths_and_unsaved_state(self):
  r=SW(Doc('one.SLDASM',Doc('two.SLDASM'))).list_open_documents()
  self.assertTrue(r['success'])
  self.assertEqual(['one.SLDASM','two.SLDASM'],[d['path'] for d in r['data']['documents']])
  self.assertTrue(all(d['unsaved_changes'] for d in r['data']['documents']))
 def test_missing_optional_save_flag_keeps_document_with_unknown_state(self):
  class Partial(Doc):
   def GetSaveFlag(self):raise RuntimeError('unavailable')
  r=SW(Partial('one.SLDASM')).list_open_documents()
  self.assertEqual('one.SLDASM',r['data']['documents'][0]['path'])
  self.assertIsNone(r['data']['documents'][0]['unsaved_changes'])
  self.assertFalse(r['data']['complete'])
