import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from solidworks_mcp.automation.documents import DocumentOperations

class Doc:
    def __init__(self,path):self.path=path
    def GetPathName(self):return self.path
    def GetTitle(self):return Path(self.path).name

class App:
    def __init__(self,doc,activation_error=0,wrong=False):
        self.doc=doc;self.ActiveDoc=Doc('C:/other.sldasm')
        self.activation_error=activation_error;self.wrong=wrong;self.activations=0
    def OpenDoc6(self,*args):return self.doc
    def ActivateDoc3(self,name,use_preferences,rebuild,error):
        self.activations+=1
        # Mirrors dynamic COM's output parameter requirement.
        error.value=self.activation_error
        if not self.wrong:self.ActiveDoc=self.doc
        return self.doc

class SW(DocumentOperations):
    is_connected=True
    def __init__(self,app):self._sw_app=app
    def _get_doc_title(self,doc):return doc.GetTitle()
    def _result(self,success,message,error_code=0,data=None):
        return dict(success=success,message=message,data=data or {})

class OpenActivationTests(unittest.TestCase):
    def run_open(self,error=0,wrong=False):
        with TemporaryDirectory() as folder:
            p=Path(folder)/'route.sldasm';p.touch();doc=Doc(str(p));app=App(doc,error,wrong)
            with patch('solidworks_mcp.automation.documents.win32com.client.dynamic.Dispatch',return_value=app):
                result=SW(app).open_document(str(p))
            return result,app
    def test_open_existing_activates_requested_document_with_byref_error(self):
        r,app=self.run_open();self.assertTrue(r['success'],r)
        self.assertEqual(1,app.activations)
        self.assertIs(app.doc,app.ActiveDoc)
    def test_activation_native_error_is_failure(self):
        r,_=self.run_open(error=7);self.assertFalse(r['success'],r)
    def test_wrong_active_path_is_failure(self):
        r,_=self.run_open(wrong=True);self.assertFalse(r['success'],r)

if __name__=='__main__':unittest.main()
