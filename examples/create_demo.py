#!/usr/bin/env python3
"""Make a tiny synthetic-tone pack demonstrating exact sample slicing.

No speech model, microphone, game assets, or personal recordings are required.
These tones are NOT a demonstration of realistic voice quality.
"""
import math
import struct
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from phonomenal.vcpack import write_pack
rate=48000
words=[];phones=[];samples=[]
for i,(word,phone,hz) in enumerate((('hello','HH',180),('there','DH',190),('friend','F',185),('good','G',175),('morning','M',180))):
    start=len(samples)
    for n in range(9600):
        envelope=min(1,n/240,(9599-n)/240)
        samples.append(round(6000*envelope*math.sin(2*math.pi*hz*n/rate)))
    words.append(dict(label=word,start=start,end=len(samples)))
    phones.append(dict(label=phone,word=i,start=start,end=len(samples)))
output=Path(sys.argv[1] if len(sys.argv)>1 else 'examples/demo.vcpack')
write_pack(output,voice='Synthetic format demo',language='en-us',rate=rate,
           pcm=struct.pack('<'+'h'*len(samples),*samples),records=[dict(id='demo',words=words,phones=phones)],
           report=dict(description='Synthetic tones for format/planner testing; not human speech.'),features=False)
print(output)
