from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ArtistRef:
    id: str
    name: str


@dataclass
class Track:
    id: str
    uri: str
    name: str
    artists: list[ArtistRef]
    album_name: str
    release_date: str
    year: int | None
    added_at: str
    genres: list[str] = field(default_factory=list)

    def sample_label(self) -> str:
        artist = ", ".join(a.name for a in self.artists) or "Unknown artist"
        return f"{self.name} — {artist}"

    def artist_ids(self) -> list[str]:
        return [a.id for a in self.artists if a.id]


@dataclass
class TopArtist:
    id: str
    name: str
    genres: list[str] = field(default_factory=list)


@dataclass
class Library:
    tracks: list[Track]
    top_artists: list[TopArtist] = field(default_factory=list)
    scanned_at: str = ""

    @property
    def track_count(self) -> int:
        return len(self.tracks)


@dataclass
class Suggestion:
    id: str
    name: str
    description: str
    approx_track_count: int
    sample_tracks: list[str]
    rationale: str
    track_uris: list[str]
    kind: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "approx_track_count": self.approx_track_count,
            "sample_tracks": list(self.sample_tracks),
            "rationale": self.rationale,
            "track_uris": list(self.track_uris),
            "kind": self.kind,
        }


def library_to_dict(library: Library) -> dict[str, Any]:
    return {
        "scanned_at": library.scanned_at,
        "track_count": library.track_count,
        "tracks": [
            {
                "id": t.id,
                "uri": t.uri,
                "name": t.name,
                "artists": [asdict(a) for a in t.artists],
                "album_name": t.album_name,
                "release_date": t.release_date,
                "year": t.year,
                "added_at": t.added_at,
                "genres": list(t.genres),
            }
            for t in library.tracks
        ],
        "top_artists": [asdict(a) for a in library.top_artists],
    }


def library_from_dict(data: dict[str, Any]) -> Library:
    tracks: list[Track] = []
    for raw in data.get("tracks", []):
        artists = [
            ArtistRef(id=str(a.get("id") or ""), name=str(a.get("name") or ""))
            for a in raw.get("artists", [])
        ]
        tracks.append(
            Track(
                id=str(raw.get("id") or ""),
                uri=str(raw.get("uri") or ""),
                name=str(raw.get("name") or ""),
                artists=artists,
                album_name=str(raw.get("album_name") or ""),
                release_date=str(raw.get("release_date") or ""),
                year=raw.get("year"),
                added_at=str(raw.get("added_at") or ""),
                genres=list(raw.get("genres") or []),
            )
        )
    top = [
        TopArtist(
            id=str(a.get("id") or ""),
            name=str(a.get("name") or ""),
            genres=list(a.get("genres") or []),
        )
        for a in data.get("top_artists", [])
    ]
    return Library(
        tracks=tracks,
        top_artists=top,
        scanned_at=str(data.get("scanned_at") or ""),
    )
