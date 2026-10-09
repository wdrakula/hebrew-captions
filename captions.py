#!/usr/bin/env python3
"""Launch UI, or short live monitor probes; never read audio files."""
import argparse
import asyncio
import json
import time
from audio import capture, rms, Silero
from config import load_key
from journal import Journal
from pipeline import Runner
from languages import LANGUAGES, TRANSLATORS


async def probe(seconds, source=None):
    vad = Silero()
    stream = capture(source)
    log = Journal('capture-probe')
    begin, frames, voiced, peak = time.monotonic(),0,0,0.
    try:
        async for frame in stream:
            probability = vad.probability(frame.pcm)
            frames += 1
            voiced += probability >= .35
            peak = max(peak,rms(frame.pcm))
            log.emit('capture',rms=rms(frame.pcm),speech_probability=probability,source=frame.source)
            if time.monotonic()-begin>=seconds:
                break
    finally:
        await stream.aclose()
        log.emit('probe_summary',frames=frames,speech_frames=voiced,peak_rms=peak,
            single_core_percent=100*vad.cpu_seconds/max(.001,vad.seconds))
        log.close()
    print(json.dumps({'frames':frames,'speech_frames':voiced,'peak_rms':peak,
        'vad_single_core_percent':100*vad.cpu_seconds/max(.001,vad.seconds),'log':str(log.path)}))


async def live_test(mode,seconds,source=None,speech_language='he',subtitle_language='ru',translator='gpt-4o-mini'):
    subtitles = []
    def emit(kind,value):
        if kind=='subtitle':
            subtitles.append(value)
            value['log'].emit('test_output',sequence=value['sequence'],provisional=value.get('provisional',False),
                from_start_ms=1000*(time.monotonic()-value['start']),
                from_end_ms=1000*(time.monotonic()-value['end']))
            print(json.dumps({'he':value['he'],'ru':value['ru']},ensure_ascii=False),flush=True)
    runner = Runner(mode,source,load_key(),emit,speech_language,subtitle_language,translator)
    async def stop():
        await asyncio.sleep(seconds)
        runner.stopping = True
    timer = asyncio.create_task(stop())
    try:
        await runner.run()
    finally:
        timer.cancel()
        await asyncio.gather(timer,return_exceptions=True)
        runner.log.close()
        print(json.dumps({'subtitles':len(subtitles),'log':str(runner.log.path)}),flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--probe',type=float)
    parser.add_argument('--test-mode',choices=['live','transcribe'])
    parser.add_argument('--seconds',type=float,default=12)
    parser.add_argument('--source')
    parser.add_argument('--speech-language',choices=list(LANGUAGES),default='he')
    parser.add_argument('--subtitle-language',choices=list(LANGUAGES),default='ru')
    parser.add_argument('--translator',choices=list(TRANSLATORS),default='gpt-4o-mini')
    args=parser.parse_args()
    if args.probe:
        asyncio.run(probe(args.probe,args.source))
    elif args.test_mode:
        asyncio.run(live_test(args.test_mode,args.seconds,args.source,args.speech_language,args.subtitle_language,args.translator))
    else:
        from gui import App
        App().root.mainloop()


if __name__=='__main__':
    main()
