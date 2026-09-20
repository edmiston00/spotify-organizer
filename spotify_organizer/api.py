from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

import requests
from spotipy.oauth2 import SpotifyOAuth

from spotify_organizer.auth import access_token
from spotify_organizer.config import (
    API_BASE,
    ARTIST_BATCH_LIMIT,
    ARTIST_GENRE_CACHE,
    PLAYLIST_ADD_LIMIT,
    PLAYLIST_PAGE,
    SAVED_TRACKS_PAGE,
)
from spotify_organizer.models import ArtistRef, Library, TopArtist, Track


class SpotifyAPIError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class SpotifyClient:
    """Thin Web API client that respects Feb 2026 Dev Mode endpoint changes.

    Extended Quota apps can still use batch GETs and `/playlists/{id}/tracks`.
    Development Mode rejects batch `GET /artists` (typically 403). This client
    tries the batch path once and, on 403/404/405, leaves genres empty rather
    than issuing thousands of `GET /artists/{id}` calls.
    """

    def __init__(
        self,
        oauth: SpotifyOAuth,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.oauth = oauth
        self.session = session or requests.Session()
        self._sleep = sleep
        self._batch_artists_supported: bool | None = None
        self._playlist_items_path = "items"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token(self.oauth)}",
            "Content-Type": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        allow_statuses: tuple[int, ...] = (),
    ) -> requests.Response:
        url = path if path.startswith("http") else f"{API_BASE}{path}"
        delay = 1.0
        last_error: Exception | None = None

        for attempt in range(8):
            try:
                response = self.session.request(
                    method,
                    url,
                    headers=self._headers(),
                    params=params,
                    json=json_body,
                    timeout=30,
                )
            except requests.RequestException as exc:
                last_error = exc
                self._sleep(delay)
                delay = min(delay * 2, 30)
                continue

            if response.status_code in allow_statuses:
                return response

            if response.status_code == 401 and attempt == 0:
                # Force a refresh on the next header build.
                try:
                    self.oauth.get_cached_token()
                except Exception:
                    pass
                continue

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else delay
                except ValueError:
                    wait = delay
                self._sleep(max(wait, 0.25) + 0.05)
                delay = min(delay * 2, 60)
                continue

            if response.status_code >= 500:
                self._sleep(delay)
                delay = min(delay * 2, 30)
                continue

            if not response.ok:
                detail = _response_detail(response)
                raise SpotifyAPIError(
                    f"Spotify API {method} {path} failed ({response.status_code}): {detail}",
                    status=response.status_code,
                )
            return response

        raise SpotifyAPIError(f"Spotify API {method} {path} failed after retries: {last_error}")

    def get_json(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.request("GET", path, **kwargs).json()

    def iter_saved_tracks(self) -> Iterator[Track]:
        """Paginate GET /me/tracks (max 50). Album release dates come with the track."""
        url: str | None = "/me/tracks"
        params: dict[str, Any] | None = {"limit": SAVED_TRACKS_PAGE}

        while url:
            payload = self.get_json(url, params=params)
            params = None
            for row in payload.get("items") or []:
                track = _parse_saved_track(row)
                if track:
                    yield track
            url = payload.get("next")

    def fetch_artist_genres(
        self,
        artist_ids: Iterable[str],
        *,
        cache_path: Path | None = ARTIST_GENRE_CACHE,
    ) -> dict[str, list[str]]:
        """Resolve genres for unique artist IDs.

        Tries GET /artists?ids=… (50/id batch, Extended Quota). When that
        endpoint is blocked (Dev Mode 403/404/405), missing IDs get empty
        genre lists. Analyze then clusters on years, artist names, and save
        dates. Per-artist GET /artists/{id} is intentionally not used.
        """
        unique = [aid for aid in dict.fromkeys(artist_ids) if aid]
        genres = _load_genre_cache(cache_path)
        missing = [aid for aid in unique if aid not in genres]
        if not missing:
            return {aid: genres.get(aid, []) for aid in unique}

        if self._batch_artists_supported is not False:
            fetched, used_batch = self._try_batch_artists(missing)
            genres.update(fetched)
            self._batch_artists_supported = used_batch
            if used_batch:
                _save_genre_cache(cache_path, genres)

        # Missing IDs (Dev Mode or absent from a batch payload) stay empty.
        # Do not persist those placeholders, so a later Extended Quota run can fill them.
        return {aid: list(genres.get(aid, [])) for aid in unique}

    def _try_batch_artists(self, artist_ids: list[str]) -> tuple[dict[str, list[str]], bool]:
        out: dict[str, list[str]] = {}
        unavailable = {403, 404, 405}
        for chunk in _chunks(artist_ids, ARTIST_BATCH_LIMIT):
            response = self.request(
                "GET",
                "/artists",
                params={"ids": ",".join(chunk)},
                allow_statuses=(403, 404, 405),
            )
            if response.status_code in unavailable:
                return out, False
            payload = response.json()
            for artist in payload.get("artists") or []:
                if not artist:
                    continue
                aid = artist.get("id")
                if aid:
                    out[str(aid)] = list(artist.get("genres") or [])
        return out, True

    def get_top_artists(
        self, *, time_range: str = "medium_term", limit: int = 50
    ) -> list[TopArtist]:
        """GET /me/top/artists — optional listening signal (user-top-read)."""
        try:
            payload = self.get_json(
                "/me/top/artists",
                params={"time_range": time_range, "limit": min(limit, 50)},
            )
        except SpotifyAPIError as exc:
            if exc.status in {403, 404}:
                return []
            raise
        artists: list[TopArtist] = []
        for raw in payload.get("items") or []:
            if not raw or not raw.get("id"):
                continue
            artists.append(
                TopArtist(
                    id=str(raw["id"]),
                    name=str(raw.get("name") or ""),
                    genres=list(raw.get("genres") or []),
                )
            )
        return artists

    def current_user_id(self) -> str:
        return str(self.get_json("/me").get("id") or "")

    def iter_own_playlists(self) -> Iterator[dict[str, Any]]:
        url: str | None = "/me/playlists"
        params: dict[str, Any] | None = {"limit": PLAYLIST_PAGE}
        while url:
            payload = self.get_json(url, params=params)
            params = None
            for playlist in payload.get("items") or []:
                if playlist:
                    yield playlist
            url = payload.get("next")

    def find_playlist_by_name(self, name: str) -> dict[str, Any] | None:
        needle = name.casefold()
        for playlist in self.iter_own_playlists():
            if str(playlist.get("name") or "").casefold() == needle:
                return playlist
        return None

    def create_playlist(self, name: str, description: str, *, public: bool = False) -> dict[str, Any]:
        response = self.request(
            "POST",
            "/me/playlists",
            json_body={"name": name, "description": description, "public": public},
        )
        return response.json()

    def playlist_track_uris(self, playlist_id: str) -> set[str]:
        uris: set[str] = set()
        paths = [f"/playlists/{playlist_id}/items", f"/playlists/{playlist_id}/tracks"]
        payload: dict[str, Any] | None = None
        for path in paths:
            response = self.request("GET", path, params={"limit": 50}, allow_statuses=(404,))
            if response.status_code == 404:
                continue
            payload = response.json()
            self._playlist_items_path = path.rsplit("/", 1)[-1]
            break
        if payload is None:
            return uris

        while payload:
            for row in payload.get("items") or []:
                obj = row.get("item") or row.get("track") or row.get("episode")
                if obj and obj.get("uri"):
                    uris.add(str(obj["uri"]))
            nxt = payload.get("next")
            if not nxt:
                break
            payload = self.get_json(nxt)
        return uris

    def add_track_uris(self, playlist_id: str, uris: list[str]) -> int:
        """Add URIs in batches of at most 100. Idempotent caller should pre-filter."""
        added = 0
        for chunk in _chunks(uris, PLAYLIST_ADD_LIMIT):
            self._add_chunk(playlist_id, chunk)
            added += len(chunk)
        return added

    def _add_chunk(self, playlist_id: str, uris: list[str]) -> None:
        body = {"uris": uris}
        primary = f"/playlists/{playlist_id}/{self._playlist_items_path}"
        fallback = (
            f"/playlists/{playlist_id}/tracks"
            if self._playlist_items_path == "items"
            else f"/playlists/{playlist_id}/items"
        )
        response = self.request("POST", primary, json_body=body, allow_statuses=(404,))
        if response.status_code == 404:
            self.request("POST", fallback, json_body=body)
            self._playlist_items_path = fallback.rsplit("/", 1)[-1]


def scan_liked_songs(
    client: SpotifyClient,
    *,
    include_top_artists: bool = True,
    progress: Callable[[str], None] | None = None,
) -> Library:
    from datetime import datetime, timezone

    log = progress or (lambda _msg: None)
    tracks: list[Track] = []
    log("Scanning Liked Songs (paginated GET /me/tracks)…")
    for track in client.iter_saved_tracks():
        tracks.append(track)
        if len(tracks) % 200 == 0:
            log(f"  …{len(tracks)} tracks so far")

    artist_ids = [aid for track in tracks for aid in track.artist_ids()]
    unique_artists = len(set(artist_ids))
    log(f"Resolving genres for {unique_artists} unique artists (batch GET /artists)…")
    genres = client.fetch_artist_genres(artist_ids)
    if unique_artists and client._batch_artists_supported is False:
        log(
            "Batch GET /artists is unavailable (Dev Mode 403/404/405). "
            "Skipping per-artist fetches; clustering by year, artist name, and save date."
        )
    for track in tracks:
        seen: list[str] = []
        for aid in track.artist_ids():
            for genre in genres.get(aid, []):
                if genre and genre not in seen:
                    seen.append(genre)
        track.genres = seen

    top: list[TopArtist] = []
    if include_top_artists:
        log("Fetching optional top artists (GET /me/top/artists)…")
        top = client.get_top_artists()
        # Top-artist payloads already include genres when the API returns them.
        extra_ids = [a.id for a in top if a.id and not a.genres]
        if extra_ids:
            extra = client.fetch_artist_genres(extra_ids)
            for artist in top:
                if not artist.genres:
                    artist.genres = extra.get(artist.id, [])

    log(f"Scan complete: {len(tracks)} liked tracks.")
    return Library(
        tracks=tracks,
        top_artists=top,
        scanned_at=datetime.now(timezone.utc).isoformat(),
    )


def _parse_saved_track(row: dict[str, Any]) -> Track | None:
    raw = row.get("track")
    if not raw or raw.get("type") not in {None, "track"}:
        return None
    if raw.get("is_local") or not raw.get("id") or not raw.get("uri"):
        return None

    album = raw.get("album") or {}
    release_date = str(album.get("release_date") or "")
    year = _year_from_release(release_date)
    artists = [
        ArtistRef(id=str(a.get("id") or ""), name=str(a.get("name") or ""))
        for a in raw.get("artists") or []
        if a
    ]
    return Track(
        id=str(raw["id"]),
        uri=str(raw["uri"]),
        name=str(raw.get("name") or ""),
        artists=artists,
        album_name=str(album.get("name") or ""),
        release_date=release_date,
        year=year,
        added_at=str(row.get("added_at") or ""),
    )


def _year_from_release(release_date: str) -> int | None:
    if not release_date:
        return None
    prefix = release_date[:4]
    if prefix.isdigit():
        year = int(prefix)
        if 1000 <= year <= 2100:
            return year
    return None


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _response_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            return str(error.get("message") or payload)
        return str(payload)
    except ValueError:
        return response.text[:300]


def _load_genre_cache(path: Path | None) -> dict[str, list[str]]:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): list(v or []) for k, v in data.items()}


def _save_genre_cache(path: Path | None, genres: dict[str, list[str]]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(genres, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        return
