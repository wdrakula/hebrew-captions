from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gui import History
from history_text import present
from bidi.algorithm import get_display

SOURCE='שלום (123) — русский, https://example.org/a?q=12&x=3. 🙂'
TRANSLATION='Привет: שלום עולם, число 42 (тест); https://example.org/path.'

class HistoryToolsTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw()
        self.h=History(self.root,{'show_hebrew':True,'subtitle_geometry':'700x260+10+10'})
        self.h.session_started=100
        self.h.append({'id':'one','he':SOURCE,'ru':TRANSLATION,'start':165.8})
        self.root.update()
    def tearDown(self):self.root.destroy()

    def test_select_all_copies_logical_unicode_and_separators(self):
        self.h.append({'id':'two','he':'שיעור שני','ru':'Вторая часть','start':200})
        self.h.select_all();self.h.copy_selection()
        expected=f'[00:01:05]\n{SOURCE}\n{TRANSLATION}\n\n[00:01:40]\nשיעור שני\nВторая часть'
        self.assertEqual(self.h.text.clipboard_get(),expected)
        self.assertEqual(self.h.text.cget('state'),'disabled')
        before=self.h.text.get('1.0','end')
        self.h.text.insert('1.0','accidental edit')
        self.assertEqual(self.h.text.get('1.0','end'),before)

    def test_partial_hebrew_and_url_copy(self):
        start,end,p=self.h.presentations[0][1]
        for visual,expected in [(get_display('שלום'),'שלום'),('https://example.org/a?q=12&x=3','https://example.org/a?q=12&x=3')]:
            offset=p.visual.index(visual)
            # Tcl indices use two units for supplementary characters; text search is exact.
            first=self.h.text.search(visual,start,stopindex=end,exact=True)
            self.assertTrue(first)
            self.h.text.tag_remove('sel','1.0','end')
            self.h.text.tag_add('sel',first,f'{first}+{len(visual)}c')
            self.h.copy_selection()
            self.assertEqual(self.h.text.clipboard_get(),expected)

    def test_export_three_variants_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            for variant,expected in [('source',SOURCE+'\n'),('translation',TRANSLATION+'\n'),('both',SOURCE+'\n'+TRANSLATION+'\n')]:
                path=Path(folder)/f'{variant}.txt'
                self.h.save_text(path,variant,False)
                self.assertEqual(path.read_bytes(),expected.encode('utf-8'))
                self.h.save_text(path,variant,True)
                self.assertEqual(path.read_text(encoding='utf-8'),'[00:01:05]\n'+expected)

    def test_live_timestamp_stable_and_pause_gap_retained(self):
        self.h.append({'id':'one','he':SOURCE+' חדש','ru':TRANSLATION+' новое','start':9999})
        self.assertEqual(len(self.h.records),1)
        self.assertAlmostEqual(self.h.record_meta[0]['seconds'],65.8)
        self.h.append({'id':'two','he':'אחרי הפסקה','ru':'После паузы','start':3805})
        self.assertIn('[01:01:45]',self.h.export_text('both',True))
        self.assertIn('[00:01:05]',self.h.text.get('1.0','end'))

    def test_shortcuts_for_non_latin_layouts(self):
        for keysym in ('a','Cyrillic_ef','hebrew_shin'):
            self.h.text.tag_remove('sel','1.0','end')
            self.h.control_key(SimpleNamespace(keycode=next(k for k,v in self.h.shortcut_codes.items() if v=='a'),keysym=keysym))
            self.assertTrue(self.h.text.tag_ranges('sel'))
            self.h.control_key(SimpleNamespace(keycode=next(k for k,v in self.h.shortcut_codes.items() if v=='c'),keysym='hebrew_bet'))
            self.assertIn(SOURCE,self.h.text.clipboard_get())

    def test_mouse_drag_selects_while_readonly(self):
        self.h.text.see('1.0');self.root.update()
        a=self.h.text.bbox('1.0');b=self.h.text.bbox('1.5')
        self.assertTrue(a and b)
        self.h.text.event_generate('<Button-1>',x=a[0]+1,y=a[1]+2)
        self.h.text.event_generate('<B1-Motion>',x=b[0]+2,y=b[1]+2,state=256)
        self.h.text.event_generate('<ButtonRelease-1>',x=b[0]+2,y=b[1]+2)
        self.root.update()
        self.assertTrue(self.h.text.tag_ranges('sel'))
        self.assertEqual(self.h.text.cget('state'),'disabled')

    def test_mapping_with_diacritics_mirrors_and_multiline(self):
        for text in [SOURCE,TRANSLATION,'שָׁלוֹם! (42) [abc]','שלום\nРусский (123) שלום','מילה \u2067abc\u2069 אחרת']:
            p=present(text)
            self.assertEqual(p.selected(0,len(p.visual)),text)
            self.assertEqual(len(p.visual),len(p.indices))
            for i,original in enumerate(p.indices):
                self.assertEqual(p.selected(i,i+1),text[original])

    def test_selection_survives_append_and_later_live_update(self):
        a,b,p=self.h.presentations[0][1]
        self.h.text.tag_add('sel',a,b)
        self.h.append({'id':'two','he':'עוד','ru':'Ещё','start':200})
        self.h.append({'id':'two','he':'עוד משפט','ru':'Ещё фраза','start':201})
        self.h.copy_selection()
        self.assertEqual(self.h.text.clipboard_get(),SOURCE+'\n')
        self.h.set_hebrew(False)
        self.h.select_all();self.h.text.event_generate('<<Copy>>');self.root.update()
        self.assertEqual(self.h.text.clipboard_get(),'[00:01:05]\n'+TRANSLATION+'\n\n[00:01:40]\nЕщё фраза')

class HistoryDialogTests(unittest.TestCase):
    def test_buttons_use_snapshot_without_models(self):
        from unittest.mock import patch
        from gui import App
        with patch('gui.load_settings',return_value={}), patch('gui.load_key',return_value=''), patch('gui.save_settings'), patch('gui.Runner',side_effect=AssertionError('No capture allowed')):
            app=App()
            try:
                app.history.session_started=100
                app.history.append({'id':'one','he':SOURCE,'ru':TRANSLATION,'start':165})
                app.history_tools()
                frame=app.history_window.winfo_children()[0]
                with tempfile.TemporaryDirectory() as folder:
                    for row,variant in enumerate(('source','translation','both'),1):
                        expected=app.history.export_text(variant,True)
                        for child in frame.winfo_children():
                            grid=child.grid_info()
                            if grid.get('row')==row and grid.get('column')==1:
                                child.invoke()
                                self.assertEqual(app.history.text.clipboard_get(),expected)
                            if grid.get('row')==row and grid.get('column')==2:
                                path=Path(folder)/f'{variant}.txt'
                                with patch('gui.filedialog.asksaveasfilename',return_value=str(path)):
                                    child.invoke()
                                self.assertEqual(path.read_text(encoding='utf-8'),expected)
            finally:app.root.destroy()
