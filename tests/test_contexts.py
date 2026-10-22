import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from contexts import DEFAULT_CONTEXT, CONTEXTS
from pipeline import translate
from gui import App

class ContextTests(unittest.TestCase):
    def test_default_math_is_one_request_with_previous_context(self):
        requests=[]
        def fake(req,**kwargs):
            requests.append(json.loads(req.data))
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':'Множество'}}]}).encode())
        with patch('pipeline.urllib.request.urlopen',side_effect=fake):
            translate('fake','קבוצה','הוכחה')
        self.assertEqual(len(requests),1)
        self.assertIn('Mathematics lecture',requests[0]['messages'][0]['content'])
        self.assertIn('uncertain letters',requests[0]['messages'][0]['content'])
        self.assertIn('הוכחה',requests[0]['messages'][1]['content'])
        with patch('pipeline.urllib.request.urlopen',side_effect=fake):
            translate('fake','שלום',translation_context='cinema')
        self.assertIn('Film or TV',requests[-1]['messages'][0]['content'])
        self.assertNotIn('Mathematics lecture',requests[-1]['messages'][0]['content'])

    def test_default_and_saved_selection_survive_restart_and_ui_language(self):
        saved={}
        with patch('gui.load_settings',side_effect=lambda:dict(saved)),patch('gui.save_settings',side_effect=lambda data:saved.update(data)),patch('gui.load_key',return_value=''),patch('gui.outputs',return_value=[]):
            app=App()
            try:
                self.assertEqual(app.translation_context,'math')
                app.advanced()
                frame=app.advanced_window.winfo_children()[0]
                box=next(w for w in frame.winfo_children() if 'values' in w.keys() and tuple(w.cget('values'))==tuple(v[0] for v in CONTEXTS.values()))
                box.current(list(CONTEXTS).index('news'))
                box.event_generate('<<ComboboxSelected>>');app.root.update()
                self.assertEqual(saved['translation_context'],'news')
                app.set_ui_language('fr')
                self.assertEqual(box.current(),list(CONTEXTS).index('news'))
            finally:app.root.destroy()
            app=App()
            try:self.assertEqual(app.translation_context,'news')
            finally:app.root.destroy()
