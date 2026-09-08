"""Default TF2 build order, with generic recording support kept separate."""
MERC_ORDER = ('heavy', 'medic', 'soldier', 'scout', 'demoman', 'engineer', 'sniper', 'spy', 'pyro')

def build_mercs(root, merc='heavy', **options):
    from pathlib import Path
    from phonomenal.builder import build_pack
    root=Path(root)
    order=MERC_ORDER if merc=='all' else (merc,)
    if any(x not in MERC_ORDER for x in order):
        raise ValueError('Unknown TF2 merc')
    for voice in order:
        print(f'=== {voice}: automatic speech pack ===',flush=True)
        build_pack(root/'source'/voice, root/'data/packages'/f'{voice}.vcpack', voice, tf2=True, **options)
