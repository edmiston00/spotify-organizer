from __future__ import annotations

from spotipy.oauth2 import SpotifyOAuth

from spotify_organizer.config import Settings


def build_oauth(settings: Settings, *, open_browser: bool = True) -> SpotifyOAuth:
    """Authorization Code flow with a local http://127.0.0.1:8888/callback server."""
    return SpotifyOAuth(
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        redirect_uri=settings.redirect_uri,
        scope=settings.scope,
        cache_path=settings.token_cache,
        open_browser=open_browser,
        show_dialog=False,
    )


def access_token(oauth: SpotifyOAuth) -> str:
    token = oauth.get_access_token(as_dict=True, check_cache=True)
    if not token or not token.get("access_token"):
        raise RuntimeError("Spotify OAuth did not return an access token.")
    return str(token["access_token"])
