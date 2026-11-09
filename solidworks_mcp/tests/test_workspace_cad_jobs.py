import tempfile,unittest
from pathlib import Path
from solidworks_mcp.workspace.parameter_store import ParameterStore,Conflict,ValidationError

class CadJobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=ParameterStore(Path(self.tmp.name)/'db.sqlite3')
        self.p=self.s.create_project('CAD')['id']
        owner=self.s.add_owner(self.p,{'kind':'part','name':'plate'})
        self.param=self.s.add_parameter(self.p,{'owner_id':owner['id'],'key':'width','label':'width','value_type':'number','unit':'mm','role':'input','observed_value':100,'binding':{'kind':'dimension','document_path':'copy.SLDPRT','configuration':'Default','name':'D1@Sketch1'}})
        self.s.set_draft(self.p,self.param['id'],120)
    def test_claim_is_exclusive_and_success_updates_observed(self):
        revision=self.s.snapshot(self.p)['revision']
        job=self.s.queue_cad_job(self.p,revision)
        self.s.claim_cad_job(self.p,job['id'])
        with self.assertRaises(Conflict):self.s.claim_cad_job(self.p,job['id'])
        self.s.finish_cad_job(self.p,job['id'],{'success':True,'data':{'saved':True}})
        p=self.s.snapshot(self.p)['parameters'][0]
        self.assertEqual(p['observed_value'],120);self.assertFalse(p['has_draft'])
    def test_later_draft_preserved(self):
        job=self.s.queue_cad_job(self.p,self.s.snapshot(self.p)['revision'])
        self.s.claim_cad_job(self.p,job['id'])
        self.s.set_draft(self.p,self.param['id'],130)
        self.s.finish_cad_job(self.p,job['id'],{'success':True})
        p=self.s.snapshot(self.p)['parameters'][0]
        self.assertEqual(p['observed_value'],120);self.assertEqual(p['draft_value'],130)
    def test_failed_job_never_updates_observed(self):
        job=self.s.queue_cad_job(self.p,self.s.snapshot(self.p)['revision'])
        self.s.claim_cad_job(self.p,job['id'])
        self.s.finish_cad_job(self.p,job['id'],{'success':False})
        self.assertEqual(self.s.snapshot(self.p)['parameters'][0]['observed_value'],100)
    def test_stale_revision_rejected(self):
        with self.assertRaises(Conflict):self.s.queue_cad_job(self.p,0)
