from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from spotify_organizer import __version__
from spotify_organizer.api import SpotifyClient, scan_liked_songs
from spotify_organizer.apply import APPLY_REFUSAL, ApplyRefused, apply_suggestions
from spotify_organizer.auth import build_oauth
from spotify_organizer.config import MUSICBRAINZ_CACHE, ConfigError, load_settings
from spotify_organizer.enrich import (
    apply_labels_to_library,
    apply_local_fallbacks,
    enrich_artists,
    enrichment_summary,
    load_unique_artists_json,
    propagate_coartist_genres,
    unique_artists_from_library,
)
from spotify_organizer.musicbrainz import LookupCache, MusicBrainzClient
from spotify_organizer.reports import load_library, load_suggestions, write_reports
from spotify_organizer.style_map import MAX_STYLE_SUGGESTIONS
from spotify_organizer.suggest import discover_style_suggestions, discover_suggestions


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
        if args.command == "enrich-genres":
            return _cmd_enrich(args)
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
    commands = {"analyze", "apply", "enrich-genres"}
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
            "Scan Spotify Liked Songs and suggest review-first playlists. "
            "Playlists are never created unless you run `apply --apply`."
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
        default=None,
        help="Maximum playlists to propose (default 10, or 15 with --style-only).",
    )
    analyze.add_argument(
        "--style-only",
        action="store_true",
        help="Cluster by MusicBrainz/style similarity only (no date/era/saved-year buckets).",
    )
    analyze.add_argument(
        "--allow-overlap",
        action="store_true",
        help="Allow a track in multiple playlists. Implied by --style-only.",
    )
    analyze.add_argument(
        "--enrich-genres",
        action="store_true",
        help="Run MusicBrainz artist enrichment before style clustering (resumable cache).",
    )
    analyze.add_argument(
        "--genre-cache",
        type=Path,
        default=MUSICBRAINZ_CACHE,
        help="MusicBrainz lookup cache path.",
    )
    analyze.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the OAuth URL instead of opening a browser.",
    )

    enrich = sub.add_parser(
        "enrich-genres",
        help="Look up artist genres/tags on MusicBrainz (~1 req/sec, cached).",
    )
    enrich.add_argument(
        "--library-json",
        type=Path,
        default=Path("reports/library.json"),
        help="Library snapshot used to list artists (and to attach labels).",
    )
    enrich.add_argument(
        "--artists-json",
        type=Path,
        help="Optional unique-artists JSON (id, name, track_count).",
    )
    enrich.add_argument(
        "--cache",
        type=Path,
        default=MUSICBRAINZ_CACHE,
        help="On-disk lookup cache so the job can resume.",
    )
    enrich.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports"),
        help="Where to write enrichment_summary.json and optional labeled library.",
    )
    enrich.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N unique artists (for testing).",
    )
    enrich.add_argument(
        "--write-labeled-library",
        action="store_true",
        help="Write library.json with artist style labels copied onto each track.",
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

    style_only = bool(args.style_only or args.allow_overlap)
    cache = None
    if style_only:
        cache = LookupCache(args.genre_cache)
        if args.enrich_genres:
            artists = unique_artists_from_library(library)
            print(
                f"Enriching {len(artists)} unique artists via MusicBrainz "
                f"(~1 req/sec, cache {args.genre_cache})"
            )
            cache = enrich_artists(artists, cache=cache, progress=print)
            apply_local_fallbacks(cache)
            propagate_coartist_genres(library, cache)
        elif not cache.artists:
            print(
                "warning: no MusicBrainz cache yet. Run `spotify-organizer enrich-genres` "
                "or pass --enrich-genres. Falling back to name heuristics and any existing tags.",
                file=sys.stderr,
            )
        else:
            apply_local_fallbacks(cache)
            propagate_coartist_genres(library, cache)
        apply_labels_to_library(library, cache)

    if style_only:
        max_suggestions = args.max_suggestions if args.max_suggestions is not None else MAX_STYLE_SUGGESTIONS
        suggestions = discover_style_suggestions(
            library,
            cache=cache,
            min_tracks=args.min_tracks,
            max_suggestions=max_suggestions,
        )
    else:
        max_suggestions = args.max_suggestions if args.max_suggestions is not None else 10
        suggestions = discover_suggestions(
            library,
            min_tracks=args.min_tracks,
            max_suggestions=max_suggestions,
        )
    paths = write_reports(library, suggestions, args.output_dir, dry_run=True)

    print()
    print(f"Library: {library.track_count} liked tracks")
    print(f"Suggestions: {len(suggestions)} (dry-run — nothing was created)")
    if style_only:
        print("Mode: style-only overlapping playlists (MusicBrainz / fallback).")
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


def _cmd_enrich(args: argparse.Namespace) -> int:
    library_path: Path = args.library_json
    if not library_path.exists():
        print(
            f"error: {library_path} not found. Pass --library-json from a prior analyze scan.",
            file=sys.stderr,
        )
        return 2
    library = load_library(library_path)
    if args.artists_json:
        artists = load_unique_artists_json(args.artists_json)
        print(f"Loaded {len(artists)} unique artists from {args.artists_json}")
    else:
        artists = unique_artists_from_library(library)
        print(f"Derived {len(artists)} unique artists from {library_path}")

    cache = LookupCache(args.cache)
    print(
        f"MusicBrainz enricher: {len(artists)} artists, "
        f"~1 request/sec, cache={args.cache} ({len(cache.artists)} already cached)"
    )
    cache = enrich_artists(
        artists,
        cache=cache,
        client=MusicBrainzClient(),
        progress=print,
        limit=args.limit,
    )
    inherited = propagate_coartist_genres(library, cache)
    extra = apply_local_fallbacks(cache)
    inherited += propagate_coartist_genres(library, cache)
    print(f"Co-artist fallback filled {inherited} artists; local fallbacks {extra}")
    apply_labels_to_library(library, cache)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = enrichment_summary(cache, library)
    summary_path = args.output_dir / "enrichment_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote {summary_path}")
    print(
        "MB tagged {musicbrainz_with_tags}/{artists_cached}; "
        "fallback {fallback_or_coartist}; unlabeled {still_unlabeled}".format(**summary)
    )
    if args.write_labeled_library:
        labeled = args.output_dir / "library.json"
        from spotify_organizer.models import library_to_dict

        labeled.write_text(json.dumps(library_to_dict(library), indent=2), encoding="utf-8")
        print(f"Wrote labeled library {labeled}")
    print("Done. Next: spotify-organizer analyze --library-json ... --style-only --allow-overlap")
    print("Nothing was created on Spotify.")
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
