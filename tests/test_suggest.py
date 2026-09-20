from __future__ import annotations

from datetime import datetime, timezone

from tests.factories import alt_library, diverse_library

from spotify_organizer.suggest import discover_suggestions


NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


def test_discover_returns_five_to_ten_named_playlists():
    suggestions = discover_suggestions(diverse_library(now=NOW), now=NOW)
    assert 5 <= len(suggestions) <= 10
    for item in suggestions:
        assert item.name
        assert item.description
        assert item.approx_track_count >= 5
        assert item.sample_tracks
        assert item.rationale
        assert item.track_uris
        assert item.track_uris[0].startswith("spotify:track:")


def test_suggestions_are_data_driven_not_a_fixed_taxonomy():
    soul_library = discover_suggestions(diverse_library(now=NOW), now=NOW)
    other = discover_suggestions(alt_library(), now=NOW)

    soul_names = " ".join(s.name.lower() for s in soul_library)
    other_names = " ".join(s.name.lower() for s in other)

    assert "indie soul" in soul_names or "synthpop" in soul_names
    assert "bossa nova" in other_names or "progressive metal" in other_names
    assert "bossa nova" not in soul_names
    assert "indie soul" not in other_names


def test_sample_tracks_and_counts_match_uris():
    suggestions = discover_suggestions(diverse_library(now=NOW), now=NOW)
    for item in suggestions:
        assert item.approx_track_count == len(item.track_uris)
        assert 1 <= len(item.sample_tracks) <= 5


def test_empty_library_yields_nothing():
    from spotify_organizer.models import Library

    assert discover_suggestions(Library(tracks=[])) == []


def test_suggestions_without_genres_use_years_names_and_save_dates():
    library = diverse_library(now=NOW)
    for track in library.tracks:
        track.genres = []
    for artist in library.top_artists:
        artist.genres = []
    suggestions = discover_suggestions(library, now=NOW)
    assert 5 <= len(suggestions) <= 10
    kinds = {item.kind for item in suggestions}
    assert "genre" not in kinds
    assert "genre_decade" not in kinds
    assert kinds & {"decade", "artist", "recent", "saved_year", "top_artists"}
    for item in suggestions:
        assert item.approx_track_count >= 5
        assert item.track_uris
