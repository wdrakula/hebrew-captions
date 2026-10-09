from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gui import App

class LanguageUITests(unittest.TestCase):
    def test_pair_settings_and_pause_controls(self):
        with patch('gui.load_settings',return_value={'source_language':'fr','target_language':'en','translator':'gpt-4.1-mini'}), patch('gui.load_key',return_value=''), patch('gui.save_settings') as save:
            app=App()
            try:
                self.assertEqual(app.source_language.get(),'Французский')
                self.assertEqual(app.target_language.get(),'Английский')
                app.languages_changed()
                self.assertEqual(save.call_args.args[0]['translator'],'gpt-4.1-mini')
                self.assertEqual(save.call_args.args[0]['source_language'],'fr')
                # Simulate a running worker without capturing or sending anything.
                with patch.object(app,'active',return_value=True):
                    app.advanced()
                    self.assertIsNone(app.advanced_window)
                app.history.append({'he':'Bonjour','ru':'Hello'})
                app.history.set_hebrew(True)
                content=app.history.text.get('1.0','end')
                self.assertIn('Bonjour',content)
                self.assertIn('Hello',content)
            finally:
                app.root.destroy()

    def test_start_locks_languages_until_finished_event(self):
        with patch('gui.load_settings',return_value={}), patch('gui.load_key',return_value='fake'), patch('gui.save_settings'), patch('gui.threading.Thread.start'):
            app=App()
            try:
                app.start()
                self.assertTrue(all(str(box.cget('state'))=='disabled' for box in app.language_boxes))
                closed=[]
                class Log:
                    def close(self): closed.append(True)
                app.events.put(('finished',Log()))
                app.poll()
                self.assertTrue(closed)
                self.assertTrue(all(str(box.cget('state'))=='readonly' for box in app.language_boxes))
            finally:
                app.root.destroy()
