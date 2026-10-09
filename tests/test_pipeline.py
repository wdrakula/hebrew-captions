import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from audio import Frame, Segmenter, Silero, rms, capture
from pipeline import Session, Runner, APIError, remove_overlap, session_config
from journal import Journal
from config import load_key

VOICE=(np.full(2400,2000,dtype='<i2')).tobytes()
SILENCE=bytes(4800)

class AudioTests(unittest.TestCase):
    def frame(self,n,pcm=VOICE):
        return Frame(pcm,10+n/10,'test.monitor')

    def test_silence_skipped(self):
        s=Segmenter('transcribe')
        for n in range(100):
            self.assertEqual(s.feed(self.frame(n,SILENCE),False),([],None))

    def test_preroll_retained(self):
        s=Segmenter('transcribe')
        s.feed(self.frame(0,SILENCE),False)
        s.feed(self.frame(1,SILENCE),False)
        packets,turn=s.feed(self.frame(2),True)
        self.assertEqual(len(packets),3)
        self.assertIsNone(turn)

    def test_forced_cut_12_frames_then_overlap(self):
        s=Segmenter('transcribe')
        for n in range(12):
            packets,turn=s.feed(self.frame(n),True)
        self.assertIsNotNone(turn)
        self.assertEqual(len(s.carry),4)
        packets,turn=s.feed(self.frame(12),True)
        self.assertEqual(len(packets),5)
        self.assertTrue(s.overlap)
        for n in range(13,24):
            _,turn=s.feed(self.frame(n),True)
        self.assertIsNotNone(turn)
        self.assertAlmostEqual(turn.end-turn.start,1.6)

    def test_live_does_not_replay(self):
        s=Segmenter('live')
        for n in range(12):
            s.feed(self.frame(n),True)
        self.assertEqual(s.carry,[])
        packets,_=s.feed(self.frame(12),True)
        self.assertEqual(len(packets),1)

    def test_pause_finishes_and_no_overlap(self):
        s=Segmenter('transcribe')
        s.feed(self.frame(0),True)
        for n in range(1,4):
            _,turn=s.feed(self.frame(n,SILENCE),False)
        self.assertIsNotNone(turn)
        self.assertEqual(s.carry,[])

    def test_schema_languages_both_models(self):
        for mode in ['live','transcribe']:
            inp=session_config(mode)['session']['audio']['input']
            self.assertEqual(inp['transcription']['languages'],['he'])
            self.assertNotIn('language',inp['transcription'])
            self.assertIsNone(inp['turn_detection'])

    def test_silero_silence_and_resampling_bounded(self):
        v=Silero()
        for _ in range(20):
            self.assertLess(v.probability(SILENCE),.35)
            self.assertLess(len(v.buffer),512)
        self.assertEqual(v.session.get_providers(),['CPUExecutionProvider'])
        self.assertEqual(v.session.get_session_options().intra_op_num_threads,1)

    def test_overlap_word_boundaries(self):
        fresh,n=remove_overlap('היום אנחנו מדברים על הנושא','על הנושא, החשוב הזה')
        self.assertEqual((fresh,n),('החשוב הזה',2))
        self.assertEqual(remove_overlap('זה טוב','טוב מאוד'),('טוב מאוד',0))
        self.assertEqual(remove_overlap('שלום עולם','נושא אחר'),('נושא אחר',0))

    def test_quota_not_every_429(self):
        self.assertTrue(APIError('insufficient_quota',status=429).quota)
        self.assertFalse(APIError('rate_limit_exceeded',status=429).quota)
        self.assertFalse(APIError('invalid_api_key',status=401).quota)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    def runner(self):
        r=Runner('live',None,'fake',lambda *args:None)
        self.addCleanup(r.log.close)
        return r

    async def test_out_of_order(self):
        from audio import Turn
        r=self.runner(); s=Session(r,'live')
        now=time.monotonic()
        s.pending.extend([Turn(1,now-2,now-1,committed=now),Turn(2,now-1,now,committed=now)])
        events=[{'type':'input_audio_buffer.committed','item_id':'a'},
                {'type':'input_audio_buffer.committed','item_id':'b'},
                {'type':'conversation.item.input_audio_transcription.completed','item_id':'b','transcript':'ב'},
                {'type':'conversation.item.input_audio_transcription.completed','item_id':'a','transcript':'א'}]
        class Socket:
            def __aiter__(self):return self.rows()
            async def rows(self):
                for e in events:yield json.dumps(e)
        await s.receive(Socket())
        self.assertEqual((await s.translation_queue.get())[0].sequence,1)
        self.assertEqual((await s.translation_queue.get())[0].sequence,2)

    async def test_stop_commits_unfinished(self):
        r=self.runner(); s=Session(r,'live')
        class Socket:
            messages=[]
            async def send(self,raw):self.messages.append(json.loads(raw))
        ws=Socket()
        for n in range(3):
            await r.frames.put((Frame(VOICE,time.monotonic(),'x'),.9))
        task=asyncio.create_task(s.send_audio(ws))
        await asyncio.sleep(.03)
        r.stopping=True
        await task
        self.assertEqual(ws.messages[-1]['type'],'input_audio_buffer.commit')
        self.assertEqual(s.outstanding,1)

    async def test_switch_preserves_next_audio(self):
        r=self.runner(); s=Session(r,'live')
        r.desired_mode='transcribe'
        await r.frames.put((Frame(VOICE,time.monotonic(),'x'),.9))
        class Socket:
            async def send(self,_):raise AssertionError('Must not send to old mode')
        await s.send_audio(Socket())
        self.assertEqual(r.frames.qsize(),1)

    async def test_translation_and_usage(self):
        from audio import Turn
        r=self.runner(); shown=[];r.emit=lambda k,v:shown.append((k,v))
        s=Session(r,'transcribe');now=time.monotonic();s.outstanding=1
        await s.translation_queue.put((Turn(1,now-2,now-1), 'שלום עולם', now))
        with patch('pipeline.translate',return_value=('Привет, мир',{'total_tokens':10})):
            task=asyncio.create_task(s.translations())
            try:
                await asyncio.wait_for(s.translation_queue.join(),1)
                self.assertEqual(shown[-1][1]['ru'],'Привет, мир')
                self.assertEqual(s.outstanding,0)
                self.assertNotIn('שלום עולם',r.log.path.read_text())
            finally:
                task.cancel();await asyncio.gather(task,return_exceptions=True)

    async def test_server_quota(self):
        s=Session(self.runner(),'live')
        class Socket:
            def __aiter__(self):return self.rows()
            async def rows(self):
                yield json.dumps({'type':'error','error':{'code':'insufficient_quota'}})
        with self.assertRaises(APIError) as ctx:
            await s.receive(Socket())
        self.assertTrue(ctx.exception.quota)

if __name__=='__main__':unittest.main()
