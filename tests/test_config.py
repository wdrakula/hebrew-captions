import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

class KeyTests(unittest.TestCase):
    def test_shallow_install_path_does_not_crash(self):
        namespace = {'__file__': '/opt/hebrew-captions/config.py'}
        exec(compile(Path(config.__file__).read_text(), 'config.py', 'exec'), namespace)
        self.assertIsNone(namespace['KEY_FILE'])

    def test_key_source_precedence_without_reading_real_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'APIkey.txt').write_text('fake-file-key')
            with patch.object(config, 'ROOT', root), patch.object(config, 'KEY_FILE', None), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(config.load_key(), 'fake-file-key')
                (root/'.env').write_text('OPENAI_API_KEY=fake-env-file-key')
                self.assertEqual(config.load_key(), 'fake-env-file-key')
                with patch.dict(os.environ, {'OPENAI_API_KEY': 'fake-environment-key'}):
                    self.assertEqual(config.load_key(), 'fake-environment-key')
