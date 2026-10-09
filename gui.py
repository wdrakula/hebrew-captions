"""Two-window UI, quiet controls, scrollable session history."""
import asyncio
import ctypes
import ctypes.util
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
import webbrowser
from languages import LANGUAGES, TRANSLATORS, is_rtl, display_text as get_display

from i18n import UI_LANGUAGES, translate_ui
from audio import outputs
from config import load_key, load_settings, save_settings
from pipeline import Runner, APIError

MODE_NAMES = {'live':'Live — дороже', 'transcribe':'Обычный — дешевле'}


class StatusText(tk.StringVar):
    def __init__(self, app, value):
        self.app, self.raw = app, value
        super().__init__(master=app.root, value=app.ui_text(value))

    def set(self, value):
        self.raw = value
        super().set(self.app.ui_text(value))

    def refresh(self):
        super().set(self.app.ui_text(self.raw))


class InputShape:
    """X11 input region for this application's subtitle window only."""
    def __init__(self):
        self.x = ctypes.CDLL(ctypes.util.find_library('X11'))
        self.ext = ctypes.CDLL(ctypes.util.find_library('Xext'))
        self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x.XOpenDisplay.restype = ctypes.c_void_p
        self.x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.x.XFlush.argtypes = [ctypes.c_void_p]
        self.ext.XShapeCombineRectangles.argtypes = [ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,
            ctypes.c_int,ctypes.c_int,ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int]
        self.ext.XShapeCombineMask.argtypes = [ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,
            ctypes.c_int,ctypes.c_int,ctypes.c_ulong,ctypes.c_int]
        self.x.XQueryTree.argtypes = [ctypes.c_void_p,ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),ctypes.POINTER(ctypes.c_uint)]
        self.x.XFree.argtypes = [ctypes.c_void_p]

    def set(self, window, locked):
        window.update_idletasks()
        display = self.x.XOpenDisplay(None)
        if not display:
            raise RuntimeError('Нет подключения к X11')
        try:
            wid = window.winfo_id()
            root, parent = ctypes.c_ulong(), ctypes.c_ulong()
            children = ctypes.POINTER(ctypes.c_ulong)()
            count = ctypes.c_uint()
            self.x.XQueryTree(display,wid,ctypes.byref(root),ctypes.byref(parent),ctypes.byref(children),ctypes.byref(count))
            if children:
                self.x.XFree(children)
            windows = [wid]
            if parent.value and parent.value != root.value:
                windows.append(parent.value)
            for w in windows:
                if locked:
                    self.ext.XShapeCombineRectangles(display,w,2,0,0,None,0,0,0)
                else:
                    self.ext.XShapeCombineMask(display,w,2,0,0,0,0)
            self.x.XFlush(display)
        finally:
            self.x.XCloseDisplay(display)


