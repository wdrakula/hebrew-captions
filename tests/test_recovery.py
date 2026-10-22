import asyncio
import json
import logging
import time
import unittest
from unittest.mock import patch

from test_pipeline import Frame, VOICE
from audio import Turn
from pipeline import Runner, Session, RecognitionStalled, APIError


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    def runner(self):
        runner = Runner('transcribe', None, 'secret-test-key', lambda *args: None)
        self.addCleanup(runner.log.close)
        return runner

    async def producer(self):
        await asyncio.Future()

    async def test_actual_incomplete_websocket_frame_is_recoverable_type(self):
        import websockets
        from websockets.exceptions import ConnectionClosed
        async def truncate(socket, *args):
            # Declares five payload bytes, sends two, then drops the transport.
            socket.transport.write(b'\x81\x05ab')
            socket.transport.close()
        logger = logging.Logger('expected-truncated-frame')
        logger.addHandler(logging.NullHandler())
        async with websockets.serve(truncate, '127.0.0.1', 0, logger=logger) as server:
            port = server.sockets[0].getsockname()[1]
            async with websockets.connect('ws://127.0.0.1:'+str(port)) as socket:
                with self.assertRaises(ConnectionClosed):
                    await asyncio.wait_for(socket.recv(), 2)

    async def test_broken_socket_recovers_without_replaying_audio(self):
        from websockets.exceptions import ConnectionClosedError
        runner = self.runner()
        attempts = []
        async def session_run(session):
            attempts.append(session)
            if len(attempts) == 1:
                await runner.frames.put((Frame(VOICE, time.monotonic(), 'test'), .9))
                raise ConnectionClosedError(None, None)
            self.assertEqual(runner.frames.qsize(), 0)
            runner.stopping = True
        with patch.object(Runner, 'collect', lambda _: self.producer()), patch.object(Session, 'run', session_run):
            await asyncio.wait_for(runner.run(), 3)
        self.assertEqual(len(attempts), 2)
        rows = [json.loads(line) for line in runner.log.path.read_text().splitlines()]
        recovery = next(row for row in rows if row['event'] == 'stt_recovery')
        self.assertEqual(recovery['dropped_capture_frames'], 1)
        self.assertNotIn(runner.key, runner.log.path.read_text())

    async def test_quota_is_not_retried_and_error_is_logged(self):
        runner = self.runner()
        async def session_run(session):
            raise APIError('insufficient_quota')
        with patch.object(Runner, 'collect', lambda _: self.producer()), patch.object(Session, 'run', session_run):
            with self.assertRaises(APIError):
                await runner.run()
        log = runner.log.path.read_text()
        self.assertIn('pipeline_error', log)
        self.assertNotIn('stt_recovery', log)

    async def test_repeated_stall_has_bounded_retries(self):
        runner = self.runner()
        attempts = []
        original_sleep = asyncio.sleep
        async def immediate_sleep(delay): await original_sleep(0)
        async def session_run(session):
            attempts.append(session)
            raise RecognitionStalled('missing final')
        with patch.object(Runner, 'collect', lambda _: self.producer()), patch.object(Session, 'run', session_run), patch('pipeline.asyncio.sleep', immediate_sleep):
            with self.assertRaisesRegex(RuntimeError, 'трёх попыток'):
                await asyncio.wait_for(runner.run(), 1)
        self.assertEqual(len(attempts), 4)

    async def test_missing_final_detected_without_new_audio(self):
        runner = self.runner()
        session = Session(runner, 'transcribe')
        now = time.monotonic()
        session.pending.append(Turn(1, now-40, now-35, committed=now-31))
        class Socket:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def send(self, raw): pass
            async def recv(self): return json.dumps({'type': 'session.updated'})
        async def idle(*args): await asyncio.Future()
        with patch('websockets.connect', return_value=Socket()), patch.object(session, 'send_audio', idle), patch.object(session, 'receive', idle), patch.object(session, 'translations', idle):
            with self.assertRaises(RecognitionStalled):
                await asyncio.wait_for(session.run(), 1)
