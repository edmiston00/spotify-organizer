"""MusicBrainz artist genre/tag lookup with rate limiting and on-disk cache.

Spotify GET /artists often 403s in Development Mode. MusicBrainz is free for
non-commercial use with a descriptive User-Agent and ~1 request/second.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from spotify_organizer.config import (
    MUSICBRAINZ_BASE,
    MUSICBRAINZ_CACHE,
    MUSICBRAINZ_MIN_INTERVAL,
    MUSICBRAINZ_USER_AGENT,
)

CACHE_SCHEMA = 1
SEARCH_LIMIT = 8
TOP_TAGS = 12
TRIBUTE_RE = re.compile(
    r"tribute|karaoke|cover band|bootleg|vs\.|mash[- ]up",
    re.IGNORECASE,
)

# Prefer the well-known recording artist when MusicBrainz has several hits.
DISAMBIGUATION_HINTS: dict[str, dict[str, Any]] = {
    "sublime": {"tags": {"ska", "punk", "ska punk"}, "type": "Group", "country": "US"},
    "yes": {"tags": {"progressive rock", "rock"}, "type": "Group", "country": "GB"},
    "tool": {"tags": {"progressive metal", "metal", "rock"}, "type": "Group", "country": "US"},
    "live": {"tags": {"alternative rock", "rock"}, "type": "Group"},
    "prince": {"tags": {"funk", "pop", "r&b", "minneapolis"}, "type": "Person"},
    "common": {"tags": {"hip hop", "rap"}, "type": "Person"},
    "future": {"tags": {"hip hop", "trap", "rap"}, "type": "Person"},
    "drake": {"tags": {"hip hop", "rap"}, "type": "Person", "country": "CA"},
    "usher": {"tags": {"r&b", "soul"}, "type": "Person"},
    "seal": {"tags": {"soul", "pop"}, "type": "Person"},
    "beck": {"tags": {"alternative", "rock"}, "type": "Person"},
    "sting": {"tags": {"rock", "pop"}, "type": "Person"},
    "heart": {"tags": {"rock", "hard rock"}, "type": "Group"},
    "cream": {"tags": {"rock", "blues"}, "type": "Group"},
    "poison": {"tags": {"glam", "rock", "hair"}, "type": "Group"},
    "hole": {"tags": {"grunge", "rock"}, "type": "Group"},
    "garbage": {"tags": {"alternative", "rock"}, "type": "Group"},
    "spoon": {"tags": {"indie", "rock"}, "type": "Group"},
    "cake": {"tags": {"alternative", "rock"}, "type": "Group"},
    "rush": {"tags": {"progressive rock", "rock"}, "type": "Group", "country": "CA"},
    "genesis": {"tags": {"progressive rock", "rock"}, "type": "Group"},
    "boston": {"tags": {"rock", "classic rock"}, "type": "Group"},
    "chicago": {"tags": {"rock", "classic rock"}, "type": "Group"},
    "kansas": {"tags": {"rock", "progressive"}, "type": "Group"},
    "queen": {"tags": {"rock", "classic rock"}, "type": "Group", "country": "GB"},
    "pink": {"tags": {"pop", "r&b"}, "type": "Person"},
    "maxwell": {"tags": {"soul", "r&b"}, "type": "Person"},
    "sade": {"tags": {"soul", "r&b"}, "type": "Person"},
    "journey": {"tags": {"rock", "arena"}, "type": "Group"},
    "america": {"tags": {"rock", "folk"}, "type": "Group"},
    "bread": {"tags": {"rock", "soft rock"}, "type": "Group"},
    "free": {"tags": {"rock", "blues"}, "type": "Group"},
    "traffic": {"tags": {"rock", "progressive"}, "type": "Group"},
    "war": {"tags": {"funk", "soul"}, "type": "Group"},
    "fun": {"tags": {"indie", "pop", "rock"}, "type": "Group"},
    "train": {"tags": {"rock", "pop"}, "type": "Group"},
}


@dataclass
class ArtistLookup:
    query: str
    spotify_id: str = ""
    found: bool = False
    mbid: str = ""
    mb_name: str = ""
    disambiguation: str = ""
    type: str = ""
    country: str = ""
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    search_score: int = 0
    source: str = ""
    fallback_genres: list[str] = field(default_factory=list)
    error: str = ""
    looked_up_at: str = ""

    @property
    def style_labels(self) -> list[str]:
        labels: list[str] = []
        for item in [*self.genres, *self.tags, *self.fallback_genres]:
            cleaned = (item or "").strip()
            if cleaned and cleaned not in labels:
                labels.append(cleaned)
        return labels

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def lookup_from_dict(data: dict[str, Any]) -> ArtistLookup:
    allowed = {item.name for item in fields(ArtistLookup)}
    kwargs = {key: value for key, value in data.items() if key in allowed}
    kwargs.setdefault("query", "")
    kwargs.setdefault("genres", [])
    kwargs.setdefault("tags", [])
    kwargs.setdefault("fallback_genres", [])
    return ArtistLookup(**kwargs)


class MusicBrainzClient:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        min_interval: float = MUSICBRAINZ_MIN_INTERVAL,
        user_agent: str = MUSICBRAINZ_USER_AGENT,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})
        self._sleep = sleep
        self._min_interval = min_interval
        self._now = now
        self._next_ok = 0.0

    def search_artists(self, name: str, *, limit: int = SEARCH_LIMIT) -> list[dict[str, Any]]:
        params = {"query": f'artist:"{name}"', "fmt": "json", "limit": limit}
        data = self._get("/artist/", params)
        return list(data.get("artists") or [])

    def artist_detail(self, mbid: str) -> dict[str, Any]:
        return self._get(f"/artist/{mbid}", {"inc": "genres+tags", "fmt": "json"})

    def lookup_name(self, name: str) -> ArtistLookup:
        result = ArtistLookup(query=name, looked_up_at=_now_iso())
        hits = self._search_with_fallbacks(name)
        if not hits:
            return result
        chosen = pick_artist_hit(name, hits)
        if chosen is None:
            return result
        result.search_score = int(chosen.get("score") or 0)
        result.mbid = str(chosen.get("id") or "")
        result.mb_name = str(chosen.get("name") or "")
        result.disambiguation = str(chosen.get("disambiguation") or "")
        result.type = str(chosen.get("type") or "")
        result.country = str(chosen.get("country") or "")
        detail: dict[str, Any] = {}
        if result.mbid:
            try:
                detail = self.artist_detail(result.mbid)
            except MusicBrainzError as exc:
                genres, tags = extract_genres_and_tags({}, chosen)
                if tags:
                    result.genres = genres
                    result.tags = tags
                    result.found = True
                    result.source = "musicbrainz"
                    return result
                result.error = f"{type(exc).__name__}: {exc}"
                return result
        genres, tags = extract_genres_and_tags(detail, chosen)
        result.genres = genres
        result.tags = tags
        result.found = True
        result.source = "musicbrainz" if (genres or tags) else "musicbrainz-empty"
        if detail:
            result.mb_name = str(detail.get("name") or result.mb_name)
            result.disambiguation = str(detail.get("disambiguation") or result.disambiguation)
            result.type = str(detail.get("type") or result.type)
            if isinstance(detail.get("country"), str) and detail.get("country"):
                result.country = str(detail["country"])
        return result

    def _search_with_fallbacks(self, name: str) -> list[dict[str, Any]]:
        tried: list[str] = []
        for candidate in _search_name_variants(name):
            if candidate in tried:
                continue
            tried.append(candidate)
            try:
                hits = self.search_artists(candidate)
            except MusicBrainzError:
                hits = []
            if hits:
                return hits
        return []

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = path if path.startswith("http") else f"{MUSICBRAINZ_BASE}{path}"
        delay = 2.0
        last_error: Exception | None = None
        for _attempt in range(8):
            self._throttle()
            try:
                response = self.session.get(url, params=params, timeout=45)
            except requests.RequestException as exc:
                last_error = exc
                self._sleep(delay)
                delay = min(delay * 2, 30)
                continue
            if response.status_code in {429, 503}:
                retry_after = response.headers.get("Retry-After")
                wait = delay
                if retry_after:
                    try:
                        wait = max(delay, float(retry_after))
                    except ValueError:
                        wait = delay
                self._sleep(wait)
                delay = min(delay * 2, 30)
                continue
            if response.status_code >= 400:
                raise MusicBrainzError(
                    f"MusicBrainz HTTP {response.status_code} for {path}",
                    status=response.status_code,
                )
            try:
                return response.json()
            except ValueError as exc:
                last_error = exc
                self._sleep(delay)
                delay = min(delay * 2, 30)
        raise MusicBrainzError(f"MusicBrainz request failed for {path}: {last_error}")

    def _throttle(self) -> None:
        now = self._now()
        wait = self._next_ok - now
        if wait > 0:
            self._sleep(wait)
            now = self._now()
        self._next_ok = now + self._min_interval


class MusicBrainzError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def pick_artist_hit(query: str, hits: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not hits:
        return None
    scored = [(score_artist_candidate(query, hit), hit) for hit in hits]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best = scored[0]
    if best_score < 20:
        return None
    return best


def score_artist_candidate(query: str, hit: dict[str, Any]) -> float:
    q = _norm_name(query)
    name = _norm_name(str(hit.get("name") or ""))
    score = float(hit.get("score") or 0)
    dis = str(hit.get("disambiguation") or "")
    tags = _hit_tag_names(hit)

    if name == q:
        score += 45
    elif q and (q in name or name in q):
        score += 12

    if TRIBUTE_RE.search(dis) or TRIBUTE_RE.search(str(hit.get("name") or "")):
        score -= 90
    if any(TRIBUTE_RE.search(tag) for tag in tags):
        score -= 40

    artist_type = str(hit.get("type") or "")
    if artist_type == "Group":
        score += 6
    elif artist_type == "Person":
        score += 3

    score += min(len(tags), 8)

    hint = DISAMBIGUATION_HINTS.get(q)
    if hint:
        wanted = {_norm_name(t) for t in hint.get("tags") or set()}
        haystack = {_norm_name(dis), *(_norm_name(t) for t in tags)}
        if wanted and any(any(w in h for h in haystack if h) for w in wanted):
            score += 35
        if hint.get("type") and artist_type == hint["type"]:
            score += 12
        if hint.get("country") and str(hit.get("country") or "") == hint["country"]:
            score += 10

    return score


def extract_genres_and_tags(
    detail: dict[str, Any],
    search_hit: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    genres = _ranked_names(detail.get("genres") or [])
    tags = _ranked_names(detail.get("tags") or [], require_count=True)[:TOP_TAGS]
    if not genres and not tags and search_hit:
        tags = _ranked_names(search_hit.get("tags") or [], require_count=True)[:TOP_TAGS]
    return genres, tags


def cache_key(spotify_id: str, name: str) -> str:
    if spotify_id:
        return f"id:{spotify_id}"
    return f"name:{_norm_name(name)}"


class LookupCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or MUSICBRAINZ_CACHE
        self.artists: dict[str, ArtistLookup] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        rows = raw.get("artists") if isinstance(raw, dict) else raw
        if isinstance(rows, dict):
            for key, value in rows.items():
                if isinstance(value, dict):
                    self.artists[key] = lookup_from_dict(value)

    def get(self, spotify_id: str, name: str) -> ArtistLookup | None:
        return self.artists.get(cache_key(spotify_id, name))

    def put(self, lookup: ArtistLookup) -> None:
        self.artists[cache_key(lookup.spotify_id, lookup.query)] = lookup

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": CACHE_SCHEMA,
            "updated_at": _now_iso(),
            "count": len(self.artists),
            "artists": {key: value.to_dict() for key, value in self.artists.items()},
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def is_complete(self, lookup: ArtistLookup | None) -> bool:
        if lookup is None:
            return False
        return not lookup.error


def _ranked_names(rows: list[dict[str, Any]], *, require_count: bool = False) -> list[str]:
    ranked = sorted(rows, key=lambda row: -int(row.get("count") or 0))
    out: list[str] = []
    for row in ranked:
        if require_count and int(row.get("count") or 0) <= 0:
            continue
        name = (row.get("name") or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def _hit_tag_names(hit: dict[str, Any]) -> list[str]:
    return [str(t.get("name") or "") for t in (hit.get("tags") or []) if t.get("name")]


def _search_name_variants(name: str) -> list[str]:
    stripped = (name or "").strip()
    if not stripped:
        return []
    variants = [stripped]
    folded = _ascii_fold(stripped)
    if folded and folded not in variants:
        variants.append(folded)
    no_the = re.sub(r"^the\s+", "", stripped, flags=re.IGNORECASE).strip()
    if no_the and no_the not in variants:
        variants.append(no_the)
    return variants


def _norm_name(value: str) -> str:
    folded = _ascii_fold(value).casefold()
    folded = re.sub(r"[^\w\s]+", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def _ascii_fold(value: str) -> str:
    return unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
