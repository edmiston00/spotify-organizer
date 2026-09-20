from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError

from spotify_organizer.config import DEFAULT_REDIRECT_URI, Settings

# Loopback redirect required by the Spotify Dashboard for this app.
# The page does not need to load; paste-auth copies the address bar.

PASTE_AUTH_BANNER = """
================================================================
Spotify login from a phone (no local browser)
================================================================

This uses the standard Authorization Code flow. Spotify does NOT
allow Device Authorization Grant (the TV "enter this code" flow)
for normal Developer Dashboard apps — those clients are
allowlisted; a custom app gets unauthorized_client.

Keep the app Redirect URI exactly:
  {redirect_uri}
(loopback http://127.0.0.1 is still allowed. Do not change it.)

1. On your phone, open this URL and approve access:

{url}

2. Spotify then redirects to:
  {redirect_uri}?code=...&state=...
   That page may fail to load on the phone — that is expected.
   Nothing needs to listen on this computer.
   Copy the FULL address from the address bar, or copy only
   the `code` query parameter.

3. Paste it below, then press Enter.
================================================================
""".lstrip()


class AuthError(RuntimeError):
    """User-facing OAuth / paste-auth failure (never includes secrets)."""


def build_oauth(
    settings: Settings,
    *,
    open_browser: bool = True,
    state: str | None = None,
) -> SpotifyOAuth:
    """Authorization Code flow with a local http://127.0.0.1:8888/callback server."""
    return SpotifyOAuth(
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        redirect_uri=settings.redirect_uri,
        scope=settings.scope,
        cache_path=settings.token_cache,
        open_browser=open_browser,
        show_dialog=False,
        state=state,
    )


def access_token(oauth: SpotifyOAuth) -> str:
    token = oauth.get_access_token(as_dict=True, check_cache=True)
    if not token or not token.get("access_token"):
        raise RuntimeError("Spotify OAuth did not return an access token.")
    return str(token["access_token"])


def has_usable_cache(oauth: SpotifyOAuth) -> bool:
    """True when a cached token exists and can be used or refreshed."""
    try:
        token = oauth.get_cached_token()
    except Exception:
        return False
    return bool(token and token.get("access_token"))


def parse_callback_input(raw: str) -> tuple[str, str | None]:
    """Extract (code, state) from a pasted redirect URL, query string, or raw code."""
    text = (raw or "").strip().strip("\"'")
    if not text:
        raise AuthError(
            "Nothing was pasted. Paste the redirect URL from the address bar "
            "or the `code` query parameter."
        )

    url_match = re.search(r"https?://\S+", text)
    if url_match:
        text = url_match.group(0).rstrip(".,);]>\"'")

    looks_like_query = ("code=" in text or "error=" in text) and "://" not in text
    if looks_like_query:
        text = f"{DEFAULT_REDIRECT_URI}?{text.lstrip('?')}"
    elif text.startswith("/callback"):
        text = f"http://127.0.0.1:8888{text}"

    if "://" in text:
        parsed = urlparse(text)
        query = parse_qs(parsed.query, keep_blank_values=False)
        if parsed.fragment and ("=" in parsed.fragment):
            query = {**query, **parse_qs(parsed.fragment, keep_blank_values=False)}
        if "error" in query:
            err = (query.get("error") or ["unknown"])[0]
            raise AuthError(f"Spotify authorization failed: {err}")
        codes = query.get("code")
        if codes and codes[0]:
            state = (query.get("state") or [None])[0]
            return codes[0], state
        raise AuthError(
            "Pasted URL has no `code` query parameter. Copy the full address "
            "bar after Spotify redirects (or copy only the code value)."
        )

    if any(ch.isspace() for ch in text) or "&" in text or text.startswith("code="):
        raise AuthError(
            "Could not parse pasted input as a redirect URL or authorization code."
        )
    return text, None


def run_paste_auth(
    oauth: SpotifyOAuth,
    *,
    prompt: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
) -> None:
    """Print a phone-friendly authorize URL, accept a pasted callback, cache tokens.

    Does not open a browser and does not listen on 127.0.0.1.
    Never prints client secrets or access/refresh tokens.
    """
    if not oauth.state:
        oauth.state = secrets.token_urlsafe(24)

    url = oauth.get_authorize_url()
    echo(
        PASTE_AUTH_BANNER.format(
            url=url,
            redirect_uri=oauth.redirect_uri or DEFAULT_REDIRECT_URI,
        )
    )
    try:
        pasted = prompt("Paste redirect URL or code: ")
    except EOFError as exc:
        raise AuthError("No input received. Paste the redirect URL or code.") from exc

    code, state = parse_callback_input(pasted)
    if oauth.state and state and state != oauth.state:
        raise AuthError(
            "State mismatch. Paste the redirect URL from this login attempt."
        )

    try:
        token = oauth.get_access_token(code=code, as_dict=True, check_cache=False)
    except SpotifyOauthError as exc:
        raise AuthError(_oauth_error_message(exc)) from exc

    if not token or not token.get("access_token"):
        raise AuthError("Spotify OAuth did not return an access token.")

    echo("Login successful. Tokens saved to the local cache (not printed).")


def ensure_login(oauth: SpotifyOAuth, *, paste: bool) -> str:
    """Use cache when possible; otherwise desktop listener or paste-auth.

    Returns ``cached``, ``paste``, or ``desktop``.
    """
    if has_usable_cache(oauth):
        return "cached"
    if paste:
        run_paste_auth(oauth)
        return "paste"
    access_token(oauth)
    return "desktop"


def _oauth_error_message(exc: SpotifyOauthError) -> str:
    err = getattr(exc, "error", None) or "token_exchange_failed"
    # Do not include exception payloads — they can contain request details.
    return f"Spotify token exchange failed ({err}). Re-copy the code and try again."
