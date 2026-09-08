"""Lossless editable projects for v1 voice packs. Original packs are immutable.

JSON uses absolute integer sample positions in master.wav. Unknown optional
sections survive as base64; FEAT and QARE are regenerated after manual edits.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import html
import json
import shutil
from pathlib import Path
import struct
import wave
import uuid

from phonomenal.vcpack import HEADER, DIRECTORY, inspect_pack, write_pack, validate_records


class Reader:
    def __init__(self, data): self.data, self.pos = data, 0
    def unpack(self, fmt):
        size = struct.calcsize(fmt)
        if self.pos + size > len(self.data): raise ValueError('Truncated typed section')
        value = struct.unpack_from(fmt, self.data, self.pos); self.pos += size
        return value
    def count(self):
        n, = self.unpack('<I')
        if n > len(self.data) - self.pos: raise ValueError('Invalid count')
        return n
    def string(self):
        n = self.count(); value = self.data[self.pos:self.pos+n].decode('utf-8'); self.pos += n
        return value
    def done(self):
        if self.pos != len(self.data): raise ValueError('Unexpected typed section suffix')


def read_pack(path):
    report = inspect_pack(path); raw = Path(path).read_bytes()
    _, _, count, _ = HEADER.unpack_from(raw); sections = {}
    for i in range(count):
        tag, _, start, length, _, _ = DIRECTORY.unpack_from(raw, HEADER.size+i*DIRECTORY.size)
        sections[tag] = raw[start:start+length]
    r = Reader(sections[b'META'])
    metadata = dict(voice=r.string(), language=r.string(), alphabet=r.string(), rate=r.unpack('<I')[0]); r.done()
    if metadata['alphabet'] != 'arpabet': raise ValueError('Unsupported phonetic alphabet')
    r = Reader(sections[b'RECS']); records = []
    for _ in range(r.count()):
        record = dict(id=r.string(), transcript=r.string(), words=[], phones=[])
        for _ in range(r.count()):
            label = r.string(); start, end, confidence = r.unpack('<QQf')
            record['words'].append(dict(label=label, start=start, end=end, confidence=None if confidence < 0 else confidence))
        for _ in range(r.count()):
            label = r.string(); word, start, end, confidence = r.unpack('<iQQf')
            record['phones'].append(dict(label=label, word=word, start=start, end=end, confidence=None if confidence < 0 else confidence))
        records.append(record)
    r.done(); lexicon = {}
    if b'LEXI' in sections:
        r = Reader(sections[b'LEXI'])
        for _ in range(r.count()):
            word = r.string(); lexicon[word] = [r.string() for _ in range(r.count())]
        r.done()
    extras = {tag.decode('ascii'): base64.b64encode(data).decode('ascii') for tag, data in sections.items()
              if tag not in {b'META', b'RECS', b'AUDI', b'LEXI', b'FEAT', b'QARE', b'SPEC'}}
    validate_records(records, len(sections[b'AUDI'])//2, metadata['rate'])
    return metadata, records, lexicon, extras, sections[b'AUDI'], report


def json_write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def open_project(pack, project):
    metadata, records, lexicon, extras, pcm, report = read_pack(pack)
    project = Path(project); project.mkdir(parents=True, exist_ok=False)
    json_write(project/'metadata.json', metadata)
    json_write(project/'lexicon.json', lexicon)
    json_write(project/'extensions.json', extras)
    json_write(project/'provenance.json', dict(source_sha256=hashlib.sha256(Path(pack).read_bytes()).hexdigest(), original_report=report))
    with wave.open(str(project/'master.wav'), 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(metadata['rate']); out.writeframes(pcm)
    entries = []
    for i, record in enumerate(records):
        filename = f'record-{i:06d}.json'; json_write(project/filename, record)
        entries.append(filename+'\t'+record['id'].replace('\t',' ').replace('\n',' ')+' | '+record.get('transcript','').replace('\t',' ').replace('\n',' ')[:110])
    (project/'index.tsv').write_text('\n'.join(entries)+'\n', encoding='utf-8')
    return dict(project=str(project), recordings=len(records), rate=metadata['rate'])


def read_audio(project):
    with wave.open(str(Path(project)/'master.wav'), 'rb') as f:
        if f.getnchannels()!=1 or f.getsampwidth()!=2 or f.getcomptype()!='NONE':
            raise ValueError('Editor master must be uncompressed mono PCM16 WAV')
        return f.getframerate(), f.readframes(f.getnframes())


def replace_audio(project, source):
    project=Path(project); source=Path(source)
    metadata=json.loads((project/'metadata.json').read_text(encoding='utf-8'))
    with wave.open(str(source),'rb') as f:
        if f.getnchannels()!=1 or f.getsampwidth()!=2 or f.getcomptype()!='NONE' or not f.getnframes():
            raise ValueError('Replacement audio must be nonempty mono PCM16 WAV')
        if f.getframerate()!=metadata['rate']:raise ValueError('Replacement audio must use the same sample rate as the project')
    shutil.copyfile(project/'master.wav',project/'master.previous.wav')
    temporary=project/'master.next.wav';shutil.copyfile(source,temporary);temporary.replace(project/'master.wav')
    return dict(audio_replaced=True,warning='Check every recording interval if the audio length or content changed')


def change_record(project, index, delete=False):
    project=Path(project)
    if index<0:raise ValueError('Invalid recording index')
    path=project/f'record-{index:06d}.json'
    record=json.loads(path.read_text(encoding='utf-8'))
    existing=sorted(project.glob('record-*.json'))
    if delete:
        if len(existing)<=1:raise ValueError('Keep at least one recording in the project')
        path.rename(path.with_suffix('.deleted'))
    else:
        index=max(int(p.stem.split('-')[1]) for p in existing if p.stem.split('-')[1].isdigit())+1
        record['id'] += '-copy-'+uuid.uuid4().hex[:8]
        json_write(project/f'record-{index:06d}.json',record)
    entries=[]
    for p in sorted(project.glob('record-*.json')):
        if not p.stem.split('-')[1].isdigit():continue
        r=json.loads(p.read_text(encoding='utf-8'))
        entries.append(p.name+'\t'+r['id'].replace('\n',' ').replace('\t',' ')+' | '+r.get('transcript','').replace('\n',' ').replace('\t',' ')[:110])
    (project/'index.tsv').write_text('\n'.join(entries)+'\n',encoding='utf-8')
    return dict(recordings=len(entries))


def save_project(project, output):
    project = Path(project); output = Path(output)
    if output.exists(): raise ValueError('Save to a new filename; existing packs are never overwritten')
    metadata = json.loads((project/'metadata.json').read_text(encoding='utf-8'))
    rate, pcm = read_audio(project)
    if metadata['rate'] != rate: raise ValueError('Metadata rate must match master.wav; resample audio explicitly')
    if metadata.get('alphabet') != 'arpabet': raise ValueError('Alphabet must remain arpabet')
    records = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(project.glob('record-*.json')) if p.stem.split('-')[1].isdigit()]
    if not records: raise ValueError('A pack needs at least one recording')
    validate_records(records, len(pcm)//2, rate)
    lexicon = json.loads((project/'lexicon.json').read_text(encoding='utf-8'))
    if not isinstance(lexicon, dict) or any(not isinstance(w,str) or not w or not isinstance(ps,list) or not ps or any(not isinstance(p,str) or not p for p in ps) for w,ps in lexicon.items()):
        raise ValueError('Lexicon must map nonempty words to lists of phone labels')
    extras = {tag:base64.b64decode(data, validate=True) for tag,data in json.loads((project/'extensions.json').read_text()).items()}
    provenance = json.loads((project/'provenance.json').read_text(encoding='utf-8'))
    from phonomenal.boundary_audit import audit_boundaries
    audits = []
    for record in records:
        lo=min(w['start'] for w in record['words']); hi=max(w['end'] for w in record['words'])
        local = lambda units: [dict(u,start=u['start']-lo,end=u['end']-lo) for u in units]
        audits.append(dict(id=record['id'], source_offset_sample=lo, **audit_boundaries(local(record['words']),local(record['phones']),pcm[lo*2:hi*2],rate)))
    report = dict(manual_edit=True, boundary_accuracy='unmeasured after manual edits',
                  source_pack_sha256=provenance['source_sha256'],
                  boundary_audit=dict(every_boundary_checked=True, boundaries_checked=sum(a['boundaries_checked'] for a in audits),
                                      flagged_boundaries=sum(a['flagged_boundaries'] for a in audits), recordings=audits))
    # Retain provenance/licenses without carrying forward stale accuracy claims.
    report['licenses'] = provenance.get('original_report', {}).get('licenses', {})
    return write_pack(output, voice=metadata['voice'], language=metadata['language'], rate=rate, pcm=pcm,
                      records=records, lexicon=lexicon, report=report, extra_sections=extras,
                      lexicon_overrides=True)


def preview(project, record_index, output, start=None, end=None):
    import numpy as np
    project=Path(project); output=Path(output)
    if record_index < 0: raise ValueError('Invalid recording index')
    record=json.loads((project/f'record-{record_index:06d}.json').read_text(encoding='utf-8'))
    rate,pcm=read_audio(project); validate_records([record],len(pcm)//2,rate)
    lo=min(w['start'] for w in record['words']);hi=max(w['end'] for w in record['words'])
    if start is not None:lo=start
    if end is not None:hi=end
    if not 0<=lo<hi<=len(pcm)//2:raise ValueError('Preview sample interval is outside master audio')
    clip=pcm[lo*2:hi*2]; output.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(output),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(clip)
    values=np.frombuffer(clip,dtype='<i2'); points=[]
    for x in range(1000):
        chunk=values[x*len(values)//1000:max(x*len(values)//1000+1,(x+1)*len(values)//1000)]
        points.append(f'M{x},{90-float(chunk.max())/32768*75:.2f}V{90-float(chunk.min())/32768*75:.2f}')
    svg=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 255" role="img" aria-label="Recording waveform and sample boundaries">',
         '<rect width="1000" height="255" fill="#282828"/>', '<path stroke="#b8bb26" d="'+' '.join(points)+'"/>']
    for tier,y,color in [('words',192,'#fabd2f'),('phones',228,'#83a598')]:
        for unit in record[tier]:
            if unit['end']<=lo or unit['start']>=hi:continue
            x=(unit['start']-lo)*1000/(hi-lo);end=(unit['end']-lo)*1000/(hi-lo)
            label=html.escape(unit['label']); title=html.escape(f"{unit['label']}: {unit['start']}:{unit['end']} samples ({unit['start']*1000/rate:.3f}:{unit['end']*1000/rate:.3f} ms)")
            svg.append(f'<g><title>{title}</title><path stroke="{color}" opacity=".6" d="M{x:.2f},5V{y}H{end:.2f}"/><text x="{x+2:.2f}" y="{y+14}" fill="{color}" font-size="12">{label}</text></g>')
    svg.append('</svg>'); output.with_suffix('.svg').write_text(''.join(svg),encoding='utf-8')
    return dict(start_sample=lo,end_sample=hi,rate=rate)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('action',choices=['open','save','preview','replace-audio','clone-record','delete-record'])
    parser.add_argument('--project',type=Path,required=True);parser.add_argument('--pack',type=Path)
    parser.add_argument('--output',type=Path);parser.add_argument('--record',type=int,default=0)
    parser.add_argument('--input',type=Path)
    parser.add_argument('--start',type=int);parser.add_argument('--end',type=int)
    args=parser.parse_args(argv)
    if args.action=='open':
        if not args.pack: parser.error('open requires --pack')
        result=open_project(args.pack,args.project)
    elif args.action in ('clone-record','delete-record'):
        result=change_record(args.project,args.record,args.action=='delete-record')
    elif args.action=='replace-audio':
        if not args.input:parser.error('replace-audio requires --input')
        result=replace_audio(args.project,args.input)
    else:
        if not args.output:parser.error('save/preview requires --output')
        result=save_project(args.project,args.output) if args.action=='save' else preview(args.project,args.record,args.output,args.start,args.end)
    print(json.dumps({k:v for k,v in result.items() if k!='boundary_audit'},ensure_ascii=False))


if __name__=='__main__':main()
