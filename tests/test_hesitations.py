import asyncio
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from audio import Frame, Segmenter, Turn
from pipeline import remove_overlap, Runner, Session

def frame(n):return Frame(bytes([n])*4800,10+n/10,'test')

class HesitationTests(unittest.TestCase):
    def forced_cut(self):
        s=Segmenter('transcribe')
        for n in range(15):_,turn=s.feed(frame(n),True)
        self.assertIsNotNone(turn)
        return s

    def test_one_or_two_quiet_blocks_preserve_overlap_and_all_new_audio(self):
        for gap in (1,2):
            s=self.forced_cut()
            for n in range(15,15+gap):
                self.assertEqual(s.feed(frame(n),False),([],None))
                self.assertEqual(len(s.carry),4)
            packets,_=s.feed(frame(15+gap),True)
            self.assertEqual([p[0] for p in packets],list(range(11,16+gap)))
            self.assertTrue(s.overlap)
            self.assertTrue(s.overlap_gap)
            turn=s.finish()
            self.assertTrue(turn.overlap_gap)

    def test_long_gap_expires_replay_and_only_keeps_preroll(self):
        s=self.forced_cut()
        for n in range(15,25):self.assertEqual(s.feed(frame(n),False),([],None))
        self.assertEqual(s.carry,[])
        packets,_=s.feed(frame(25),True)
        self.assertEqual([p[0] for p in packets],[23,24,25])
        self.assertFalse(s.overlap)

    def test_short_utterance_survives_300ms_hesitation(self):
        s=Segmenter('transcribe')
        sent=[]
        for n,voice in enumerate([True,False,False,False,True]):
            packets,turn=s.feed(frame(n),voice)
            self.assertIsNone(turn);sent.extend(packets)
        self.assertEqual([p[0] for p in sent],list(range(5)))

    def test_silence_boundary_preferred_after_one_second(self):
        s=Segmenter('transcribe')
        for n in range(9):self.assertIsNone(s.feed(frame(n),True)[1])
        _,turn=s.feed(frame(9),False)
        self.assertIsNotNone(turn)
        self.assertAlmostEqual(turn.end-turn.start,1.0)
        self.assertEqual(len(s.carry),4)
        self.assertTrue(s.carry_pause)

    def test_continuous_speech_has_hard_limit(self):
        s=Segmenter('transcribe');turns=[]
        for n in range(120):
            _,turn=s.feed(frame(n),True)
            if turn:turns.append(turn)
        self.assertEqual(len(turns),8)
        self.assertAlmostEqual(turns[0].end-turns[0].start,1.5)
        self.assertTrue(all(t.end-t.start<=1.901 for t in turns))

    def test_repetition_is_preserved_when_ambiguous(self):
        for previous,current in [('אני חושב','אני חושב אחרת'),('כך אני חושב היום','אני חושב היום'),('это очень важно','очень важно')]:
            self.assertEqual(remove_overlap(previous,current),(current,0))
        self.assertEqual(remove_overlap('היום אנחנו מדברים על הנושא הזה','על הנושא הזה נמשיך לדבר'),('נמשיך לדבר',3))

class HesitationPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_overlap_with_pause_does_not_delete_repeated_words(self):
        r=Runner('transcribe',None,'fake',lambda *args:None)
        s=Session(r,'transcribe');s.previous='היום אנחנו מדברים על הנושא הזה';s.outstanding=1
        now=time.monotonic()
        turn=Turn(1,now-2,now,True,overlap_gap=True)
        text='על הנושא הזה נמשיך לדבר'
        await s.translation_queue.put((turn,text,now))
        with patch('pipeline.translate',return_value=('Перевод',{})) as mocked:
            task=asyncio.create_task(s.translations())
            try:
                await asyncio.wait_for(s.translation_queue.join(),1)
                self.assertEqual(mocked.call_args.args[1],text)
            finally:
                task.cancel();await asyncio.gather(task,return_exceptions=True);r.log.close()
