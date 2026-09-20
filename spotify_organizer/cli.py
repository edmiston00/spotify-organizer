from __future__ import annotations

import argparse
import sys
from pathlib import Path

from spotify_organizer import __version__
from spotify_organizer.api import SpotifyClient, scan_liked_songs
from spotify_organizer.apply import APPLY_REFUSAL, ApplyRefused, apply_suggestions
from spotify_organizer.auth import build_oauth
from spotify_organizer.config import ConfigError, load_settings
from spotify_organizer.reports import load_library, load_suggestions, write_reports
from spotify_organizer.suggest import discover_suggestions


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    argv = _default_analyze(argv)
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "analyze":
            return _cmd_analyze(args)
        if args.command == "apply":
            return _cmd_apply(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ApplyRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    return 1


def _default_analyze(argv: list[str]) -> list[str]:
    commands = {"analyze", "apply"}
    if not argv:
        return ["analyze"]
    if argv[0] in commands or argv[0] in {"-h", "--help", "--version"}:
        return argv
    if argv[0].startswith("-"):
        return ["analyze", *argv]
    return argv


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spotify-organizer",
        description=(
            "Scan Spotify Liked Songs and suggest 5–10 data-driven playlists. "
            "Review reports first. Playlists are never created unless you run "
            "`apply --apply`."
        ),
    )
    parser.add_argument("--version", action="version", version=f"spotify-organizer {__version__}")
    sub = parser.add_subparsers(dest="command")

    analyze = sub.add_parser(
        "analyze",
        help="Scan Liked Songs and write dry-run suggestions (default command).",
    )
    analyze.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports"),
        help="Directory for suggestions.json, suggestions.csv, and library.json.",
    )
    analyze.add_argument(
        "--library-json",
        type=Path,
        help="Reuse a previously saved library snapshot instead of calling Spotify.",
    )
    analyze.add_argument(
        "--no-top-artists",
        action="store_true",
        help="Skip GET /me/top/artists even if the user-top-read scope is granted.",
    )
    analyze.add_argument(
        "--min-tracks",
        type=int,
        default=None,
        help="Minimum cluster size (default: adaptive from library size).",
    )
    analyze.add_argument(
        "--max-suggestions",
        type=int,
        default=10,
        help="Maximum playlists to propose (capped at 10).",
    )
    analyze.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the OAuth URL instead of opening a browser.",
    )

    apply = sub.add_parser(
        "apply",
        help="Create playlists from a reviewed suggestions.json. Requires --apply.",
    )
    apply.add_argument(
        "--apply",
        action="store_true",
        help="Required confirmation. Without this flag, apply refuses to write.",
    )
    apply.add_argument(
        "--suggestions",
        type=Path,
        default=Path("reports/suggestions.json"),
        help="Path to the reviewed suggestions.json from analyze.",
    )
    apply.add_argument(
        "--only",
        action="append",
        default=[],
        help="Limit to suggestion id or exact name. Repeatable.",
    )
    apply.add_argument(
        "--public",
        action="store_true",
        help="Create playlists as public (default: private).",
    )
    apply.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the OAuth URL instead of opening a browser.",
    )
    return parser


def _cmd_analyze(args: argparse.Namespace) -> int:
    if args.library_json:
        library = load_library(args.library_json)
        print(f"Loaded {library.track_count} tracks from {args.library_json}")
    else:
        client = _client(open_browser=not args.no_browser)
        library = scan_liked_songs(
            client,
            include_top_artists=not args.no_top_artists,
            progress=print,
        )

    suggestions = discover_suggestions(
        library,
        min_tracks=args.min_tracks,
        max_suggestions=args.max_suggestions,
    )
    paths = write_reports(library, suggestions, args.output_dir, dry_run=True)

    print()
    print(f"Library: {library.track_count} liked tracks")
    print(f"Suggestions: {len(suggestions)} (dry-run — nothing was created)")
    print()
    if not suggestions:
        print("No clusters were large enough to suggest playlists.")
        print(f"Wrote empty report to {paths['json']}")
        return 0

    for index, suggestion in enumerate(suggestions, start=1):
        print(f"{index}. {suggestion.name}  (~{suggestion.approx_track_count} tracks)")
        print(f"   {suggestion.description}")
        print(f"   samples: {'; '.join(suggestion.sample_tracks[:3])}")
        print(f"   why: {suggestion.rationale}")
        print()

    print(f"JSON: {paths['json']}")
    print(f"CSV:  {paths['csv']}")
    print(f"Library snapshot: {paths['library']}")
    print()
    print("Review the report. Playlists are not created by analyze.")
    print("When you are ready:  spotify-organizer apply --apply")
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    if not args.suggestions.exists():
        print(
            f"error: {args.suggestions} not found. Run `spotify-organizer analyze` first.",
            file=sys.stderr,
        )
        return 2

    suggestions = load_suggestions(args.suggestions)
    if not suggestions:
        print("error: suggestions file contains no playlists.", file=sys.stderr)
        return 2

    print(f"Loaded {len(suggestions)} suggestions from {args.suggestions}")
    for suggestion in suggestions:
        print(f"  - {suggestion.name} (~{suggestion.approx_track_count} tracks)")

    if not args.apply:
        print()
        print(APPLY_REFUSAL)
        return 2

    client = _client(open_browser=not args.no_browser)
    report = apply_suggestions(
        client,
        suggestions,
        do_apply=True,
        only_ids=args.only or None,
        public=args.public,
    )
    print()
    print("Apply complete (idempotent by playlist name, batches ≤ 100 URIs).")
    for action in report.actions:
        state = "updated" if action.existed else "created"
        print(
            f"  {action.name}: {state}, added {action.added} "
            f"(already present {action.already_present})"
        )
    return 0


def _client(*, open_browser: bool) -> SpotifyClient:
    settings = load_settings()
    oauth = build_oauth(settings, open_browser=open_browser)
    return SpotifyClient(oauth)


if __name__ == "__main__":
    raise SystemExit(main())
