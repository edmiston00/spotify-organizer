from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Iterable

from spotify_organizer.models import Library, Suggestion, Track

MIN_SUGGESTIONS = 5
MAX_SUGGESTIONS = 10
SAMPLE_SIZE = 5
MAX_OVERLAP = 0.72


def discover_suggestions(
    library: Library,
    *,
    min_tracks: int | None = None,
    max_suggestions: int = MAX_SUGGESTIONS,
    now: datetime | None = None,
) -> list[Suggestion]:
    """Build 5–10 playlists from *this* library's genres, years, and save dates.

    There is no fixed genre/era taxonomy. Clusters are whatever the scan found
    in enough volume, then diversified so we do not emit ten near-duplicates.
    """
    tracks = [t for t in library.tracks if t.uri]
    if not tracks:
        return []

    max_suggestions = max(1, min(max_suggestions, MAX_SUGGESTIONS))
    threshold = min_tracks if min_tracks is not None else _adaptive_min(len(tracks))
    now = now or datetime.now(timezone.utc)

    candidates: list[Suggestion] = []
    candidates.extend(_genre_suggestions(tracks, threshold))
    candidates.extend(_decade_suggestions(tracks, threshold))
    candidates.extend(_genre_decade_suggestions(tracks, max(5, threshold - 2)))
    candidates.extend(_artist_suggestions(tracks, max(8, threshold)))
    candidates.extend(_recent_suggestions(tracks, now, max(8, threshold)))
    candidates.extend(_saved_year_suggestions(tracks, threshold))
    candidates.extend(_top_artist_suggestions(library, max(8, threshold)))

    if len(_usable(candidates, threshold=max(5, threshold - 3))) < MIN_SUGGESTIONS:
        threshold = max(5, min(threshold, 6))
        extra = []
        extra.extend(_genre_suggestions(tracks, threshold))
        extra.extend(_decade_suggestions(tracks, threshold))
        extra.extend(_artist_suggestions(tracks, threshold))
        candidates.extend(extra)

    ranked = _unique_by_id(candidates)
    selected = _diversify(ranked, max_suggestions=max_suggestions)
    if len(selected) < min(MIN_SUGGESTIONS, max_suggestions) and ranked:
        used = {s.id for s in selected}
        for suggestion in ranked:
            if suggestion.id in used:
                continue
            selected.append(suggestion)
            used.add(suggestion.id)
            if len(selected) >= min(MIN_SUGGESTIONS, max_suggestions, len(ranked)):
                break

    return selected[:max_suggestions]


