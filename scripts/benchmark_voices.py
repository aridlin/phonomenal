#!/usr/bin/env python3
"""Render identical prompts for multiple packs and independently transcribe WAVs."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from phonomenal.speech_check import verify_speech


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--pack', action='append', required=True, metavar='LABEL=PATH')
    parser.add_argument('--prompts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', default='small.en')
    parser.add_argument('--strict', action='store_true')
    args=parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    from faster_whisper import WhisperModel
    root=Path(__file__).resolve().parents[1]
    recognizer=WhisperModel(args.model,device='cpu',compute_type='int8',cpu_threads=2,
                           download_root=str(root/'data/cache/asr'))
    prompts=json.loads(args.prompts.read_text())
    for prompt in prompts:
        if not prompt['id'] or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in prompt['id']):
            parser.error('Prompt IDs must contain only letters, digits, hyphens or underscores')
    results=[]
    for entry in args.pack:
        label,separator,path=entry.partition('=')
        if not separator or not label or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in label):
            parser.error('Pack must be LABEL=PATH with a simple label')
        for prompt in prompts:
            case=args.output/(label+'-'+prompt['id']);case.mkdir(parents=True,exist_ok=True)
            wav=case/'render.wav'; started=time.monotonic()
            command=[str(args.cli.resolve()),'--bank',str(Path(path).resolve()),'--text',prompt['text'],'--plan','--output',str(wav),'--audit',str(case/'boundaries.json')]
            if args.strict:command.append('--strict')
            process=subprocess.run(command,capture_output=True,text=True,timeout=180)
            result=dict(voice=label,pack=str(Path(path).resolve()),prompt=prompt,strict=args.strict,
                        synthesis_seconds=time.monotonic()-started,status='failed')
            if process.returncode:
                result['error']=process.stderr.strip()
            else:
                plan=json.loads(process.stdout);(case/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
                result.update(status='rendered',chunks=len(plan['units']),warnings=plan['warnings'],
                              kinds={kind:sum(u['kind']==kind for u in plan['units']) for kind in {u['kind'] for u in plan['units']}})
                result['stt']=verify_speech(wav,prompt['text'],args.model,recognizer=recognizer)
            (case/'result.json').write_text(json.dumps(result,indent=2)+'\n')
            results.append(result)
            (args.output/'results.json').write_text(json.dumps(results,indent=2)+'\n')
            print(label,prompt['id'],result['status'],result.get('stt',{}).get('word_error_rate'),result.get('stt',{}).get('recognized',result.get('error')),flush=True)

if __name__=='__main__':main()
