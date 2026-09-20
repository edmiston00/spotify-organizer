from __future__ import annotations

import json

import requests

from spotify_organizer.api import SpotifyClient, _parse_saved_track, _year_from_release


class FakeOAuth:
    def get_access_token(self, as_dict=True, check_cache=True):
        return {"access_token": "test-token"}

    def get_cached_token(self):
        return {"access_token": "test-token"}


class ScriptedSession(requests.Session):
    def __init__(self, scripts: list[tuple[int, dict | None, dict | None]]):
        super().__init__()
        self.scripts = scripts
        self.calls: list[tuple[str, str]] = []

    def request(self, method, url, **kwargs):  # type: ignore[override]
        self.calls.append((method, url))
        status, payload, headers = self.scripts.pop(0)
        response = requests.Response()
        response.status_code = status
        response.headers.update(headers or {})
        response._content = json.dumps(payload or {}).encode("utf-8")
        response.url = url
        return response


def test_year_from_release():
    assert _year_from_release("1998-04-01") == 1998
    assert _year_from_release("2020") == 2020
    assert _year_from_release("") is None


def test_parse_skips_local_and_missing_tracks():
    assert _parse_saved_track({"track": None}) is None
    assert _parse_saved_track({"track": {"id": "x", "uri": "u", "is_local": True}}) is None
    parsed = _parse_saved_track(
        {
            "added_at": "2024-01-01T00:00:00Z",
            "track": {
                "id": "abc",
                "uri": "spotify:track:abc",
                "name": "Hello",
                "type": "track",
                "artists": [{"id": "ar", "name": "Ada"}],
                "album": {"name": "LP", "release_date": "2011-02-03"},
            },
        }
    )
    assert parsed is not None
    assert parsed.year == 2011
    assert parsed.artists[0].name == "Ada"


def test_artist_genre_batch_success(tmp_path):
    session = ScriptedSession(
        [
            (
                200,
                {
                    "artists": [
                        {"id": "a1", "genres": ["indie soul"]},
                        {"id": "a2", "genres": ["grime"]},
                    ]
                },
                None,
            ),
        ]
    )
    client = SpotifyClient(FakeOAuth(), session=session, sleep=lambda _s: None)
    genres = client.fetch_artist_genres(["a1", "a2"], cache_path=tmp_path / "g.json")
    assert genres == {"a1": ["indie soul"], "a2": ["grime"]}
    assert len(session.calls) == 1
    assert session.calls[0][1].endswith("/artists")


def test_artist_genre_batch_403_skips_individual_fetches(tmp_path):
    session = ScriptedSession(
        [
            (403, {"error": {"status": 403, "message": "Forbidden"}}, None),
        ]
    )
    client = SpotifyClient(FakeOAuth(), session=session, sleep=lambda _s: None)
    ids = [f"a{i}" for i in range(8)]
    genres = client.fetch_artist_genres(ids, cache_path=tmp_path / "g.json")
    assert genres == {aid: [] for aid in ids}
    assert client._batch_artists_supported is False
    assert len(session.calls) == 1
    assert session.calls[0][1].endswith("/artists")
    assert session.scripts == []
    # Empty placeholders are not cached, so a later quota upgrade can retry.
    cache_file = tmp_path / "g.json"
    assert not cache_file.exists() or json.loads(cache_file.read_text()) == {}


def test_artist_genre_batch_404_and_405_skip_individual_fetches(tmp_path):
    for status in (404, 405):
        session = ScriptedSession([(status, {"error": {"message": "gone"}}, None)])
        client = SpotifyClient(FakeOAuth(), session=session, sleep=lambda _s: None)
        genres = client.fetch_artist_genres(["x", "y"], cache_path=tmp_path / f"g{status}.json")
        assert genres == {"x": [], "y": []}
        assert len(session.calls) == 1
        assert not any("/artists/x" in url or "/artists/y" in url for _, url in session.calls)


def test_artist_genre_second_call_does_not_retry_failed_batch():
    session = ScriptedSession(
        [(403, {"error": {"message": "Forbidden"}}, None)]
    )
    client = SpotifyClient(FakeOAuth(), session=session, sleep=lambda _s: None)
    assert client.fetch_artist_genres(["a1"], cache_path=None) == {"a1": []}
    assert client.fetch_artist_genres(["a2", "a3"], cache_path=None) == {"a2": [], "a3": []}
    assert len(session.calls) == 1


def test_rate_limit_honors_retry_after():
    slept: list[float] = []
    session = ScriptedSession(
        [
            (429, {"error": {"message": "slow down"}}, {"Retry-After": "2"}),
            (200, {"id": "me"}, None),
        ]
    )
    client = SpotifyClient(FakeOAuth(), session=session, sleep=slept.append)
    payload = client.get_json("/me")
    assert payload["id"] == "me"
    assert slept and slept[0] >= 2
