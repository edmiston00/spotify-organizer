from __future__ import annotations

from tests.factories import make_track
from spotify_organizer.models import Library
from spotify_organizer.musicbrainz import ArtistLookup, LookupCache
from spotify_organizer.suggest import discover_style_suggestions, discover_suggestions


def _style_library() -> Library:
    tracks = []
    for i in range(24):
        tracks.append(
            make_track(
                f"trap{i:03d}",
                f"Trap {i}",
                artists=[("bx", "BigXthaPlug")],
                genres=["southern hip hop", "trap"],
                year=2024,
                added_at="2024-01-01T00:00:00Z",
            )
        )
    for i in range(22):
        tracks.append(
            make_track(
                f"house{i:03d}",
                f"House {i}",
                artists=[("dd", "Dom Dolla")],
                genres=["tech house", "house"],
                year=2023,
                added_at="2023-01-01T00:00:00Z",
            )
        )
    for i in range(20):
        tracks.append(
            make_track(
                f"zep{i:03d}",
                f"Zep {i}",
                artists=[("lz", "Led Zeppelin")],
                genres=["hard rock", "classic rock"],
                year=1971,
                added_at="2020-01-01T00:00:00Z",
            )
        )
    for i in range(18):
        tracks.append(
            make_track(
                f"chv{i:03d}",
                f"Chvrches {i}",
                artists=[("ch", "CHVRCHES")],
                genres=["synth-pop", "indie pop"],
                year=2015,
                added_at="2021-01-01T00:00:00Z",
            )
        )
    return Library(tracks=tracks, scanned_at="2026-01-01T00:00:00+00:00")


def test_style_playlists_are_gb_prefixed_and_overlap():
    suggestions = discover_style_suggestions(_style_library(), min_tracks=10, max_suggestions=15)
    assert 4 <= len(suggestions) <= 15
    for item in suggestions:
        assert item.name.startswith("GB ")
        assert 1 <= len(item.sample_tracks) <= 3
        assert item.approx_track_count == len(item.track_uris)
        assert item.kind in {"style", "style-leftover"}
        assert "MusicBrainz" in item.rationale or "no mappable" in item.rationale

    names = {s.name for s in suggestions}
    assert any("Hip-Hop" in n for n in names)
    assert any("Southern Trap" in n for n in names)
    assert any("House" in n or "Electronic" in n for n in names)

    hip = next(s for s in suggestions if "Hip-Hop" in s.name)
    south = next(s for s in suggestions if "Southern Trap" in s.name)
    assert set(south.track_uris) & set(hip.track_uris)
    assert not any(s.kind in {"decade", "saved_year", "recent", "genre_decade"} for s in suggestions)


def test_style_mode_does_not_emit_era_buckets():
    suggestions = discover_style_suggestions(_style_library(), min_tracks=8)
    joined = " ".join(s.name.lower() for s in suggestions)
    assert "time capsule" not in joined
    assert "saved in" not in joined
    assert "1970s" not in joined
    assert "recently saved" not in joined


def test_style_cache_labels_used_when_track_genres_empty(tmp_path):
    tracks = []
    for i in range(20):
        tracks.append(
            make_track(
                f"empty{i:03d}",
                f"Empty {i}",
                artists=[("bx", "BigXthaPlug")],
                genres=[],
                year=2024,
                added_at="2024-01-01T00:00:00Z",
            )
        )
    library = Library(tracks=tracks)
    cache = LookupCache(tmp_path / "mb.json")
    cache.put(
        ArtistLookup(
            query="BigXthaPlug",
            spotify_id="bx",
            found=True,
            genres=["southern hip hop", "trap"],
            source="musicbrainz",
        )
    )
    suggestions = discover_style_suggestions(library, cache=cache, min_tracks=10)
    names = {s.name for s in suggestions}
    assert any("Southern Trap" in n for n in names)
    assert any("Hip-Hop" in n for n in names)


def test_default_discover_still_uses_non_style_path():
    from tests.factories import diverse_library
    from datetime import datetime, timezone

    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    suggestions = discover_suggestions(diverse_library(now=now), now=now)
    assert 5 <= len(suggestions) <= 10
    assert not all(s.name.startswith("GB ") for s in suggestions)
