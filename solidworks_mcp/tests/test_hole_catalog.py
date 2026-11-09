"""Generated Hole Wizard library: read-only queries and source provenance."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import copy
import unittest
from unittest.mock import patch

from scripts.build_hole_wizard_catalog import build_catalog
from solidworks_mcp.tools.hole_catalog import list_hole_wizard_sizes
from solidworks_mcp.tests.test_advanced_features import Automation

class HoleCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.db=self.root/'toolbox.sldedb'
        db=sqlite3.connect(self.db)
        for table in ('DIN_Type_Holes','DIN_TYPE_BS'):
            db.execute('create table '+table+' (SWconst_Enum_Value int,enabled int,Name text,DataTable text)')
        db.execute("insert into DIN_Type_Holes values (72,1,'Drill sizes','+DATA_HW_DrillSizes')")
        db.executemany('insert into DIN_TYPE_BS values (?,?,?,?)',[(67,1,'Cap (912)','+DATA_CAP'),(68,1,'CTSK (7991)','+DATA_CSK')])
        db.execute('create table DIN_DATA_HW_DrillSizes (SIZE text,DIAMETER text,enabled int)')
        db.executemany('insert into DIN_DATA_HW_DrillSizes values (?,?,?)',[('Ø6.0','6',1),('Ø8.0','8',1),('Ø10.0','10',0)])
        db.execute('create table DIN_DATA_HW_ScrewClearances (SIZE text,CLOSE_FIT text,NORMAL_FIT text,LOOSE_FIT text,enabled int)')
        db.execute("insert into DIN_DATA_HW_ScrewClearances values ('M6','6.4','6.6','7',1)")
        db.execute('create table DIN_DATA_CAP (SIZE text,DIAMETER text,CBORE_DIA text,CBORE_DEPTH text,HEAD_DIA text,enabled int)')
        db.execute("insert into DIN_DATA_CAP values ('M6','6','11','6.4','10',1)")
        db.execute('create table DIN_DATA_CSK (SIZE text,DIAMETER text,HEAD_DIA text,HEAD_ANG text,COUNTERSINK_DIAMETER text,enabled int)')
        db.execute("insert into DIN_DATA_CSK values ('M6','6','12','90','13.71',1)")
        db.commit();db.close()
    def build(self):return build_catalog(self.db,standards=['din'])
    def publish(self,payload):
        (self.root/'hole_wizard.json').write_text(json.dumps(payload),encoding='utf-8')
    def test_build_does_not_modify_source_and_preserves_hole_vs_fastener_dimensions(self):
        before=self.db.read_bytes();payload=self.build();self.assertEqual(before,self.db.read_bytes())
        self.assertEqual(3,len(payload['families']))
        cb=next(f for f in payload['families'] if f['hole_type']=='counterbore')
        self.assertEqual((4,67),(cb['standard_index'],cb['fastener_type_index']))
        self.assertEqual(6.6,cb['rows'][0]['clearance_mm']['normal'])
        self.assertEqual(11,cb['rows'][0]['counterbore_diameter_mm'])
        cs=next(f for f in payload['families'] if f['hole_type']=='countersink')['rows'][0]
        self.assertEqual(12,cs['fastener_head_diameter_mm']);self.assertEqual(13.71,cs['countersink_diameter_mm'])
        self.assertFalse(payload['native_geometry_verified'])
    def test_disabled_sizes_excluded(self):
        f=next(f for f in self.build()['families'] if f['hole_type']=='drill')
        self.assertEqual(['Ø6.0','Ø8.0'],[r['catalog_size'] for r in f['rows']])
    def test_exact_size_and_pagination_need_no_cad(self):
        self.publish(self.build());sw=Automation()
        with patch.dict(os.environ,{'SW_MCP_STANDARD_LIBRARY':str(self.root)}):
            r=list_hole_wizard_sizes(sw,standard='din',hole_type='drill',limit=1)
            self.assertTrue(r['success'],r);self.assertEqual(2,r['data']['total_matches']);self.assertEqual(1,r['data']['next_offset'])
            r=list_hole_wizard_sizes(sw,standard='din',hole_type='drill',catalog_size='Ø8.0')
            self.assertEqual(8,r['data']['rows'][0]['diameter_mm']);self.assertEqual(0,sw.active_doc_calls)
    def test_missing_snapshot_and_missing_family_are_clear_failures(self):
        with patch.dict(os.environ,{'SW_MCP_STANDARD_LIBRARY':str(self.root)}):
            self.assertFalse(list_hole_wizard_sizes(Automation())['success'])
            self.publish(self.build())
            self.assertFalse(list_hole_wizard_sizes(Automation(),standard='iso')['success'])
    def test_invalid_query_rejected_without_library_read(self):
        for kwargs in [dict(standard='unknown'),dict(hole_type='tap'),dict(limit=True),dict(offset=-1),dict(limit=101),dict(catalog_size=5)]:
            with self.subTest(kwargs=kwargs):
                self.assertFalse(list_hole_wizard_sizes(Automation(),**kwargs)['success'])
    def test_invalid_numeric_data_is_not_published(self):
        db=sqlite3.connect(self.db);db.execute("update DIN_DATA_CAP set CBORE_DEPTH='nan'");db.commit();db.close()
        with self.assertRaises(ValueError):self.build()
    def test_duplicate_size_is_not_silently_overwritten(self):
        db=sqlite3.connect(self.db);db.execute("insert into DIN_DATA_HW_DrillSizes values ('Ø6.0','6.1',1)");db.commit();db.close()
        with self.assertRaises(ValueError):self.build()
    def test_malformed_snapshot_shapes_units_and_provenance_are_rejected(self):
        valid=self.build()
        for change in ('scalar_dict','missing_dimension','wrong_units','missing_hash','bad_clearance','boolean_id'):
            with self.subTest(change=change):
                payload=copy.deepcopy(valid)
                if change=='scalar_dict':payload['families'][0]['rows'][0]['diameter_mm']={}
                if change=='missing_dimension':payload['families'][0]['rows'][0].pop('diameter_mm')
                if change=='wrong_units':payload['units']='inches'
                if change=='missing_hash':payload.pop('source_sha256')
                if change=='bad_clearance':payload['families'][1]['rows'][0]['clearance_mm']={}
                if change=='boolean_id':payload['families'][0]['standard_index']=True
                self.publish(payload)
                with patch.dict(os.environ,{'SW_MCP_STANDARD_LIBRARY':str(self.root)}):
                    self.assertFalse(list_hole_wizard_sizes(Automation(),standard='din')['success'])
    def test_active_wal_source_is_refused_without_modification(self):
        db=sqlite3.connect(self.db)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute("update DIN_DATA_HW_DrillSizes set DIAMETER='6.25' where SIZE='Ø6.0'");db.commit()
            with self.assertRaisesRegex(ValueError,'WAL'):self.build()
        finally:db.close()

if __name__=='__main__':unittest.main()
