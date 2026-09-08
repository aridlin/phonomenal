from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from phonomenal.align import align_merc, load_alignment_state, save_alignment_state
from phonomenal.audio import build_merc_master
from phonomenal.config import default_layout, resolve_mercs
from phonomenal.exporter import export_manifests
from phonomenal.packager import pack_voice_bank
from phonomenal.splicer import SplicerService, run_splicer_server, write_splice_result
from phonomenal.tf2_source import fetch_merc, load_catalog, scan_local_source_merc


def _common_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="phonomenal")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root. Defaults to current directory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser("fetch-tf2", help="Fetch TF2 source clips for one merc or all mercs.")
    fetch_parser.add_argument("--merc", default="all", help="Merc name or 'all'.")
    fetch_parser.add_argument("--limit", type=int, default=None, help="Optional max number of clips per merc.")
    fetch_parser.add_argument("--force", action="store_true", help="Re-download clips even if they already exist.")

    scan_parser = subparsers.add_parser("scan-source", help="Scan local TF2 source files from ./source into catalogs.")
    scan_parser.add_argument("--merc", default="all", help="Merc name or 'all'.")
    scan_parser.add_argument("--limit", type=int, default=None, help="Optional max number of clips per merc.")

    combine_parser = subparsers.add_parser(
        "combine-source",
        help="Build one normalized master WAV per merc from the local source catalog.",
    )
    combine_parser.add_argument("--merc", default="all", help="Merc name or 'all'.")
    combine_parser.add_argument("--limit", type=int, default=None, help="Optional max number of clips per merc.")
    combine_parser.add_argument("--force", action="store_true", help="Rebuild master WAVs even if they exist.")

    align_parser = subparsers.add_parser("align", help="Normalize audio, transcribe, and MFA-align clips.")
    align_parser.add_argument("--merc", default="all", help="Merc name or 'all'.")
    align_parser.add_argument("--whisper-model", default="medium.en", help="WhisperX model name.")
    align_parser.add_argument("--batch-size", type=int, default=8, help="WhisperX batch size.")
    align_parser.add_argument("--mfa-command", default="mfa", help="Command prefix used to invoke MFA.")
    align_parser.add_argument("--force", action="store_true", help="Re-normalize audio before alignment.")

    export_parser = subparsers.add_parser("export", help="Validate and write final per-merc and merged JSON.")
    export_parser.add_argument("--merc", default="all", help="Merc name or 'all'.")

    build_parser = subparsers.add_parser("build-tf2", help="Run fetch, align, and export end-to-end.")
    build_parser.add_argument("--merc", default="all", help="Merc name or 'all'.")
    build_parser.add_argument("--limit", type=int, default=None, help="Optional max number of clips per merc.")
    build_parser.add_argument("--whisper-model", default="medium.en", help="WhisperX model name.")
    build_parser.add_argument("--batch-size", type=int, default=8, help="WhisperX batch size.")
    build_parser.add_argument("--mfa-command", default="mfa", help="Command prefix used to invoke MFA.")
    build_parser.add_argument("--force", action="store_true", help="Re-download and re-normalize assets.")

    phenomenise_parser = subparsers.add_parser(
        "phenomenise",
        help="Scan local source, align clips, build per-merc master WAVs, and export manifests.",
    )
    phenomenise_parser.add_argument("--merc", default="all", help="Merc name or 'all'.")
    phenomenise_parser.add_argument("--limit", type=int, default=None, help="Optional max number of clips per merc.")
    phenomenise_parser.add_argument("--whisper-model", default="medium.en", help="WhisperX model name.")
    phenomenise_parser.add_argument("--batch-size", type=int, default=8, help="WhisperX batch size.")
    phenomenise_parser.add_argument("--mfa-command", default="mfa", help="Command prefix used to invoke MFA.")
    phenomenise_parser.add_argument("--force", action="store_true", help="Rebuild normalized and master audio.")

    splice_parser = subparsers.add_parser(
        "splice",
        help="Synthesize a merc voice line from the aligned bank and write WAV output.",
    )
    splice_parser.add_argument("--merc", required=True, help="Merc name.")
    splice_parser.add_argument("--text", required=True, help="Text to synthesize.")
    splice_parser.add_argument("--output", type=Path, default=None, help="Write WAV output to this path.")
    splice_parser.add_argument("--stdout-wav", action="store_true", help="Write raw WAV bytes to stdout.")
    splice_parser.add_argument("--manifest", type=Path, default=None, help="Optional manifest to load instead of aligned state.")
    splice_parser.add_argument("--crossfade-ms", type=int, default=12, help="Join crossfade in milliseconds.")

    splice_plan_parser = subparsers.add_parser(
        "splice-plan",
        help="Print the chunk/phoneme synthesis plan as JSON.",
    )
    splice_plan_parser.add_argument("--merc", required=True, help="Merc name.")
    splice_plan_parser.add_argument("--text", required=True, help="Text to plan.")
    splice_plan_parser.add_argument("--manifest", type=Path, default=None, help="Optional manifest to load instead of aligned state.")

    serve_parser = subparsers.add_parser(
        "serve-splicer",
        help="Run a small local HTTP server for planning and synthesis.",
    )
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    serve_parser.add_argument("--port", type=int, default=8768, help="Port to bind.")

    pack_parser = subparsers.add_parser(
        "pack-bank",
        help="Write a native-friendly merc bank package for the C++ runtime.",
    )
    pack_parser.add_argument("--merc", default="all", help="Merc name or 'all'.")
    pack_parser.add_argument("--output", type=Path, default=None, help="Optional output path for a single merc package.")
    pack_parser.add_argument(
        "--bundle-master",
        action="store_true",
        help="Copy the merc master WAV next to the package and store a local relative path.",
    )

    build = subparsers.add_parser("build-pack", help="Build a self-contained voice pack from any speech folder.")
    build.add_argument("source", type=Path)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--voice", required=True)
    build.add_argument("--language", default="en")
    build.add_argument("--whisper-model", default="small.en")
    build.add_argument("--mfa-command", default="mfa")
    build.add_argument("--acoustic-model", default="english_us_arpa")
    build.add_argument("--work", type=Path)
    build.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    build.add_argument("--force", action="store_true")
    build.add_argument("--tf2", action="store_true", help="Exclude TF2 robot-voice variants and test files")
    verify = subparsers.add_parser("verify-speech", help="Transcribe generated audio without prompt hints and report word errors.")
    verify.add_argument("audio", type=Path)
    verify.add_argument("--text", required=True)
    verify.add_argument("--model", default="small.en")
    verify.add_argument("--json-output", type=Path)
    verify.add_argument("--require-match", action="store_true", help="Exit 2 if recognized words differ.")
    extend = subparsers.add_parser("extend-pack", help="Add optional binary sections and an ASCII specification without changing voice data.")
    extend.add_argument("pack", type=Path)
    extend.add_argument("--output", type=Path, help="Default: atomically update the input pack.")
    extend.add_argument("--section", action="append", default=[], metavar="TAG=FILE", help="Four ASCII bytes, equals sign, binary payload file; repeatable.")
    inspect = subparsers.add_parser("inspect-pack", help="Validate checksums and show pack quality report.")
    inspect.add_argument("pack", type=Path)
    convert = subparsers.add_parser("convert-pack", help="Embed existing aligned state and master in .vcpack.")
    convert.add_argument("--voice", required=True)
    convert.add_argument("--output", required=True, type=Path)
    compare = subparsers.add_parser("compare-alignments", help="Measure word/phone boundary errors against independent references.")
    compare.add_argument("reference", type=Path)
    compare.add_argument("predicted", type=Path)
    compare.add_argument("--tolerance-ms", type=float, default=10.)

    script = subparsers.add_parser("recording-script", help="Export the original optimized reading script and per-take transcripts.")
    script.add_argument("--output", type=Path, required=True)

    merc = subparsers.add_parser("build-mercs", help="Build TF2 packs: Heavy, Medic, Soldier, then the rest.")
    merc.add_argument("--merc", default="heavy")
    merc.add_argument("--mfa-command", default="mfa")
    merc.add_argument("--whisper-model", default="small.en")
    merc.add_argument("--force", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _common_parser()
    args = parser.parse_args(argv)
    layout = default_layout(args.root)
    mercs = resolve_mercs(args.merc) if hasattr(args, "merc") else []

    if args.command == "verify-speech":
        from phonomenal.speech_check import verify_speech
        result = verify_speech(args.audio, args.text, args.model)
        if args.json_output:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
        print("STT heard: " + (result['recognized'] or '(nothing)'))
        print("Expected: " + result['expected'])
        print(f"Word error rate: {result['word_error_rate']:.1%} ({result['word_errors']} errors / {result['reference_words']} words)")
        if result['spacing_only_difference']:
            print("The recognized letters match; only word spacing differs. Raw word error rate is retained above.")
        for edit in result['differences']:
            print(f"  {edit['operation']}: {edit['expected']!r} -> {edit['heard']!r}")
        print(result['limitation'])
        return 2 if args.require_match and not result['words_match'] else 0
    if args.command == "build-mercs":
        from phonomenal.mercs import build_mercs
        build_mercs(layout.root, args.merc, mfa_command=args.mfa_command, model=args.whisper_model, force=args.force)
        return 0

    if args.command == "recording-script":
        from phonomenal.recording_script import export_script
        print(json.dumps(export_script(args.output), indent=2))
        return 0

    if args.command == "build-pack":
        from phonomenal.builder import build_pack
        build_pack(args.source, args.output, args.voice, args.language, args.whisper_model,
                   args.mfa_command, args.acoustic_model, args.work, args.force, args.device, args.tf2)
        return 0
    if args.command == "extend-pack":
        from phonomenal.vcpack import extend_pack
        sections = {}
        for item in args.section:
            tag, separator, filename = item.partition("=")
            if not separator or tag in sections:
                parser.error("Each --section must be a unique TAG=FILE")
            sections[tag] = Path(filename).read_bytes()
        extend_pack(args.pack, sections, output=args.output)
        print(f"Updated {args.output or args.pack}: optional data preserved, ASCII specification at EOF")
        return 0
    if args.command == "inspect-pack":
        from phonomenal.vcpack import inspect_pack
        print(json.dumps(inspect_pack(args.pack), indent=2, ensure_ascii=False))
        return 0
    if args.command == "convert-pack":
        from phonomenal.vcpack import convert_legacy
        report = convert_legacy(layout.root, args.voice, args.output)
        print(f"Built {args.output}: {report['words']} words, {report['phones']} phones")
        return 0
    if args.command == "compare-alignments":
        from phonomenal.alignment_quality import compare_boundaries
        report = compare_boundaries(json.loads(args.reference.read_text()), json.loads(args.predicted.read_text()), args.tolerance_ms)
        print(json.dumps(report, indent=2))
        return 0

    if args.command == "fetch-tf2":
        for merc in mercs:
            fetch_merc(merc, layout=layout, limit=args.limit, force=args.force)
        return 0

    if args.command == "scan-source":
        for merc in mercs:
            scan_local_source_merc(merc, layout=layout, limit=args.limit)
        return 0

    if args.command == "combine-source":
        for merc in mercs:
            try:
                records = load_alignment_state(layout, merc)
            except FileNotFoundError:
                try:
                    records = load_catalog(layout, merc)
                except FileNotFoundError:
                    records = scan_local_source_merc(merc, layout=layout, limit=args.limit)
            build_merc_master(merc, records=records, layout=layout, force=args.force)
            if any(record.words or record.phonemes or record.master_audio_path for record in records):
                save_alignment_state(layout, merc, records)
        return 0

    if args.command == "align":
        for merc in mercs:
            align_merc(
                merc,
                layout=layout,
                whisper_model=args.whisper_model,
                batch_size=args.batch_size,
                mfa_command=args.mfa_command,
                force=args.force,
            )
        return 0

    if args.command == "export":
        export_manifests(layout, mercs)
        return 0

    if args.command == "phenomenise":
        for merc in mercs:
            scan_local_source_merc(merc, layout=layout, limit=args.limit)
            records = align_merc(
                merc,
                layout=layout,
                whisper_model=args.whisper_model,
                batch_size=args.batch_size,
                mfa_command=args.mfa_command,
                force=args.force,
            )
            build_merc_master(merc, records=records, layout=layout, force=args.force)
            save_alignment_state(layout, merc, records)
        export_manifests(layout, mercs)
        return 0

    if args.command == "splice":
        manifest_path = args.manifest.resolve() if args.manifest is not None else None
        output_path = args.output.resolve() if args.output is not None else None
        if not args.stdout_wav and output_path is None:
            parser.error("splice requires either --output or --stdout-wav")
        write_splice_result(
            layout=layout,
            merc=args.merc,
            text=args.text,
            output_path=output_path,
            stdout_wav=args.stdout_wav,
            manifest_path=manifest_path,
            crossfade_ms=args.crossfade_ms,
        )
        return 0

    if args.command == "splice-plan":
        manifest_path = args.manifest.resolve() if args.manifest is not None else None
        service = SplicerService(layout)
        plan = service.plan(args.merc, args.text, manifest_path=manifest_path)
        print(json.dumps(plan.to_dict(), indent=2))
        return 0

    if args.command == "serve-splicer":
        run_splicer_server(layout=layout, host=args.host, port=args.port)
        return 0

    if args.command == "pack-bank":
        if args.output is not None and len(mercs) != 1:
            parser.error("--output can only be used when packing a single merc")
        for merc in mercs:
            output_path = args.output.resolve() if args.output is not None else None
            pack_voice_bank(
                layout=layout,
                merc=merc,
                output_path=output_path,
                bundle_master=args.bundle_master,
            )
        return 0

    if args.command == "build-tf2":
        for merc in mercs:
            fetch_merc(merc, layout=layout, limit=args.limit, force=args.force)
            align_merc(
                merc,
                layout=layout,
                whisper_model=args.whisper_model,
                batch_size=args.batch_size,
                mfa_command=args.mfa_command,
                force=args.force,
            )
        export_manifests(layout, mercs)
        return 0

    parser.error(f"Unhandled command: {args.command}")
    return 2
