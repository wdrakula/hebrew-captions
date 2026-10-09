from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gui import App
from i18n import UI_LANGUAGES, CATALOGS, SOURCE
from languages import display_text

class InterfaceLanguageTests(unittest.TestCase):
    def make_app(self, settings=None):
        self.patches=[patch('gui.load_settings',return_value=settings or {}),patch('gui.load_key',return_value=''),patch('gui.save_settings'),patch('gui.outputs',return_value=[])]
        for p in self.patches:p.start()
        self.app=App()
        self.app.root.update()
        self.addCleanup(self.app.root.destroy)
        for p in self.patches:self.addCleanup(p.stop)
        return self.app

    def test_switch_preserves_running_pipeline_and_history(self):
        a=self.make_app({'source_language':'fr','target_language':'es','mode':'transcribe','translator':'gpt-4.1-mini'})
        a.runner=SimpleNamespace(desired_mode='transcribe',stopping=False)
        for box in a.language_boxes:box.configure(state='disabled')
        a.status.set('Слушаю')
        a.ui_sources[(a.start_button,'text')] = 'Пауза'
        a.start_button.configure(text='Пауза')
        for n in range(30):a.history.append({'he':'Bonjour','ru':f'Text {n} '+('history '*12)})
        a.history.text.yview_moveto(0);a.root.update()
        before=a.history.text.index('@0,0');content=a.history.text.get('1.0','end')
        for code in UI_LANGUAGES:
            a.set_ui_language(code);a.root.update()
            self.assertEqual((a.language_id(a.source_language),a.language_id(a.target_language)),('fr','es'))
            self.assertEqual(a.mode_id(),'transcribe')
            self.assertEqual(a.translator,'gpt-4.1-mini')
            self.assertFalse(a.runner.stopping)
            self.assertEqual(a.history.text.index('@0,0'),before)
            self.assertEqual(a.history.text.get('1.0','end'),content)
            self.assertTrue(all(str(b.cget('state'))=='disabled' for b in a.language_boxes))
            self.assertTrue(a.ui_button.winfo_ismapped())
            self.assertEqual(a.ui_button.cget('text'),'🌐')
            self.assertTrue(a.advanced_button.winfo_ismapped())
            bottom=a.advanced_button.winfo_rooty()+a.advanced_button.winfo_height()
            self.assertLessEqual(bottom,a.root.winfo_rooty()+a.root.winfo_height())
            for n,name in enumerate(UI_LANGUAGES.values()):
                self.assertEqual(a.ui_menu.entrycget(n,'label'),display_text(name))
            self.assertEqual(a.settings['ui_language'],code)
        self.assertEqual(a.status.get(),'Escuchando')
        self.assertEqual(a.start_button.cget('text'),'Pausa')
        a.ui_menu.invoke(1)
        self.assertEqual(a.ui_language,'en')
        self.assertEqual(a.start_button.cget('text'),'Pause')

    def test_non_russian_start_and_open_dialogs_retranslate(self):
        a=self.make_app({'ui_language':'en','source_language':'he','target_language':'ru'})
        self.assertEqual(a.start_button.cget('text'),'Start')
        a.advanced();window=a.advanced_window
        self.assertEqual(window.title(),'Advanced')
        a.set_ui_language('fr')
        self.assertEqual(window.title(),'Options')
        self.assertEqual(a.start_button.cget('text'),'Démarrer')
        a.status.set('Ошибка: Нет подключения к PulseAudio')
        self.assertEqual(a.status.get(),'Erreur : Connexion à PulseAudio impossible')
        a.quota();a.set_ui_language('es')
        self.assertEqual(a.quota_window.title(),'Se necesita pagar la API')
        self.assertEqual(a.language_id(a.source_language),'he')

    def test_catalogs_have_all_builtin_messages(self):
        for code in UI_LANGUAGES:
            self.assertEqual(set(CATALOGS[code]),set(SOURCE))
