import asyncio
import json
import time
import unittest
from unittest.mock import patch
from test_pipeline import VOICE, Frame, Segmenter
from audio import capture, Turn
from pipeline import Session

class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_change_with_completed_read_reopens(self):
        class Pipe:
            async def readexactly(self, n): return bytes(n)
        class Process:
            returncode = None
            stdout = Pipe()
            def terminate(self): self.returncode = 0
            async def wait(self): return 0
        devices = []
        async def spawn(*args, **kwargs):
            devices.append(args[1]); return Process()
        with patch('audio.default_monitor', side_effect=['old', 'new', 'new']), patch('audio.time', __import__('types').SimpleNamespace(monotonic=iter([0,0,2,2,2,2]).__next__)), patch('audio.asyncio.create_subprocess_exec', side_effect=spawn):
            stream = capture()
            frame = await anext(stream)
            self.assertEqual(frame.source, 'new')
            self.assertEqual(devices, ['--device=old', '--device=new'])
            await stream.aclose()

class LiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_not_cut_at_ordinary_boundary(self):
        s = Segmenter('live')
        for n in range(30):
            _, turn = s.feed(Frame(VOICE, 10+n/10, 'x'), True)
            self.assertIsNone(turn)
        for n in range(30,33):
            _, turn = s.feed(Frame(bytes(4800), 10+n/10, 'x'), False)
        self.assertIsNotNone(turn)

    async def test_preview_then_final_reuses_translation(self):
        from pipeline import Runner
        shown=[]
        r=Runner('live',None,'fake',lambda k,v:shown.append((k,v)))
        s=Session(r,'live'); now=time.monotonic(); turn=Turn(1,now-2,now)
        s.preview_at=now-2; s.snapshots[1]=(turn,'שלום עולם',now)
        with patch('pipeline.translate',return_value=('Привет, мир',{})) as translator:
            task=asyncio.create_task(s.translations())
            try:
                for _ in range(30):
                    if any(k=='subtitle' for k,v in shown):break
                    await asyncio.sleep(.02)
                s.snapshots.clear();s.outstanding=1
                await s.translation_queue.put((turn,'שלום עולם',time.monotonic()))
                await asyncio.wait_for(s.translation_queue.join(),1)
                subtitles=[v for k,v in shown if k=='subtitle']
                self.assertEqual([v['provisional'] for v in subtitles],[True,False])
                self.assertEqual(subtitles[0]['id'],subtitles[1]['id'])
                self.assertEqual(translator.call_count,1)
            finally:
                task.cancel();await asyncio.gather(task,return_exceptions=True);r.log.close()
