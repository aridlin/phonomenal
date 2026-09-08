"""Isolated MFA entrypoint with a narrowly detected 3.3.9 refinement fix.

Upstream assigns self.fine_tune twice instead of assigning the tolerance.
Do not change the system package: repair that exact constructor in this process.
"""
import functools
import inspect
import sys
from montreal_forced_aligner.alignment.pretrained import PretrainedAligner

original = PretrainedAligner.__init__
if 'self.fine_tune = fine_tune_boundary_tolerance' in inspect.getsource(original):
    signature = inspect.signature(original)
    @functools.wraps(original)
    def corrected(self, *args, **kwargs):
        values = signature.bind(self, *args, **kwargs)
        values.apply_defaults()
        original(self, *args, **kwargs)
        self.fine_tune = values.arguments['fine_tune']
        self.fine_tune_boundary_tolerance = values.arguments['fine_tune_boundary_tolerance']
    PretrainedAligner.__init__ = corrected
    original_align = PretrainedAligner.align
    @functools.wraps(original_align)
    def align_then_refine(self):
        requested = self.fine_tune
        # In 3.3.9 _align runs before phone intervals are collected into the DB.
        self.fine_tune = False
        try:
            original_align(self)
        finally:
            self.fine_tune = requested
        if requested:
            self.fine_tune_alignments()
    PretrainedAligner.align = align_then_refine

# The same upstream release also has an extra dot in the archive extension,
# looks up numeric database IDs instead of Kaldi utterance keys, and misses the
# final phone intervals when applying refined boundaries. Patch only the exact
# affected function, inside this isolated process. Keep its original license.
import textwrap
import montreal_forced_aligner.alignment.multiprocessing as align_mp
source = textwrap.dedent(inspect.getsource(align_mp.FineTuneFunction._run))
if '"ali", ".ark"' in source:
    source = source.replace('"ali", ".ark"', '"ali", "ark"')
    source = source.replace('AlignmentArchive(ali_path)', 'AlignmentArchive(ali_path, words_file_name=job.construct_path(workflow.working_directory, "words", "ark", d.name))')
    source = source.replace('alignment_archive[utterance.id]', 'alignment_archive[utterance.kaldi_id]')
    start = source.index('            new_boundaries = ctm.phone_boundaries')
    end = source.index('            self.callback(interval_mapping)', start)
    source = source[:start] + """            refined = [p for w in ctm.word_intervals for p in w.phones]
            original_intervals = list(interval_query)
            if len(refined) != len(original_intervals):
                raise RuntimeError(f'Refined phone count {len(refined)} differs from stored alignment {len(original_intervals)}')
            interval_mapping = [dict(id=old.id, begin=new.begin, end=new.end)
                                for old, new in zip(original_intervals, refined)]
""" + source[end:]
    patched = {}
    exec(compile(source, '<phonomenal-mfa-compat>', 'exec'), align_mp.__dict__, patched)
    align_mp.FineTuneFunction._run = patched['_run']

if __name__ == '__main__':
    from montreal_forced_aligner.command_line.mfa import mfa_cli
    raise SystemExit(mfa_cli())
