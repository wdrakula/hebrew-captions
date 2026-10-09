import ctypes
from pathlib import Path
import sys
import tkinter as tk
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gui import History, InputShape

class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk()
        self.root.withdraw()
        self.history=History(self.root,{'subtitle_geometry':'600x200+10+10'})
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def append(self,n):
        self.history.append({'he':'שלום עולם','ru':f'Реплика {n}: '+'проверяем историю и прокрутку '*4})
        self.root.update()

    def test_follow_and_pause_scroll(self):
        for n in range(30):self.append(n)
        self.assertTrue(self.history.follows)
        self.assertGreater(self.history.text.yview()[1],.99)
        self.history.text.yview_moveto(0)
        self.root.update()
        before=self.history.text.index('@0,0')
        self.assertFalse(self.history.follows)
        self.append(31)
        self.assertEqual(self.history.text.index('@0,0'),before)
        self.assertTrue(self.history.jump.winfo_ismapped())
        self.history.bottom();self.root.update()
        self.assertTrue(self.history.follows)
        self.assertFalse(self.history.jump.winfo_ismapped())

    def test_current_only_latest_history_retained(self):
        self.append(1);self.append(2)
        content=self.history.text.get('1.0','end')
        self.assertIn('Реплика 1',content)
        self.assertIn('Реплика 2',content)
        ranges=self.history.text.tag_ranges('current')
        current=self.history.text.get(ranges[0],ranges[1])
        self.assertIn('Реплика 2',current)
        self.assertNotIn('Реплика 1',current)

    def test_hebrew_optional(self):
        self.append(1)
        self.assertEqual(self.history.text.tag_ranges('he'),())
        self.history.set_hebrew(True)
        self.assertTrue(self.history.text.tag_ranges('he'))
        self.history.set_hebrew(False)
        self.assertEqual(self.history.text.tag_ranges('he'),())
        self.assertIn('Реплика 1',self.history.text.get('1.0','end'))

    def test_clickthrough_region_and_restore(self):
        shape=InputShape()
        shape.ext.XShapeGetRectangles.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),ctypes.POINTER(ctypes.c_int)]
        shape.ext.XShapeGetRectangles.restype=ctypes.c_void_p
        def count():
            d=shape.x.XOpenDisplay(None)
            n,ordering=ctypes.c_int(),ctypes.c_int()
            ptr=shape.ext.XShapeGetRectangles(d,self.history.window.winfo_id(),2,
                ctypes.byref(n),ctypes.byref(ordering))
            if ptr:shape.x.XFree(ptr)
            shape.x.XCloseDisplay(d)
            return n.value
        shape.set(self.history.window,True)
        self.assertEqual(count(),0)
        shape.set(self.history.window,False)
        self.assertGreater(count(),0)

if __name__=='__main__':unittest.main()

class RevisionTests(HistoryTests):
    def test_update_preserves_neighbors_and_scroll(self):
        h=self.history
        for n in range(30):
            h.append({'id':str(n),'he':'שלום','ru':f'Строка {n}: '+('текст '*15)})
        self.root.update();h.text.yview_moveto(0);self.root.update()
        before=h.text.index('@0,0')
        h.append({'id':'29','he':'שלום','ru':'Последняя обновлённая строка'})
        self.root.update()
        self.assertEqual(len(h.records),30)
        self.assertEqual(h.text.index('@0,0'),before)
        h.append({'id':'28','he':'שלום','ru':'Предыдущая исправленная строка'})
        content=h.text.get('1.0','end')
        self.assertIn('Последняя обновлённая строка',content)
        self.assertIn('Предыдущая исправленная строка',content)
        ranges=h.text.tag_ranges('current')
        self.assertEqual(h.text.get(ranges[0],ranges[1]),'Последняя обновлённая строка')
