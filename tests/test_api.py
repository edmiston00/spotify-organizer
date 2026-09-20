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


def test_artist_genre_batch_falls_back_to_single_fetch(tmp_path):
    session = ScriptedSession(
        [
            (404, {"error": {"message": "Not Found"}}, None),
            (200, {"id": "a1", "genres": ["indie soul"]}, None),
            (200, {"id": "a2", "genres": ["grime"]}, None),
        ]
    )
    client = SpotifyClient(FakeOAuth(), session=session, sleep=lambda _s: None)
    genres = client.fetch_artist_genres(["a1", "a2"], cache_path=tmp_path / "g.json", workers=1)
    assert genres == {"a1": ["indie soul"], "a2": ["grime"]}
    assert any(url.endswith("/artists") for _, url in session.calls)
    assert any("/artists/a1" in url for _, url in session.calls)


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
