from __future__ import annotations

import pytest

from spotify_organizer.apply import (
    APPLY_REFUSAL,
    ApplyRefused,
    apply_suggestions,
    chunk_uris,
)
from spotify_organizer.config import PLAYLIST_ADD_LIMIT
from spotify_organizer.models import Suggestion


def _suggestion(name: str = "Indie Soul Favorites", n: int = 3) -> Suggestion:
    uris = [f"spotify:track:{i:03d}" for i in range(n)]
    return Suggestion(
        id="genre-indie-soul",
        name=name,
        description="n liked tracks tagged Indie Soul.",
        approx_track_count=n,
        sample_tracks=["x — y"],
        rationale="test",
        track_uris=uris,
        kind="genre",
    )


class FakeClient:
    def __init__(self) -> None:
        self.playlists: dict[str, dict] = {}
        self.add_calls: list[list[str]] = []

    def find_playlist_by_name(self, name: str):
        for playlist in self.playlists.values():
            if playlist["name"] == name:
                return playlist
        return None

    def create_playlist(self, name: str, description: str, *, public: bool = False):
        pid = f"pl{len(self.playlists) + 1}"
        self.playlists[pid] = {
            "id": pid,
            "name": name,
            "description": description,
            "public": public,
            "uris": [],
        }
        return self.playlists[pid]

    def playlist_track_uris(self, playlist_id: str) -> set[str]:
        return set(self.playlists[playlist_id]["uris"])

    def add_track_uris(self, playlist_id: str, uris: list[str]) -> int:
        for chunk in chunk_uris(uris, PLAYLIST_ADD_LIMIT):
            assert len(chunk) <= 100
            self.add_calls.append(chunk)
            self.playlists[playlist_id]["uris"].extend(chunk)
        return len(uris)


def test_chunk_uris_caps_at_100():
    uris = [f"spotify:track:{i}" for i in range(250)]
    chunks = chunk_uris(uris)
    assert [len(c) for c in chunks] == [100, 100, 50]
    assert chunks[0][0] == "spotify:track:0"


def test_bare_apply_refuses_writes():
    client = FakeClient()
    with pytest.raises(ApplyRefused, match="--apply"):
        apply_suggestions(client, [_suggestion()], do_apply=False)
    assert client.playlists == {}
    assert APPLY_REFUSAL.startswith("Refusing")


def test_apply_creates_then_is_idempotent_by_name():
    client = FakeClient()
    suggestion = _suggestion(n=5)
    first = apply_suggestions(client, [suggestion], do_apply=True)
    assert first.actions[0].created is True
    assert first.actions[0].added == 5

    second = apply_suggestions(client, [suggestion], do_apply=True)
    assert second.actions[0].existed is True
    assert second.actions[0].created is False
    assert second.actions[0].added == 0
    assert second.actions[0].already_present == 5
    assert len(client.playlists) == 1


def test_apply_top_up_only_missing_uris():
    client = FakeClient()
    first = _suggestion(n=3)
    apply_suggestions(client, [first], do_apply=True)
    enlarged = _suggestion(n=5)
    report = apply_suggestions(client, [enlarged], do_apply=True)
    assert report.actions[0].added == 2
    playlist = next(iter(client.playlists.values()))
    assert playlist["uris"] == [f"spotify:track:{i:03d}" for i in range(5)]


def test_add_batches_never_exceed_100():
    client = FakeClient()
    apply_suggestions(client, [_suggestion(n=150)], do_apply=True)
    assert [len(c) for c in client.add_calls] == [100, 50]
