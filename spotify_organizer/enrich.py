"""Enrich liked-song artists with MusicBrainz genres plus local fallbacks."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable, Iterable

from spotify_organizer.config import MUSICBRAINZ_CACHE
from spotify_organizer.models import ArtistRef, Library, Track
from spotify_organizer.musicbrainz import (
    ArtistLookup,
    LookupCache,
    MusicBrainzClient,
    MusicBrainzError,
)
from spotify_organizer.style_map import META_LABELS, labels_from_free_text, normalize_label

Progress = Callable[[str], None]


# Name-based inference when MusicBrainz has no genres/tags (e.g. Dom Dolla).
KNOWN_ARTIST_FALLBACKS: dict[str, list[str]] = {
    "dom dolla": ["tech house", "house", "electronic"],
    "fisher": ["tech house", "house", "electronic"],
    "john summit": ["house", "tech house", "dance"],
    "snbrn": ["house", "electronic", "dance"],
    "amtrac": ["house", "indietronica", "electronic"],
    "the last mr bigg": ["southern hip hop", "hip hop", "houston rap"],
    "the last mr. bigg": ["southern hip hop", "hip hop", "houston rap"],
    "bigxthaplug": ["southern hip hop", "trap", "hip hop"],
    "big x tha plug": ["southern hip hop", "trap", "hip hop"],
    "lane 8": ["melodic house", "progressive house", "electronic"],
    "zhu": ["tech house", "electronic", "house"],
    "odesza": ["future bass", "indietronica", "electronic"],
    "rufus du sol": ["alternative dance", "house", "indietronica"],
    "griz": ["live electronic", "funk", "electronic"],
    "big gigantic": ["live electronic", "electronic", "funk"],
    "zeds dead": ["dubstep", "electronic", "bass music"],
    "kill the noise": ["dubstep", "electronic"],
    "tinlicker": ["progressive house", "melodic techno", "electronic"],
    "eli fur": ["melodic house", "electronic"],
    "eli & fur": ["melodic house", "electronic"],
    "lastlings": ["indie dance", "electronic"],
    "louis the child": ["future bass", "electronic"],
    "steve angello": ["house", "progressive house", "electronic"],
    "above beyond": ["trance", "progressive house", "electronic"],
    "above & beyond": ["trance", "progressive house", "electronic"],
    "diplo": ["electronic", "moombahton", "dance"],
    "skrillex": ["dubstep", "electronic", "brostep"],
    "the chainsmokers": ["electropop", "dance pop", "edm"],
    "two feet": ["indie electronic", "alternative r&b"],
    "k flay": ["alternative rock", "indie pop", "hip hop"],
    "k.flay": ["alternative rock", "indie pop", "hip hop"],
    "chvrches": ["synth-pop", "indie pop", "electronic"],
    "sylvan esso": ["synth-pop", "indie pop", "indietronica"],
    "lcd soundsystem": ["alternative dance", "dance-punk", "electronic"],
    "chet faker": ["indie electronic", "alternative r&b"],
    "rac": ["indietronica", "electronic", "indie pop"],
    "cassian": ["house", "melodic house", "electronic"],
    "crooked colours": ["indie dance", "electronic", "house"],
    "310babii": ["hip hop", "trap"],
    "isolate.exe": ["phonk", "trap", "hip hop"],
    "electric guest": ["indie pop", "synth-pop"],
    "dombresky": ["house", "tech house", "electronic"],
    "shiba san": ["house", "tech house"],
    "ben bohmer": ["melodic house", "progressive house", "electronic"],
    "nils hoffmann": ["house", "techno", "electronic"],
    "set mo": ["house", "electronic"],
    "memba": ["bass music", "electronic", "future bass"],
    "choomba": ["house", "electronic"],
    "nox vahn": ["melodic house", "organic house", "electronic"],
    "the funk hunters": ["funk", "electronic", "house"],
    "oliver anthony music": ["americana", "country", "folk"],
    "blu j": ["edm", "electronic"],
    "humans": ["electronic", "indietronica"],
    "mk": ["house", "tech house"],
    "flight facilities": ["nu-disco", "house", "electronic"],
    "go freek": ["tech house", "house"],
}

NAME_HEURISTICS: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"^(lil['’]?|young|yung)\s", re.I), ["hip hop", "trap"]),
    (re.compile(r"\b(tha plug|thug|migos|carti|boyz)\b", re.I), ["hip hop", "trap"]),
    (re.compile(r"\$"), ["hip hop", "r&b"]),
    (re.compile(r"\bdj\s", re.I), ["electronic", "dance"]),
    (re.compile(r"\b(mafia|killa|gangsta)\b", re.I), ["hip hop", "southern hip hop"]),
]


def unique_artists_from_library(library: Library) -> list[ArtistRef]:
    seen: dict[str, ArtistRef] = {}
    counts: Counter[str] = Counter()
    for track in library.tracks:
        for artist in track.artists:
            key = artist.id or artist.name.casefold()
            if not key:
                continue
            counts[key] += 1
            seen.setdefault(key, artist)
    return [seen[key] for key, _count in counts.most_common()]


def load_unique_artists_json(path: Path) -> list[ArtistRef]:
    data = json.loads(path.read_text(encoding="utf-8"))
    artists: list[ArtistRef] = []
    seen: set[str] = set()
    for raw in data:
        artist = ArtistRef(id=str(raw.get("id") or ""), name=str(raw.get("name") or ""))
        key = artist.id or artist.name.casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        artists.append(artist)
    return artists


def enrich_artists(
    artists: Iterable[ArtistRef],
    *,
    cache: LookupCache | None = None,
    client: MusicBrainzClient | None = None,
    progress: Progress | None = print,
    save_every: int = 10,
    limit: int | None = None,
) -> LookupCache:
    cache = cache or LookupCache(MUSICBRAINZ_CACHE)
    client = client or MusicBrainzClient()
    pending = list(artists)
    if limit is not None:
        pending = pending[: max(0, limit)]

    processed = 0
    for index, artist in enumerate(pending, start=1):
        existing = cache.get(artist.id, artist.name)
        if cache.is_complete(existing) and existing is not None:
            _apply_fallbacks(existing)
            if progress:
                labels = existing.style_labels or ["NO TAGS"]
                progress(f"[{index}/{len(pending)}] {artist.name} -> cached {labels[:6]}")
            continue
        lookup = _lookup_one(client, artist, progress=progress, index=index, total=len(pending))
        _apply_fallbacks(lookup)
        cache.put(lookup)
        processed += 1
        if processed % save_every == 0:
            cache.save()
            if progress:
                progress(f"  saved cache ({len(cache.artists)} artists) -> {cache.path}")
    cache.save()
    return cache


def propagate_coartist_genres(library: Library, cache: LookupCache) -> int:
    """Fill empty artists from co-artists on shared tracks (no extra HTTP)."""
    by_id: dict[str, ArtistLookup] = {}
    for lookup in cache.artists.values():
        if lookup.spotify_id:
            by_id[lookup.spotify_id] = lookup

    filled = 0
    co_labels: dict[str, Counter[str]] = defaultdict(Counter)
    for track in library.tracks:
        ids = [a.id for a in track.artists if a.id]
        label_sets = []
        for artist_id in ids:
            lookup = by_id.get(artist_id)
            if lookup and (lookup.genres or lookup.tags or lookup.fallback_genres):
                label_sets.append(
                    [label for label in lookup.style_labels if normalize_label(label) not in META_LABELS]
                )
        if not label_sets:
            continue
        for artist_id in ids:
            lookup = by_id.get(artist_id)
            if lookup is None:
                continue
            if lookup.genres or lookup.tags or lookup.fallback_genres:
                continue
            for labels in label_sets:
                co_labels[artist_id].update(labels)

    for artist_id, counts in co_labels.items():
        lookup = by_id.get(artist_id)
        if lookup is None or lookup.fallback_genres or lookup.genres or lookup.tags:
            continue
        inherited = [name for name, _n in counts.most_common(8)]
        if not inherited:
            continue
        lookup.fallback_genres = inherited
        lookup.source = "coartist"
        filled += 1
    if filled:
        cache.save()
    return filled


def apply_labels_to_library(library: Library, cache: LookupCache) -> Library:
    by_id = {lookup.spotify_id: lookup for lookup in cache.artists.values() if lookup.spotify_id}
    by_name = {_norm(lookup.query): lookup for lookup in cache.artists.values()}
    for track in library.tracks:
        labels: list[str] = []
        for artist in track.artists:
            lookup = by_id.get(artist.id) or by_name.get(_norm(artist.name))
            if lookup is None:
                continue
            for label in lookup.style_labels:
                if label not in labels:
                    labels.append(label)
        if labels:
            track.genres = labels
    return library


def enrichment_summary(cache: LookupCache, library: Library | None = None) -> dict:
    rows = list(cache.artists.values())
    mb = [r for r in rows if r.source.startswith("musicbrainz") and (r.genres or r.tags)]
    mb_empty = [r for r in rows if r.source == "musicbrainz-empty" and not r.fallback_genres]
    fallback = [r for r in rows if r.fallback_genres]
    missing = [r for r in rows if not r.style_labels]
    label_counts: Counter[str] = Counter()
    for row in rows:
        label_counts.update(normalize_label(x) for x in row.style_labels if normalize_label(x) not in META_LABELS)

    covered_tracks = 0
    if library is not None:
        by_id = {r.spotify_id: r for r in rows if r.spotify_id}
        for track in library.tracks:
            if any((by_id.get(a.id) and by_id[a.id].style_labels) for a in track.artists if a.id):
                covered_tracks += 1

    return {
        "artists_cached": len(rows),
        "musicbrainz_with_tags": len(mb),
        "musicbrainz_empty": len(mb_empty),
        "fallback_or_coartist": len(fallback),
        "still_unlabeled": len(missing),
        "library_tracks": library.track_count if library else None,
        "tracks_with_labeled_artist": covered_tracks if library else None,
        "top_labels": label_counts.most_common(40),
    }


def _lookup_one(
    client: MusicBrainzClient,
    artist: ArtistRef,
    *,
    progress: Progress | None,
    index: int,
    total: int,
) -> ArtistLookup:
    try:
        lookup = client.lookup_name(artist.name)
    except MusicBrainzError as exc:
        lookup = ArtistLookup(
            query=artist.name,
            spotify_id=artist.id,
            found=False,
            error=f"{type(exc).__name__}: {exc}",
            source="error",
        )
        if progress:
            progress(f"[{index}/{total}] {artist.name} ERR {exc}")
        return lookup
    lookup.spotify_id = artist.id
    lookup.query = artist.name
    if progress:
        labels = lookup.style_labels or ["NO TAGS"]
        progress(f"[{index}/{total}] {artist.name} -> {labels[:8]}")
    return lookup


def apply_local_fallbacks(cache: LookupCache) -> int:
    """Re-apply name/disambiguation fallbacks to unlabeled cached artists."""
    filled = 0
    for lookup in cache.artists.values():
        if lookup.genres or lookup.tags or lookup.fallback_genres:
            continue
        _apply_fallbacks(lookup)
        if lookup.fallback_genres:
            filled += 1
    if filled:
        cache.save()
    return filled


def _apply_fallbacks(lookup: ArtistLookup) -> None:
    if lookup.genres or lookup.tags:
        return
    guessed = infer_genres_from_name(lookup.query)
    if not guessed:
        guessed = infer_genres_from_disambiguation(lookup.disambiguation)
    if guessed:
        lookup.fallback_genres = guessed
        if lookup.source in {"", "musicbrainz-empty", "musicbrainz", "coartist"}:
            lookup.source = "fallback"


def infer_genres_from_disambiguation(text: str) -> list[str]:
    return labels_from_free_text(text)


def infer_genres_from_name(name: str) -> list[str]:
    key = _norm(name)
    if key in KNOWN_ARTIST_FALLBACKS:
        return list(KNOWN_ARTIST_FALLBACKS[key])
    compact = key.replace(".", " ").replace("'", " ")
    compact = re.sub(r"\s+", " ", compact).strip()
    if compact in KNOWN_ARTIST_FALLBACKS:
        return list(KNOWN_ARTIST_FALLBACKS[compact])
    for pattern, labels in NAME_HEURISTICS:
        if pattern.search(name):
            return list(labels)
    return []


def _norm(value: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    text = text.casefold()
    text = re.sub(r"[^\w\s&]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()