class History:
    def __init__(self, root, settings):
        self.window = tk.Toplevel(root)
        self.window.title('Субтитры — иврит → русский')
        width = min(1000, root.winfo_screenwidth()-60)
        height = 280
        default = f'{width}x{height}+{(root.winfo_screenwidth()-width)//2}+{max(0,root.winfo_screenheight()-height-70)}'
        self.window.geometry(settings.get('subtitle_geometry',default))
        self.window.minsize(400,150)
        self.window.attributes('-topmost',True)
        self.window.attributes('-alpha',settings.get('opacity',.95))
        self.frame = tk.Frame(self.window,bg='#17212b')
        self.frame.pack(fill='both',expand=True)
        self.text = tk.Text(self.frame,wrap='word',bg='#17212b',fg='#a2acb7',
            font=('Sans',settings.get('font_size',21)),padx=18,pady=12,
            borderwidth=0,highlightthickness=0,state='disabled',cursor='arrow')
        self.bar = ttk.Scrollbar(self.frame,command=self.text.yview)
        self.bar.pack(side='right',fill='y')
        self.text.pack(fill='both',expand=True)
        self.text.tag_configure('current',foreground='#ffffff')
        self.text.tag_configure('he',foreground='#8aa2b9',justify='right',font=('Sans',15))
        self.text.tag_configure('ltr',justify='left')
        self.text.tag_configure('rtl',justify='right')
        self.text.configure(yscrollcommand=self.scrolled)
        self.jump = ttk.Button(self.frame,text='К текущему ↓',command=self.bottom)
        self.partial = tk.StringVar()
        self.partial_label = tk.Label(self.frame,textvariable=self.partial,bg='#17212b',fg='#8aa2b9',
                                      font=('Sans',14),anchor='e',wraplength=900)
        self.show_hebrew = settings.get('show_hebrew',False)
        self.records = []
        self.record_ids = {}
        self.record_marks = {}
        self.follows = True
        self.updating = False
        self.window.protocol('WM_DELETE_WINDOW',self.window.withdraw)

    def scrolled(self, first, last):
        self.bar.set(first,last)
        if not self.updating:
            self.follows = float(last) >= .999
        if self.follows:
            self.jump.place_forget()
        else:
            self.jump.place(relx=.98,rely=.98,anchor='se')

    def bottom(self):
        self.follows = True
        self.text.see('end')
        self.jump.place_forget()

    def append(self, value):
        identity = value.get('id')
        if identity is not None and identity in self.record_ids:
            index = self.record_ids[identity]
            self.records[index] = (value['he'], value['ru'])
            start, end = self.record_marks[index]
            follows = self.follows
            self.updating = True
            self.text.configure(state='normal')
            self.text.mark_set('viewport', self.text.index('@0,0'))
            self.text.mark_gravity('viewport', 'left')
            self.text.delete(start, end)
            if self.show_hebrew:
                self.text.insert(end, get_display(value['he'])+'\n', ('he', 'rtl' if is_rtl(value['he']) else 'ltr'))
            tags = ('current',) if index == len(self.records)-1 else ()
            self.text.insert(end, get_display(value['ru']), tags+('rtl' if is_rtl(value['ru']) else 'ltr',))
            self.text.configure(state='disabled')
            if follows:
                self.text.see('end')
            else:
                self.text.yview('viewport')
            self.text.update_idletasks()
            self.updating = False
            self.follows = follows
            self.scrolled(*self.text.yview())
        else:
            index = len(self.records)
            self.records.append((value['he'],value['ru']))
            if identity is not None:
                self.record_ids[identity] = index
            self.insert_record(value['he'],value['ru'], index)
        self.partial.set('')

    def insert_record(self, he, ru, index=None):
        follows = self.follows
        first_visible = self.text.index('@0,0')
        self.updating = True
        self.text.configure(state='normal')
        self.text.tag_remove('current','1.0','end')
        if self.text.index('end-1c') != '1.0':
            previous_end = self.record_marks.get(index-1, (None, None))[1] if index is not None else None
            if previous_end:
                self.text.mark_gravity(previous_end, 'left')
            self.text.insert('end','\n\n')
            if previous_end:
                self.text.mark_gravity(previous_end, 'right')
        if index is not None:
            start, end = f'entry_{index}_start', f'entry_{index}_end'
            self.text.mark_set(start, 'end-1c')
            self.text.mark_gravity(start, 'left')
        if self.show_hebrew:
            self.text.insert('end',get_display(he)+'\n',('he','rtl' if is_rtl(he) else 'ltr'))
        self.text.insert('end',get_display(ru),('current','rtl' if is_rtl(ru) else 'ltr'))
        if index is not None:
            self.text.mark_set(end, 'end-1c')
            self.text.mark_gravity(end, 'right')
            self.record_marks[index] = (start, end)
        self.text.configure(state='disabled')
        if follows:
            self.text.see('end')
        else:
            self.text.yview(first_visible)
        self.text.update_idletasks()
        self.updating = False
        self.follows = follows
        self.scrolled(*self.text.yview())

    def set_hebrew(self, show):
        self.show_hebrew = show
        self.text.configure(state='normal')
        self.text.delete('1.0','end')
        self.text.configure(state='disabled')
        records = list(self.records)
        for index, (he,ru) in enumerate(records):
            self.insert_record(he,ru,index)
        if show:
            self.partial_label.pack(fill='x')
        else:
            self.partial_label.pack_forget()
        self.bottom()


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('Переводчик субтитров')
        settings = load_settings()
        self.ui_language = settings.get('ui_language','ru')
        if self.ui_language not in UI_LANGUAGES:
            self.ui_language = 'ru'
        self.ui_sources = {}
        self.ui_titles = {}
        self.root.geometry(settings.get('control_geometry','500x330'))
        self.root.minsize(500,330)
        self.history = History(self.root,settings)
        self.events = queue.Queue(maxsize=256)
        self.loop = self.runner = self.task = self.thread = None
        self.key = load_key()
        self.closing = False
        self.settings = settings
        self.mode = tk.StringVar(value=MODE_NAMES.get(settings.get('mode','live'),MODE_NAMES['live']))
        self.source = settings.get('source')  # None means follow default
        self.status = StatusText(self,value='Готово · ключ найден' if self.key else 'Не найден файл с ключом')
        self.locked = tk.BooleanVar(value=False)
        top = ttk.Frame(self.root,padding=16)
        top.pack(fill='both',expand=True)
        header = ttk.Frame(top)
        header.pack(fill='x',pady=(0,4))
        self.ui_button = ttk.Menubutton(header,text='🌐',width=3)
        self.ui_button.pack(side='right')
        self.ui_menu = tk.Menu(self.ui_button,tearoff=False)
        for code, name in UI_LANGUAGES.items():
            self.ui_menu.add_command(label=get_display(name),command=lambda code=code:self.set_ui_language(code))
        self.ui_button.configure(menu=self.ui_menu)
        self.source_language = tk.StringVar(value=LANGUAGES.get(settings.get('source_language','he'),LANGUAGES['he'])[0])
        self.target_language = tk.StringVar(value=LANGUAGES.get(settings.get('target_language','ru'),LANGUAGES['ru'])[0])
        self.translator = settings.get('translator','gpt-4o-mini')
        if self.translator not in TRANSLATORS:
            self.translator = 'gpt-4o-mini'
        language_row = ttk.Frame(top)
        language_row.pack(fill='x',pady=(0,10))
        self.language_boxes = []
        for variable, label in [(self.source_language,'С какого языка'),(self.target_language,'На какой язык')]:
            column = ttk.Frame(language_row)
            column.pack(side='left',expand=True,fill='x')
            ttk.Label(column,text=label).pack(anchor='w')
            box = ttk.Combobox(column,textvariable=variable,values=[v[0] for v in LANGUAGES.values()],state='readonly',width=18)
            box.pack(fill='x',padx=(0,6))
            box.bind('<<ComboboxSelected>>',self.languages_changed)
            self.language_boxes.append(box)
        self.mode_box = ttk.Combobox(top,textvariable=self.mode,values=list(MODE_NAMES.values()),state='readonly',width=30)
        self.mode_box.pack(fill='x')
        self.mode_box.bind('<<ComboboxSelected>>',self.switch)
        row = ttk.Frame(top)
        row.pack(fill='x',pady=(12,8))
        self.start_button = ttk.Button(row,text='Начать',command=self.start_or_pause)
        self.start_button.pack(side='left')
        ttk.Button(row,text='Субтитры',command=self.show_history).pack(side='left',padx=8)
        ttk.Checkbutton(row,text='Закрепить',variable=self.locked,command=self.lock).pack(side='left')
        self.level = ttk.Progressbar(top,maximum=.15)
        self.level.pack(fill='x',pady=4)
        ttk.Label(top,textvariable=self.status,wraplength=430).pack(fill='x',pady=4)
        self.advanced_button = ttk.Button(top,text='Дополнительно…',command=self.advanced)
        self.advanced_button.pack(anchor='e')
        self.quota_window = None
        self.advanced_window = None
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.poll_timer = self.root.after(40,self.poll)
        self.root.bind('<Destroy>',self.cancel_poll_timer,add='+')
        self.history.set_hebrew(self.history.show_hebrew)
        self.apply_ui_language()

    def cancel_poll_timer(self, event):
        if event.widget is self.root:
            self.root.after_cancel(self.poll_timer)

    def ui_text(self, text):
        return get_display(translate_ui(text,self.ui_language))

    def set_ui_language(self, code):
        if code not in UI_LANGUAGES:
            return
        self.ui_language = code
        self.apply_ui_language()
        self.persist()

    def apply_ui_language(self):
        def visit(widget):
            if isinstance(widget,(tk.Tk,tk.Toplevel)) and widget != self.history.window:
                original = self.ui_titles.setdefault(widget,widget.title())
                widget.title(self.ui_text(original))
            try:
                text = str(widget.cget('text'))
            except tk.TclError:
                text = ''
            if text and widget != self.ui_button:
                original = self.ui_sources.setdefault((widget,'text'),text)
                widget.configure(text=self.ui_text(original))
            if isinstance(widget,ttk.Combobox):
                index = widget.current()
                original = self.ui_sources.setdefault((widget,'values'),tuple(widget.cget('values')))
                widget.configure(values=[self.ui_text(value) for value in original])
                if index >= 0:
                    widget.current(index)
            for child in widget.winfo_children():
                visit(child)
        visit(self.root)
        self.status.refresh()
        self.root.update_idletasks()
        self.root.minsize(max(500,self.root.winfo_reqwidth()),max(330,self.root.winfo_reqheight()))
        self.history.window.title(self.ui_text('Субтитры')+' — '+self.source_language.get()+' → '+self.target_language.get())

    def language_id(self, variable):
        box = self.language_boxes[0 if variable is self.source_language else 1]
        return list(LANGUAGES)[box.current()]

    def languages_changed(self, _=None):
        self.history.window.title(self.ui_text('Субтитры')+' — '+self.source_language.get()+' → '+self.target_language.get())
        self.persist()

    def mode_id(self):
        return list(MODE_NAMES)[self.mode_box.current()]

    def show_history(self):
        self.history.window.deiconify()
        self.history.window.lift()

    def lock(self):
        try:
            InputShape().set(self.history.window,self.locked.get())
        except Exception:
            self.locked.set(False)
            self.status.set('Не удалось закрепить окно')

    def active(self):
        return self.thread is not None and self.thread.is_alive()

    def start_or_pause(self):
        if self.active():
            self.pause()
        else:
            self.start()

    def start(self):
        if self.active() or self.closing:
            return
        self.key = load_key()
        if not self.key:
            self.status.set('Не найден файл с API-ключом')
            return
        if self.advanced_window and self.advanced_window.winfo_exists():
            self.advanced_window.destroy()
        self.status.set('Подключение…')
        self.ui_sources[(self.start_button,'text')] = 'Пауза'
        self.start_button.configure(text=self.ui_text('Пауза'))
        self.advanced_button.configure(state='disabled')
        for box in self.language_boxes:
            box.configure(state='disabled')
        self.show_history()
        mode,source,key = self.mode_id(),self.source,self.key
        speech, target, translator = self.language_id(self.source_language), self.language_id(self.target_language), self.translator
        def worker():
            def emit(kind,value):
                try:
                    self.events.put_nowait((kind,value))
                except queue.Full:
                    if kind!='level':
                        raise RuntimeError('Окно не успевает обрабатывать субтитры')
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.runner = Runner(mode,source,key,emit,speech,target,translator)
            self.task = self.loop.create_task(self.runner.run())
            if self.closing:
                self.task.cancel()
            try:
                self.loop.run_until_complete(self.task)
            # Graceful stop has already drained final recognition and translation.
            except asyncio.CancelledError:
                emit('status','Остановлено')
            except APIError as exc:
                emit('quota' if exc.quota else 'status',str(exc).replace(key,'[скрыто]'))
            except Exception as exc:
                emit('status','Ошибка: '+str(exc).replace(key,'[скрыто]'))
            finally:
                self.loop.run_until_complete(self.loop.shutdown_default_executor())
                self.loop.close()
                self.events.put(('finished',self.runner.log))
        self.thread = threading.Thread(target=worker,daemon=True)
        self.thread.start()

    def pause(self):
        if self.loop and not self.loop.is_closed() and self.runner:
            self.loop.call_soon_threadsafe(setattr,self.runner,'stopping',True)
            self.status.set('Завершаю текущую фразу…')
            self.start_button.configure(state='disabled')

    def switch(self,_=None):
        if self.loop and not self.loop.is_closed() and self.runner and self.active():
            self.loop.call_soon_threadsafe(setattr,self.runner,'desired_mode',self.mode_id())
            self.status.set('Переключение…')
        self.persist()

    def advanced(self):
        if self.active():
            return
        if self.advanced_window and self.advanced_window.winfo_exists():
            self.advanced_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.advanced_window = window
        window.title('Дополнительно')
        frame = ttk.Frame(window,padding=16)
        frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Модель перевода').pack(anchor='w')
        model = tk.StringVar(value=TRANSLATORS[self.translator])
        model_box = ttk.Combobox(frame,textvariable=model,values=list(TRANSLATORS.values()),state='readonly',width=40)
        model_box.pack(fill='x',pady=6)
        def model_changed(_):
            self.translator = list(TRANSLATORS)[model_box.current()]
            self.persist()
        model_box.bind('<<ComboboxSelected>>',model_changed)
        ttk.Label(frame,text='Источник звука').pack(anchor='w')
        try:
            devices = outputs()
        except Exception:
            devices = []
        names = ['Выход по умолчанию']+[name for _,name in devices]
        selected = tk.StringVar(value=next((name for monitor,name in devices if monitor==self.source),names[0]))
        box = ttk.Combobox(frame,textvariable=selected,values=names,state='readonly',width=40)
        box.pack(fill='x',pady=6)
        # Choose by index to distinguish outputs with identical friendly names.
        box.current(next((i+1 for i,(monitor,_) in enumerate(devices) if monitor==self.source),0))
        def source_changed(_):
            index = box.current()
            self.source = devices[index-1][0] if index else None
            self.persist()
        box.bind('<<ComboboxSelected>>',source_changed)
        show = tk.BooleanVar(value=self.history.show_hebrew)
        ttk.Checkbutton(frame,text='Показывать исходный текст',variable=show,
            command=lambda:(self.history.set_hebrew(show.get()),self.persist())).pack(anchor='w',pady=6)
        ttk.Label(frame,text='Размер текста').pack(anchor='w')
        size = tk.IntVar(value=self.settings.get('font_size',21))
        def font_changed(_=None):
            try:
                value = size.get()
            except tk.TclError:
                return
            if not 14 <= value <= 36:
                return
            self.history.text.configure(font=('Sans',value))
            self.settings['font_size'] = value
            self.persist()
        ttk.Spinbox(frame,from_=14,to=36,textvariable=size,command=font_changed,width=6).pack(anchor='w')
        size.trace_add('write',lambda *_:font_changed())
        ttk.Label(frame,text='Непрозрачность').pack(anchor='w',pady=(8,0))
        opacity = tk.DoubleVar(value=self.settings.get('opacity',.95))
        def opacity_changed(value):
            self.history.window.attributes('-alpha',float(value))
            self.settings['opacity']=float(value)
        ttk.Scale(frame,from_=.5,to=1,variable=opacity,command=opacity_changed).pack(fill='x')
        ttk.Button(frame,text='Готово',command=lambda:(self.persist(),window.destroy())).pack(anchor='e',pady=10)
        window.variables = (model,selected,show,size,opacity)
        self.apply_ui_language()

    def quota(self):
        self.status.set('Оплатите ключ API!!!! 😉')
        if self.quota_window and self.quota_window.winfo_exists():
            return
        window = self.quota_window = tk.Toplevel(self.root)
        window.title('Нужна оплата API')
        frame = ttk.Frame(window,padding=20)
        frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Оплатите ключ API!!!! 😉',font=('Sans',16)).pack(pady=8)
        ttk.Label(frame,text='Баланс или квота API исчерпаны.\nЗахват и платные запросы остановлены.').pack(pady=8)
        ttk.Button(frame,text='Открыть оплату',command=lambda:webbrowser.open('https://platform.openai.com/settings/organization/billing/overview')).pack(fill='x',pady=4)
        def retry():
            if self.active():
                self.status.set('Завершаю предыдущий сеанс…')
                window.after(200,retry)
            else:
                window.destroy()
                self.start()
        ttk.Button(frame,text='Проверить и продолжить',command=retry).pack(fill='x',pady=4)
        self.apply_ui_language()

    def poll(self):
        for _ in range(256):
            try:
                kind,value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind=='finished':
                value.close()
                self.ui_sources[(self.start_button,'text')] = 'Начать'
                self.start_button.configure(text=self.ui_text('Начать'),state='normal')
                self.advanced_button.configure(state='normal')
                for box in self.language_boxes:
                    box.configure(state='readonly')
                if self.runner and self.runner.stopping:
                    self.status.set('Пауза')
            elif kind=='level':
                self.level['value']=value
            elif kind=='status':
                self.status.set(value)
            elif kind=='quota':
                self.quota()
            elif kind=='partial' and self.history.show_hebrew:
                self.history.partial_label.configure(anchor='e' if is_rtl(value) else 'w')
                self.history.partial.set(get_display(value))
            elif kind=='subtitle':
                self.history.append(value)
                now = time.monotonic()
                value['log'].emit('display',mode=value['mode'],sequence=value['sequence'],provisional=value.get('provisional',False),
                    from_start_ms=1000*(now-value['start']),from_end_ms=1000*(now-value['end']))
        if self.closing and not self.active():
            self.root.destroy()
            return
        self.poll_timer = self.root.after(40,self.poll)

    def persist(self):
        self.settings.update(mode=self.mode_id(),source=self.source,ui_language=self.ui_language,
            source_language=self.language_id(self.source_language),target_language=self.language_id(self.target_language),translator=self.translator,
            control_geometry=self.root.geometry(),subtitle_geometry=self.history.window.geometry(),
            show_hebrew=self.history.show_hebrew)
        save_settings(self.settings)

    def close(self):
        self.persist()
        self.closing = True
        self.pause()
        if self.loop and not self.loop.is_closed() and self.task:
            # Quit should never leave billable capture running after windows close.
            self.loop.call_soon_threadsafe(self.task.cancel)
        self.root.withdraw()
        self.history.window.withdraw()
