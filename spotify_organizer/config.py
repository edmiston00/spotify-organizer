from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"
TOKEN_CACHE_PATH = ".spotify_token_cache"
ARTIST_GENRE_CACHE = Path(".cache") / "spotify-organizer" / "artist_genres.json"
MUSICBRAINZ_CACHE = Path(".cache") / "spotify-organizer" / "musicbrainz_artists.json"
MUSICBRAINZ_BASE = "https://musicbrainz.org/ws/2"
MUSICBRAINZ_MIN_INTERVAL = 1.1
# Descriptive UA with contact, as required by MusicBrainz rate-limiting policy.
MUSICBRAINZ_USER_AGENT = (
    "SpotifyOrganizer/0.2.0 "
    "(https://github.com/edmiston00/spotify-organizer; cedmist@gmail.com)"
)
PLAYLIST_NAME_PREFIX = "GB "

# Analyze only needs library + optional personalization.
# Write scopes are requested so a later `apply --apply` does not force a second login.
# Playlists are still never created unless the user passes that flag.
SCOPES = (
    "user-library-read",
    "user-top-read",
    "playlist-modify-private",
    "playlist-modify-public",
)

SAVED_TRACKS_PAGE = 50
ARTIST_BATCH_LIMIT = 50
PLAYLIST_PAGE = 50
PLAYLIST_ADD_LIMIT = 100
PLAYLIST_DESCRIPTION_LIMIT = 300

API_BASE = "https://api.spotify.com/v1"


@dataclass(frozen=True)
class Settings:
    client_id: str
    client_secret: str
    redirect_uri: str
    token_cache: str = TOKEN_CACHE_PATH

    @property
    def scope(self) -> str:
        return " ".join(SCOPES)


def load_settings(dotenv_path: str | Path | None = None) -> Settings:
    load_dotenv(dotenv_path)

    client_id = (os.getenv("SPOTIFY_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("SPOTIFY_CLIENT_SECRET") or "").strip()
    redirect_uri = (os.getenv("SPOTIFY_REDIRECT_URI") or DEFAULT_REDIRECT_URI).strip()

    missing = [
        name
        for name, value in (
            ("SPOTIFY_CLIENT_ID", client_id),
            ("SPOTIFY_CLIENT_SECRET", client_secret),
        )
        if not value
    ]
    if missing:
        raise ConfigError(
            "Missing required environment variables: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and add your Spotify app credentials."
        )

    return Settings(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )


class ConfigError(RuntimeError):
    """Raised when required Spotify credentials are missing."""
