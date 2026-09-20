from __future__ import annotations

from datetime import datetime, timedelta, timezone

from spotify_organizer.models import ArtistRef, Library, TopArtist, Track


def make_track(
    tid: str,
    name: str,
    *,
    artists: list[tuple[str, str]],
    genres: list[str],
    year: int,
    added_at: str,
    album: str = "Album",
) -> Track:
    return Track(
        id=tid,
        uri=f"spotify:track:{tid}",
        name=name,
        artists=[ArtistRef(id=aid, name=aname) for aid, aname in artists],
        album_name=album,
        release_date=f"{year}-06-01",
        year=year,
        added_at=added_at,
        genres=list(genres),
    )


def diverse_library(*, now: datetime | None = None) -> Library:
    """A mixed library that should yield several distinct, data-driven clusters."""
    now = now or datetime(2026, 9, 20, tzinfo=timezone.utc)
    tracks: list[Track] = []

    def add_group(
        prefix: str,
        count: int,
        artists: list[tuple[str, str]],
        genres: list[str],
        years: list[int],
        added: str,
    ) -> None:
        for i in range(count):
            artist = artists[i % len(artists)]
            year = years[i % len(years)]
            tracks.append(
                make_track(
                    f"{prefix}{i:03d}",
                    f"{prefix} song {i}",
                    artists=[artist],
                    genres=genres,
                    year=year,
                    added_at=added,
                )
            )

    add_group(
        "soul",
        28,
        [("s1", "Amber Vale"), ("s2", "Kite Season"), ("s3", "Low Candle")],
        ["indie soul", "neo soul"],
        [2016, 2017, 2018, 2019],
        "2023-04-12T10:00:00Z",
    )
    add_group(
        "grime",
        24,
        [("g1", "North Circular"), ("g2", "Peckham Wire")],
        ["uk hip hop", "grime"],
        [2019, 2021, 2023, 2024],
        "2024-11-02T10:00:00Z",
    )
    add_group(
        "wave",
        22,
        [("w1", "Chrome Parade"), ("w2", "Night School")],
        ["synthpop", "new wave"],
        [1982, 1984, 1986, 1988],
        "2022-01-08T10:00:00Z",
    )
    add_group(
        "amb",
        16,
        [("a1", "Glass Field"), ("a2", "Slow Antenna")],
        ["ambient"],
        [2011, 2014, 2018, 2022],
        "2024-06-01T10:00:00Z",
    )
    add_group(
        "pop",
        20,
        [("p1", "Studio Eight"), ("p2", "Lemon Radio")],
        ["dance pop", "pop"],
        [2021, 2022, 2024, 2025],
        (now - timedelta(days=12)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    add_group(
        "jazz",
        14,
        [("j1", "Ellis Ward"), ("j2", "Port Trio")],
        ["contemporary jazz", "jazz"],
        [1962, 1968, 1972, 1974],
        "2021-09-20T10:00:00Z",
    )
    for i in range(12):
        tracks.append(
            make_track(
                f"river{i:03d}",
                f"River cut {i}",
                artists=[("river", "River Atlas")],
                genres=["folk pop"],
                year=2015 + (i % 8),
                added_at="2025-02-01T10:00:00Z",
            )
        )

    top = [
        TopArtist(id="g1", name="North Circular", genres=["uk hip hop"]),
        TopArtist(id="p1", name="Studio Eight", genres=["dance pop"]),
        TopArtist(id="river", name="River Atlas", genres=["folk pop"]),
    ]
    return Library(tracks=tracks, top_artists=top, scanned_at=now.isoformat())


def alt_library() -> Library:
    """A second library with different tags — used to prove names are data-driven."""
    tracks = []
    for i in range(20):
        tracks.append(
            make_track(
                f"metal{i:03d}",
                f"Riff {i}",
                artists=[("m1", "Iron Harbor")],
                genres=["progressive metal"],
                year=2004 + (i % 6),
                added_at="2020-03-01T00:00:00Z",
            )
        )
    for i in range(18):
        tracks.append(
            make_track(
                f"bossa{i:03d}",
                f"Bossa {i}",
                artists=[("b1", "João Farol")],
                genres=["bossa nova"],
                year=1964 + (i % 5),
                added_at="2019-03-01T00:00:00Z",
            )
        )
    for i in range(15):
        tracks.append(
            make_track(
                f"drill{i:03d}",
                f"Drill {i}",
                artists=[("d1", "South End")],
                genres=["uk drill"],
                year=2022,
                added_at="2023-03-01T00:00:00Z",
            )
        )
    return Library(tracks=tracks, top_artists=[], scanned_at="2026-01-01T00:00:00+00:00")
