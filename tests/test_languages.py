import asyncio
import io
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from languages import LANGUAGES, display_text
from pipeline import translate, session_config, Runner, Session
from audio import Turn

class LanguageTests(unittest.TestCase):
    def test_explicit_hints_for_all_languages_and_modes(self):
        for code in LANGUAGES:
            for mode in ('live','transcribe'):
                settings=session_config(mode,code)['session']['audio']['input']['transcription']
                self.assertEqual(settings['languages'],[code])
                self.assertIn(LANGUAGES[code][1],settings['prompt'])

    def test_translation_request_language_and_model(self):
        requests=[]
        def request(req,**kwargs):
            requests.append(json.loads(req.data))
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':'Здравствуйте'}}]}).encode())
        with patch('pipeline.urllib.request.urlopen',side_effect=request):
            for model in ('gpt-4o-mini','gpt-4.1-mini'):
                self.assertEqual(translate('fake','Bonjour','ancien contexte',model,'fr','ru')[0],'Здравствуйте')
        for req in requests:
            self.assertIn('French',req['messages'][0]['content'])
            self.assertIn('Russian',req['messages'][0]['content'])
            self.assertNotIn('Hebrew',str(req))
        self.assertEqual([r['model'] for r in requests],['gpt-4o-mini','gpt-4.1-mini'])

    def test_ltr_text_is_not_reordered(self):
        for text in ('Bonjour, le monde!','Hello (test) 12','Привет, мир!'):
            self.assertEqual(display_text(text),text)

class PipelineLanguageTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_pair_reaches_translator(self):
        r=Runner('transcribe',None,'fake',lambda *args:None,'es','en','gpt-4.1-mini')
        s=Session(r,'transcribe');s.outstanding=1
        await s.translation_queue.put((Turn(1,time.monotonic()-2,time.monotonic()),'Hola',time.monotonic()))
        with patch('pipeline.translate',return_value=('Hello',{})) as translate_mock:
            task=asyncio.create_task(s.translations())
            try:
                await asyncio.wait_for(s.translation_queue.join(),1)
                self.assertEqual(translate_mock.call_args.args[-3:],('gpt-4.1-mini','es','en'))
            finally:
                task.cancel();await asyncio.gather(task,return_exceptions=True);r.log.close()
