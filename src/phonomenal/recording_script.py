"""Original recording material, ordered by measured phonetic coverage.

Each line is a separate take. The greedy ordering covers rarer phone pairs early;
the whole script also supplies useful words, phrases, and connected speech.
"""
from __future__ import annotations
import collections
import json
import re
from pathlib import Path

TEXT = '''Please check the microphone before we begin, and leave a little silence at the end.
Hello there. My name is whatever you would like to call me today.
I need a little more time to think about that question.
Could you bring me a glass of water and a clean blue cup?
Thank you very much. That was exactly what I needed.
I am ready when you are, but there is no need to rush.
Wait a moment. I think somebody left the window open.
We should meet outside the station just before the last train arrives.
The small red house stood beside a broad river and a narrow wooden bridge.
A cheerful young woman watched the birds gather beneath the old oak tree.
Three thin threads hung from the thick wool blanket.
Those other shoes are smoother than the ones that I wore yesterday.
She usually measures the sugar with a silver spoon.
The judge enjoyed a gentle joke about a giant jar of jam.
Choose the cheaper chair, then check whether the cushion is comfortable.
Fresh fish should be kept cool until the kitchen is ready.
Five brave friends drove through the village in a very noisy van.
The bright yellow light flickered twice and finally went out.
We found a round brown stone beneath the ground near the fountain.
The boy pointed toward the noisy crowd and smiled with genuine joy.
A curious tourist poured pure water into the little metal bottle.
The nurse heard the first word clearly, but the third word sounded blurred.
Put the full basket beside the good wooden cupboard.
The green leaves seemed to gleam after the brief evening rain.
A black cat sat on a flat mat while a fat rat ran past.
Ten red hens left their empty nest and went toward the fence.
The little kitten slipped into a hidden gap behind the kitchen sink.
Stop at the shop and ask whether the copper pot is still hot.
The tall man bought four small balls and a warm waterproof coat.
We must cut the crust before we put the butter on the bread.
The school has a cool blue room with enough space for two groups.
The pale grey train came late, so we waited near the gate.
I might try to write a short reply before the bright night sky grows dark.
Please show me the road that goes past the old stone home.
Their weary parents carried the heavy chairs down the narrow stairs.
A quiet choir sang a warm song while the square filled with people.
The quick brown fox jumped over a shallow stream and shook its wet tail.
Six sleek swans swam slowly past the reeds in the silent lake.
A strong spring breeze spread fresh straw across the street.
Bring the green grapes, the crisp bread, and the bright orange fruit.
The broken glass glittered briefly before we swept it into a bag.
We packed the clothes, closed the bags, and checked the locks twice.
The last guest asked for a small slice of freshly baked cake.
She washed the dishes, brushed her teeth, and switched off the light.
He watched the match, missed the bus, and reached the bridge after lunch.
They walked through the fields while the dogs barked at distant sheep.
I liked the first plan, but I loved the second one even more.
The masks were mixed with old maps, spare keys, and bits of string.
A glimpse of the stars brought a strange sense of calm.
The sixth shelf holds the spare lamps and the largest empty boxes.
Please do not move the green marker until I tell you where it belongs.
Turn left at the next corner, then keep going until you see the library.
Open the door, switch on the light, and take a seat beside me.
Close the window gently so that the sleeping child does not wake up.
Would you like some tea, a little coffee, or a bowl of soup?
I would rather stay at home tonight and finish reading this book.
You can leave a message if I do not answer the telephone.
There is something unusual about the way this machine makes that sound.
I cannot find the cable that connects the keyboard to the computer.
Save the file before you close the application or restart the system.
The connection failed because the address was wrong, so we tried again.
Please increase the volume a little and tell me whether you can hear me.
I can hear your voice clearly, but there is a soft buzzing in the background.
Let us try another example with a completely different sentence.
This recording should sound natural, relaxed, and easy to understand.
Speak at your usual pace and keep the distance from the microphone steady.
If you make a mistake, stop, breathe, and read the whole sentence again.
The package contains a collection of words, sounds, and useful short phrases.
A small change in timing can make a familiar word surprisingly difficult to understand.
The beginning of the sound matters just as much as the ending.
Keep the soft consonants clear without stretching every vowel into a song.
I thought you said the meeting was on Thursday, not Tuesday.
Are you certain that this is the right place to wait?
Who left these keys on the table beside the kitchen door?
Where did you put the small blue box that arrived this morning?
When will the next train leave, and how long does the journey take?
Why does this button work only after I press the other one?
How many people would like to join us for dinner tomorrow?
Which version should I choose if I want the fastest result?
That is a wonderful idea. Let us give it a try.
I am sorry, but I do not think that will work as expected.
No problem. We can fix it together after a short break.
Be careful. The floor is wet and the steps are quite steep.
Look out for the branch above your head when you walk through the gate.
Welcome back. It is good to hear your voice again.
Good morning, good afternoon, and good evening to everyone listening.
I agree with the general idea, although a few details still need attention.
We have already finished most of the work that we planned for today.
There are several ways to solve this problem, and each has a different cost.
First check the result, then compare it with the original example.
The answer depends on the size of the file and the speed of the machine.
I have never heard that particular word before, but I can try to pronounce it.
Some words look alike on the page even though their sounds are quite different.
I will read this book today, just as I read the first chapter yesterday.
Tie a bright bow around the box, then bow politely to the audience.
The wind grew stronger as she began to wind the thin cord around the wheel.
They were close friends, so he asked her to close the door quietly.
We present the results today and leave a small present on your desk.
The minute details took more than a minute to explain.
Zero, one, two, three, four, five, six, seven, eight, nine, and ten.
Eleven, twelve, thirteen, fourteen, fifteen, sixteen, seventeen, eighteen, nineteen, and twenty.
Thirty, forty, fifty, sixty, seventy, eighty, ninety, one hundred, and one thousand.
Half a cup, a quarter of an hour, and three quarters of a mile.
The temperature fell below zero shortly after midnight.
Our appointment is at half past seven on the first Friday in February.
January was cold, March was windy, and April brought long gentle showers.
May and June passed quickly, while July and August felt unusually warm.
September, October, November, and December filled the calendar with plans.
Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, and Sunday all felt different.
North of the river, south of the station, east of the hill, and west of the park.
Add the total, subtract the discount, and divide the rest into equal parts.
A hundred small choices can gradually become one important decision.
The beautiful view was partly hidden by a huge pale cloud.
An enthusiastic musician played a unusual rhythm on a handmade wooden drum.
The zoo keeper carefully examined the zebra before opening the gate.
A beige jacket lay beside a purple scarf and a pair of orange gloves.
The treasure was hidden near an ancient arch at the edge of the village.
We occasionally enjoy a leisurely walk after an exceptionally busy afternoon.
The engine hummed softly while the passengers waited for departure.
The hungry children laughed when the clumsy puppy chased its own tail.
An honest answer is usually more useful than a pleasant excuse.
The rhythm of everyday speech changes when we ask a question or tell a story.
I am still here, and I am listening to everything you say.
That is all for now. Thank you for your patience, and have a lovely day.'''


