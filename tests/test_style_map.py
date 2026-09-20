from __future__ import annotations

from spotify_organizer.musicbrainz import pick_artist_hit, score_artist_candidate
from spotify_organizer.style_map import labels_to_playlist_ids, map_artist_labels
from spotify_organizer.enrich import infer_genres_from_name


def test_sublime_prefers_us_ska_punk_group():
    hits = [
        {
            "id": "ska",
            "name": "Sublime",
            "score": 100,
            "type": "Group",
            "country": "US",
            "disambiguation": "ska punk",
            "tags": [{"name": "ska", "count": 4}, {"name": "punk rock", "count": 2}],
        },
        {
            "id": "house",
            "name": "Sublime",
            "score": 74,
            "type": "Group",
            "disambiguation": "mid 90s prog house/techno collab on Limbo Records",
            "tags": [],
        },
        {
            "id": "jp",
            "name": "Sublime",
            "score": 74,
            "type": "Person",
            "country": "JP",
            "disambiguation": "Japan–based French female singer",
            "tags": [],
        },
    ]
    chosen = pick_artist_hit("Sublime", hits)
    assert chosen is not None
    assert chosen["id"] == "ska"
    assert score_artist_candidate("Sublime", hits[0]) > score_artist_candidate("Sublime", hits[1])


def test_tribute_band_is_penalized():
    hits = [
        {
            "id": "real",
            "name": "Led Zeppelin",
            "score": 100,
            "type": "Group",
            "country": "GB",
            "disambiguation": "",
            "tags": [{"name": "rock", "count": 10}],
        },
        {
            "id": "fake",
            "name": "Presence Led Zeppelin Tribute",
            "score": 54,
            "type": "Group",
            "disambiguation": "tribute",
            "tags": [],
        },
    ]
    chosen = pick_artist_hit("Led Zeppelin", hits)
    assert chosen is not None
    assert chosen["id"] == "real"


def test_southern_trap_overlaps_hip_hop():
    playlists = labels_to_playlist_ids(["southern hip hop", "trap"])
    assert "southern-trap" in playlists
    assert "hip-hop" in playlists


def test_house_overlaps_electronic():
    playlists = labels_to_playlist_ids(["tech house", "house"])
    assert "house-club" in playlists
    assert "electronic" in playlists


def test_led_zeppelin_pop_tag_does_not_become_pop_playlist():
    playlists = map_artist_labels(
        genres=["hard rock", "rock", "classic rock"],
        tags=["pop", "british", "70s"],
    )
    assert "classic-hard-rock" in playlists
    assert "rock" in playlists
    assert "pop-rnb" not in playlists


def test_meta_and_era_tags_are_ignored():
    playlists = labels_to_playlist_ids(["american", "90s", "seen live", "2008 universal fire victim"])
    assert playlists == set()


def test_hardcore_hip_hop_is_not_metal():
    playlists = labels_to_playlist_ids(["hardcore hip hop", "boom bap"])
    assert playlists == {"hip-hop"}


def test_g_funk_is_not_jam_or_house():
    playlists = labels_to_playlist_ids(["g-funk", "west coast hip hop"])
    assert "hip-hop" in playlists
    assert "jam-funk" not in playlists
    assert "house-club" not in playlists


def test_snoop_folksonomy_junk_does_not_become_house():
    playlists = map_artist_labels(
        genres=[
            "hip hop",
            "gangsta rap",
            "g-funk",
            "west coast hip hop",
            "afro house",
            "dance",
            "drum and bass",
            "house",
            "rock",
        ],
        tags=["hip hop", "dance", "house"],
    )
    assert "hip-hop" in playlists
    assert "house-club" not in playlists
    assert "bass-edm" not in playlists
    assert "rock" not in playlists


def test_disambiguation_text_yields_house():
    from spotify_organizer.style_map import labels_from_free_text

    labels = labels_from_free_text("house, techno DJ/producer from Berlin")
    playlists = labels_to_playlist_ids(labels)
    assert "house-club" in playlists
    assert "electronic" in playlists


def test_ska_punk_overlaps_reggae_and_rock():
    playlists = labels_to_playlist_ids(["ska punk", "ska", "reggae"])
    assert "reggae-ska" in playlists
    assert "rock" in playlists or "metal-punk" in playlists


def test_dom_dolla_name_fallback_is_house():
    labels = infer_genres_from_name("Dom Dolla")
    playlists = labels_to_playlist_ids(labels)
    assert "house-club" in playlists
    assert "electronic" in playlists


def test_unmapped_mb_hit_uses_name_fallback():
    from spotify_organizer.models import Library
    from spotify_organizer.musicbrainz import ArtistLookup, LookupCache
    from spotify_organizer.suggest import discover_style_suggestions
    from tests.factories import make_track

    tracks = [
        make_track(
            f"fish{i:03d}",
            f"Fish {i}",
            artists=[("fish", "FISHER")],
            genres=[],
            year=2018,
            added_at="2020-01-01T00:00:00Z",
        )
        for i in range(20)
    ]
    cache = LookupCache.__new__(LookupCache)
    cache.path = None  # type: ignore[assignment]
    cache.artists = {
        "id:fish": ArtistLookup(
            query="FISHER",
            spotify_id="fish",
            found=True,
            disambiguation="trance/EDM singer/songwriter Kathy Fisher",
            genres=["vocal trance"],
            tags=["vocal trance"],
            source="musicbrainz",
        )
    }
    suggestions = discover_style_suggestions(Library(tracks=tracks), cache=cache, min_tracks=10)
    names = " ".join(s.name for s in suggestions)
    assert "House" in names or "Electronic" in names
    leftover = next((s for s in suggestions if "Needs Review" in s.name), None)
    if leftover:
        assert "spotify:track:fish000" not in leftover.track_uris


def test_lil_prefix_heuristic_is_hip_hop():
    labels = infer_genres_from_name("Lil Wayne")
    assert "hip hop" in labels
    playlists = labels_to_playlist_ids(labels)
    assert "hip-hop" in playlists