def _adaptive_min(library_size: int) -> int:
    return max(6, min(18, library_size // 20 or 6))


def _genre_suggestions(tracks: list[Track], min_tracks: int) -> list[Suggestion]:
    buckets: dict[str, list[Track]] = defaultdict(list)
    for track in tracks:
        for genre in _normalized_genres(track.genres):
            buckets[genre].append(track)

    out: list[Suggestion] = []
    for genre, members in buckets.items():
        members = _unique_tracks(members)
        if len(members) < min_tracks:
            continue
        artists = _artist_count(members)
        display = _title_genre(genre)
        out.append(
            _build(
                kind="genre",
                key=genre,
                name=f"{display} Favorites",
                description=f"{len(members)} liked tracks tagged {display}.",
                rationale=(
                    f"{display} is a dense tag in this library: {len(members)} liked "
                    f"tracks across {artists} artists — not a preset category."
                ),
                members=members,
            )
        )
    return out


def _decade_suggestions(tracks: list[Track], min_tracks: int) -> list[Suggestion]:
    buckets: dict[int, list[Track]] = defaultdict(list)
    for track in tracks:
        if track.year:
            buckets[(track.year // 10) * 10].append(track)

    out: list[Suggestion] = []
    for decade, members in buckets.items():
        members = _unique_tracks(members)
        if len(members) < min_tracks:
            continue
        label = f"{decade}s"
        out.append(
            _build(
                kind="decade",
                key=str(decade),
                name=f"Time Capsule: {label}",
                description=f"Liked songs whose albums were released in the {label}.",
                rationale=(
                    f"{len(members)} liked tracks have album release years in the {label}, "
                    f"a real cluster in this library rather than a canned era list."
                ),
                members=members,
            )
        )
    return out


def _genre_decade_suggestions(tracks: list[Track], min_tracks: int) -> list[Suggestion]:
    buckets: dict[tuple[str, int], list[Track]] = defaultdict(list)
    for track in tracks:
        if not track.year:
            continue
        decade = (track.year // 10) * 10
        for genre in _normalized_genres(track.genres):
            buckets[(genre, decade)].append(track)

    out: list[Suggestion] = []
    for (genre, decade), members in buckets.items():
        members = _unique_tracks(members)
        if len(members) < min_tracks:
            continue
        # Skip intersections that are almost the entire genre or decade bucket.
        display = _title_genre(genre)
        out.append(
            _build(
                kind="genre_decade",
                key=f"{genre}-{decade}",
                name=f"{display} · {decade}s",
                description=f"{display} liked tracks released in the {decade}s.",
                rationale=(
                    f"The intersection of {display} and {decade}s release years holds "
                    f"{len(members)} liked tracks — a tighter slice than either signal alone."
                ),
                members=members,
            )
        )
    return out


def _artist_suggestions(tracks: list[Track], min_tracks: int) -> list[Suggestion]:
    buckets: dict[str, list[Track]] = defaultdict(list)
    names: dict[str, str] = {}
    for track in tracks:
        for artist in track.artists:
            if not artist.id:
                continue
            buckets[artist.id].append(track)
            names[artist.id] = artist.name

    out: list[Suggestion] = []
    for artist_id, members in buckets.items():
        members = _unique_tracks(members)
        if len(members) < min_tracks:
            continue
        name = names.get(artist_id) or "Unknown artist"
        out.append(
            _build(
                kind="artist",
                key=artist_id,
                name=f"{name} — Liked",
                description=f"Every liked track featuring {name}.",
                rationale=(
                    f"{name} appears on {len(members)} liked tracks, enough to stand "
                    f"alone as a library-specific artist playlist."
                ),
                members=members,
            )
        )
    return out


def _recent_suggestions(
    tracks: list[Track], now: datetime, min_tracks: int
) -> list[Suggestion]:
    recent = [t for t in tracks if _days_since(t.added_at, now) is not None and _days_since(t.added_at, now) <= 90]
    recent = _unique_tracks(recent)
    if len(recent) < min_tracks:
        return []
    if len(recent) > int(len(tracks) * 0.85):
        return []
    return [
        _build(
            kind="recent",
            key="90d",
            name="Recently Saved",
            description="Tracks you liked in the last 90 days.",
            rationale=(
                f"{len(recent)} tracks were saved in the last 90 days "
                f"(from Liked Songs `added_at`), a recency slice the Web API actually exposes."
            ),
            members=recent,
        )
    ]


def _saved_year_suggestions(tracks: list[Track], min_tracks: int) -> list[Suggestion]:
    buckets: dict[int, list[Track]] = defaultdict(list)
    for track in tracks:
        saved = _parse_dt(track.added_at)
        if saved:
            buckets[saved.year].append(track)

    if len(buckets) < 2:
        return []

    out: list[Suggestion] = []
    for year, members in buckets.items():
        members = _unique_tracks(members)
        if len(members) < min_tracks:
            continue
        if len(members) > int(len(tracks) * 0.8):
            continue
        out.append(
            _build(
                kind="saved_year",
                key=str(year),
                name=f"Saved in {year}",
                description=f"Songs added to Liked Songs during {year}.",
                rationale=(
                    f"{len(members)} likes were timestamped in {year} via `added_at`, "
                    f"so this is a saving-habit playlist, not a release-year bin."
                ),
                members=members,
            )
        )
    return out


def _top_artist_suggestions(library: Library, min_tracks: int) -> list[Suggestion]:
    if not library.top_artists:
        return []
    top_ids = {a.id for a in library.top_artists if a.id}
    if not top_ids:
        return []
    members = [
        t
        for t in library.tracks
        if t.uri and any(a.id in top_ids for a in t.artists)
    ]
    members = _unique_tracks(members)
    if len(members) < min_tracks:
        return []
    if len(members) > int(len(library.tracks) * 0.85):
        return []
    sample_names = ", ".join(a.name for a in library.top_artists[:3] if a.name)
    return [
        _build(
            kind="top_artists",
            key="medium-term",
            name="Top Artists Overlap",
            description="Liked songs by artists in your current top-artists list.",
            rationale=(
                f"{len(members)} liked tracks overlap your GET /me/top/artists set"
                + (f" (including {sample_names})" if sample_names else "")
                + " — the personalization endpoint the Web API still offers."
            ),
            members=members,
        )
    ]


def _build(
    *,
    kind: str,
    key: str,
    name: str,
    description: str,
    rationale: str,
    members: list[Track],
) -> Suggestion:
    slug = _slug(f"{kind}-{key}")
    samples = [t.sample_label() for t in members[:SAMPLE_SIZE]]
    return Suggestion(
        id=slug[:80],
        name=name[:100],
        description=description[:240],
        approx_track_count=len(members),
        sample_tracks=samples,
        rationale=rationale,
        track_uris=[t.uri for t in members],
        kind=kind,
    )


def _diversify(candidates: list[Suggestion], *, max_suggestions: int) -> list[Suggestion]:
    scored = sorted(candidates, key=_score, reverse=True)
    selected: list[Suggestion] = []
    for candidate in scored:
        if len(selected) >= max_suggestions:
            break
        if any(_jaccard(candidate, other) > MAX_OVERLAP for other in selected):
            continue
        # Prefer not to keep a genre+decade that duplicates an already chosen genre.
        if candidate.kind == "genre_decade" and any(
            other.kind == "genre" and _jaccard(candidate, other) > 0.55 for other in selected
        ):
            continue
        selected.append(candidate)
    return selected


def _score(suggestion: Suggestion) -> tuple[float, int, str]:
    size = suggestion.approx_track_count
    kind_weight = {
        "genre_decade": 1.15,
        "genre": 1.10,
        "decade": 1.00,
        "top_artists": 0.95,
        "recent": 0.90,
        "saved_year": 0.85,
        "artist": 0.80,
    }.get(suggestion.kind, 1.0)
    # Mid-size clusters are more useful than a giant "pop" dump.
    mid = 1.0 - abs(size - 40) / 200
    return (kind_weight * size * max(mid, 0.35), size, suggestion.name)


def _jaccard(a: Suggestion, b: Suggestion) -> float:
    left, right = set(a.track_uris), set(b.track_uris)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _unique_by_id(suggestions: list[Suggestion]) -> list[Suggestion]:
    seen: dict[str, Suggestion] = {}
    for suggestion in suggestions:
        previous = seen.get(suggestion.id)
        if previous is None or suggestion.approx_track_count > previous.approx_track_count:
            seen[suggestion.id] = suggestion
    return list(seen.values())


def _usable(suggestions: Iterable[Suggestion], *, threshold: int) -> list[Suggestion]:
    return [s for s in suggestions if s.approx_track_count >= threshold]


def _normalized_genres(genres: Iterable[str]) -> list[str]:
    out: list[str] = []
    for genre in genres:
        cleaned = re.sub(r"\s+", " ", (genre or "").strip().lower())
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


def _title_genre(genre: str) -> str:
    parts = []
    for word in genre.split():
        if word in {"r&b", "rnb"}:
            parts.append("R&B")
        elif word in {"uk", "us", "nyc", "la"}:
            parts.append(word.upper())
        else:
            parts.append(word.capitalize())
    return " ".join(parts)


def _unique_tracks(tracks: list[Track]) -> list[Track]:
    seen: set[str] = set()
    out: list[Track] = []
    for track in tracks:
        key = track.uri or track.id
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(track)
    return out


def _artist_count(tracks: list[Track]) -> int:
    return len({a.id or a.name for t in tracks for a in t.artists})


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if slug:
        return slug
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _days_since(value: str, now: datetime) -> int | None:
    parsed = _parse_dt(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, int((now - parsed).total_seconds() // 86400))


def library_genre_counts(library: Library) -> Counter[str]:
    counts: Counter[str] = Counter()
    for track in library.tracks:
        counts.update(_normalized_genres(track.genres))
    return counts