def optimized_script():
    import cmudict
    dictionary = cmudict.dict()
    lines = TEXT.splitlines()
    inventories = []
    for line in lines:
        words = re.findall(r"[a-z]+(?:'[a-z]+)*", line.lower())
        phones = [p.rstrip('012') for w in words for p in dictionary.get(w, [[]])[0]]
        inventories.append(set(('phone',p) for p in phones) | set(zip(phones, phones[1:])))
    frequency = collections.Counter(x for units in inventories for x in units)
    covered, ordered, remaining = set(), [], set(range(len(lines)))
    while remaining:
        index = max(remaining, key=lambda i: (sum((4 if x[0]=='phone' else 1)/frequency[x]**.5 for x in inventories[i]-covered) / len(lines[i].split())**.35, -i))
        ordered.append(lines[index]);covered |= inventories[index];remaining.remove(index)
    return ordered, dict(sentences=len(lines), words=sum(len(x.split()) for x in lines), phones=sorted(x[1] for x in covered if x[0]=='phone'), adjacent_phone_pairs=sum(x[0]!='phone' for x in covered), method='greedy weighted phone/pair coverage over original sentences; not exhaustive diphone coverage')


def export_script(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lines, coverage = optimized_script()
    for i, line in enumerate(lines, 1):
        (directory/f'take_{i:03d}.txt').write_text(line+'\n', encoding='utf-8')
    (directory/'script.txt').write_text('\n\n'.join(f'{i:03d}. {line}' for i,line in enumerate(lines,1))+'\n', encoding='utf-8')
    (directory/'coverage.json').write_text(json.dumps(coverage,indent=2)+'\n')
    return coverage
