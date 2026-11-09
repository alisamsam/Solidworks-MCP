import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SCRIPTS=Path(__file__).resolve().parents[2]/"scripts"
SPEC=importlib.util.spec_from_file_location("saved_socket_example",SCRIPTS/"verify_routing07_example.py")
MODULE=importlib.util.module_from_spec(SPEC)
with patch.object(sys,"path",[str(SCRIPTS),*sys.path]): SPEC.loader.exec_module(MODULE)


class Document:
    def __init__(self,dirty=False): self.dirty=dirty
    def GetSaveFlag(self): return self.dirty


class SavedExampleTests(unittest.TestCase):
    def test_dirty_assembly_and_part_are_rejected(self):
        for label in ("assembly before read","referenced part before read"):
            with self.assertRaises(RuntimeError): MODULE.require_clean_document(Document(True),label)

    def test_changed_state_after_read_is_rejected(self):
        doc=Document()
        MODULE.require_clean_document(doc,"before")
        doc.dirty=True
        with self.assertRaises(RuntimeError): MODULE.require_clean_document(doc,"after")

    def test_unreadable_clean_state_is_not_assumed(self):
        with self.assertRaises(RuntimeError): MODULE.require_clean_document(Document(None),"part")

    def test_reversed_second_instance_fails_even_if_translation_is_right(self):
        transform=[1.,0.,0.,0.,1.,0.,0.,0.,1.,1.158,0.,0.,1.,0.,0.,0.]
        MODULE.verify_placement(transform,True,1.158)
        transform[:9]=[-1.,0.,0.,0.,-1.,0.,0.,0.,1.]
        with self.assertRaises(RuntimeError): MODULE.verify_placement(transform,True,1.158)

    def test_gap_requires_opposition_and_matching_nominal_data(self):
        gap={"success":True,"data":{"measurement":{"distance_mm":100.,"direction_dot":-1.,
             "opposition_angle_deg":0.,"diameter_difference_mm":0.,"route_type_equal":True}}}
        MODULE.verify_gap(gap)
        for key,value in (("opposition_angle_deg",180.),("direction_dot",1.),
                          ("diameter_difference_mm",1.),("route_type_equal",False)):
            old=gap["data"]["measurement"][key]
            gap["data"]["measurement"][key]=value
            with self.assertRaises(RuntimeError): MODULE.verify_gap(gap)
            gap["data"]["measurement"][key]=old
