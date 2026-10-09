"""PulseAudio capture and low-cost local speech detection."""
import asyncio
from collections import deque
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import time
import numpy as np

RATE = 24000
FRAME_SAMPLES = 2400
FRAME_BYTES = FRAME_SAMPLES * 2


def pulse(*args):
    result = subprocess.run(['pactl', *args], capture_output=True, text=True, timeout=4,
                            env={**os.environ, 'LC_ALL': 'C.UTF-8'})
    if result.returncode:
        raise RuntimeError('Нет подключения к PulseAudio')
    return result.stdout


def outputs():
    return [(s['monitor_source'], s.get('properties', {}).get('device.description') or
             s.get('description') or s['name']) for s in json.loads(pulse('-f', 'json', 'list', 'sinks'))]


def default_monitor():
    name = pulse('get-default-sink').strip()
    sinks = json.loads(pulse('-f', 'json', 'list', 'sinks'))
    return next(s['monitor_source'] for s in sinks if s['name'] == name)


def rms(pcm):
    x = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
    return float(np.sqrt(np.mean(x*x))) if len(x) else 0.


class Silero:
    """Pinned Silero v6.2 ONNX ABI, 16 kHz, one CPU thread, stateful resampling."""
    def __init__(self):
        import onnxruntime as ort
        from scipy.signal import firwin
        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.log_severity_level = 3
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(str(Path(__file__).parent / 'models/silero_vad.onnx'),
            sess_options=options, providers=['CPUExecutionProvider'])
        self.filter = firwin(49, 1/3) * 2  # streaming 24k → up2/down3 → 16k
        self.reset()
        self.seconds = self.cpu_seconds = 0.

    def reset(self):
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, 64), dtype=np.float32)
        self.buffer = np.empty(0, dtype=np.float32)
        self.zi = np.zeros(len(self.filter)-1)
        self.phase = 0

    def probability(self, pcm):
        from scipy.signal import lfilter
        begin = time.thread_time()
        x = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
        up = np.zeros(len(x)*2, dtype=np.float32)
        up[::2] = x
        filtered, self.zi = lfilter(self.filter, [1.], up, zi=self.zi)
        offset = (-self.phase) % 3
        down = filtered[offset::3].astype(np.float32)
        self.phase = (self.phase + len(up)) % 3
        self.buffer = np.concatenate((self.buffer, down))
        probabilities = []
        while len(self.buffer) >= 512:
            block, self.buffer = self.buffer[:512].reshape(1,512), self.buffer[512:]
            inp = np.concatenate((self.context, block), axis=1)
            value, self.state = self.session.run(None, {'input': inp, 'state': self.state,
                                                       'sr': np.array(16000, dtype=np.int64)})
            self.context = inp[:, -64:]
            probabilities.append(float(value[0,0]))
        self.seconds += len(x) / RATE
        self.cpu_seconds += time.thread_time() - begin
        return max(probabilities, default=0.)


@dataclass
class Frame:
    pcm: bytes
    end: float
    source: str
    changed: bool = False


async def capture(source=None):
    """Follow default route; detect route changes even when old monitor disappears."""
    while True:
        selected = source or await asyncio.to_thread(default_monitor)
        proc = await asyncio.create_subprocess_exec('parec', '--device='+selected, '--raw',
            '--format=s16le', '--rate=24000', '--channels=1', '--latency-msec=50',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        first, checked = True, time.monotonic()
        try:
            while True:
                read = asyncio.create_task(proc.stdout.readexactly(FRAME_BYTES))
                read_started = time.monotonic()
                route_changed = False
                try:
                    while True:
                        done, _ = await asyncio.wait([read], timeout=.5)
                        now = time.monotonic()
                        if not source and now - checked >= 1:
                            checked = now
                            if await asyncio.to_thread(default_monitor) != selected:
                                route_changed = True
                                break
                        if done:
                            try:
                                pcm = read.result()
                            except asyncio.IncompleteReadError:
                                if not source and await asyncio.to_thread(default_monitor) != selected:
                                    route_changed = True
                                    break
                                raise RuntimeError('Устройство вывода недоступно')
                            yield Frame(pcm, now, selected, first)
                            first = False
                            break
                        if now - read_started > 5:
                            raise RuntimeError('Устройство не передаёт звук')
                    if route_changed:  # restart even when the old read already completed
                        break
                finally:
                    if not read.done():
                        read.cancel()
                    await asyncio.gather(read, return_exceptions=True)
        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 2)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()


@dataclass
class Turn:
    sequence: int
    start: float
    end: float
    overlap: bool = False
    committed: float = 0.
    first_delta: float | None = None


class Segmenter:
    """Live ends at pauses (6s safety cap); normal carries 0.4s across 1.2s cuts."""
    def __init__(self, mode, maximum=None):
        self.mode = mode
        self.maximum = maximum if maximum is not None else (6.0 if mode == "live" else 1.2)
        self.pre = deque(maxlen=3)
        self.tail = deque(maxlen=4)
        self.carry = []
        self.active = False
        self.sequence = 0
        self.start = self.end = self.last_voice = self.fresh_start = 0.
        self.overlap = False

    def feed(self, frame, voiced):
        send = []
        now = frame.end
        if not self.active:
            self.pre.append(frame)
            if not voiced:
                self.carry = []
                return [], None
            self.active = True
            self.overlap = bool(self.carry)
            frames = self.carry + [frame] if self.carry else list(self.pre)
            self.start = frames[0].end - .1
            self.fresh_start = frame.end - .1
            self.tail.clear()
            self.tail.extend(frames)
            self.pre.clear()
            self.carry = []
            send = [f.pcm for f in frames]
        else:
            send = [frame.pcm]
            self.tail.append(frame)
        self.end = now
        if voiced:
            self.last_voice = now
        forced = now-self.fresh_start >= self.maximum - .001
        if forced or now-self.last_voice >= .3 - .001:
            return send, self.finish(forced)
        return send, None

    def finish(self, forced=False):
        if not self.active:
            return None
        self.sequence += 1
        turn = Turn(self.sequence, self.start, self.end, self.overlap)
        self.carry = list(self.tail) if forced and self.mode == 'transcribe' else []
        self.tail.clear()
        self.active = False
        return turn
