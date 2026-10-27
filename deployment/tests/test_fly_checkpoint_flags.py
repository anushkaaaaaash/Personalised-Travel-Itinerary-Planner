import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace
spec=importlib.util.spec_from_file_location('flags',Path(__file__).parents[1]/'fly_checkpoint_flags.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.TestCase):
    def test_known_names_only(self):
        m.verify_names([{'Name':'OPENAI_API_KEY','Digest':'not a value'},{'name':'SUPABASE_URL'}])
        for value in ({},[{}],[{'Name':'bad name'}],[{'name':'ADAPTIVE_PLANNING_ENABLED'}],[{'Name':'PLANNING_JOBS_ENABLED'}]):
            with self.assertRaises(ValueError):m.verify_names(value)
    def test_no_raw_output(self):
        with patch.object(m.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout='private fixture',stderr='private fixture')),patch('builtins.print') as output:
            self.assertEqual(m.main(),1);self.assertNotIn('private fixture',str(output.call_args_list))
