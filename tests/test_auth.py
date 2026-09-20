from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from spotipy.oauth2 import SpotifyOauthError

from spotify_organizer.auth import (
    AuthError,
    ensure_login,
    has_usable_cache,
    parse_callback_input,
    run_paste_auth,
)
from spotify_organizer.cli import _build_parser, main
from spotify_organizer.config import DEFAULT_REDIRECT_URI, Settings


REDIRECT = DEFAULT_REDIRECT_URI
FULL_URL = f"{REDIRECT}?code=AQ_TEST_CODE&state=csrf123"
SECRET_TOKEN = "secret-access-token-do-not-print"
SECRET_REFRESH = "secret-refresh-token-do-not-print"


def test_parse_full_redirect_url():
    code, state = parse_callback_input(FULL_URL)
    assert code == "AQ_TEST_CODE"
    assert state == "csrf123"


def test_parse_url_with_surrounding_text_and_quotes():
    pasted = f'Here it is: "{FULL_URL}" thanks'
    code, state = parse_callback_input(pasted)
    assert code == "AQ_TEST_CODE"
    assert state == "csrf123"


def test_parse_query_string_only():
    code, state = parse_callback_input("code=AQ_ONLY&state=zz")
    assert code == "AQ_ONLY"
    assert state == "zz"


def test_parse_path_only():
    code, state = parse_callback_input("/callback?code=FROM_PATH&state=s")
    assert code == "FROM_PATH"
    assert state == "s"


def test_parse_raw_code():
    code, state = parse_callback_input("  AQRawAuthorizationCode  ")
    assert code == "AQRawAuthorizationCode"
    assert state is None


def test_parse_error_url():
    with pytest.raises(AuthError, match="access_denied"):
        parse_callback_input(f"{REDIRECT}?error=access_denied&state=x")


def test_parse_empty():
    with pytest.raises(AuthError, match="Nothing was pasted"):
        parse_callback_input("   ")


def test_parse_url_missing_code():
    with pytest.raises(AuthError, match="no `code`"):
        parse_callback_input(f"{REDIRECT}?state=only")


def _oauth_mock(*, cached=None, state="csrf123"):
    oauth = MagicMock()
    oauth.redirect_uri = REDIRECT
    oauth.state = state
    oauth.get_authorize_url.return_value = (
        "https://accounts.spotify.com/authorize?client_id=public-id&scope=user-library-read"
    )
    oauth.get_cached_token.return_value = cached
    oauth.get_access_token.return_value = {
        "access_token": SECRET_TOKEN,
        "refresh_token": SECRET_REFRESH,
    }
    oauth.get_auth_response = MagicMock(side_effect=AssertionError("must not listen"))
    return oauth


def test_run_paste_auth_exchanges_code_without_local_server(capsys):
    oauth = _oauth_mock()
    run_paste_auth(oauth, prompt=lambda _: FULL_URL)
    oauth.get_access_token.assert_called_once_with(
        code="AQ_TEST_CODE", as_dict=True, check_cache=False
    )
    oauth.get_auth_response.assert_not_called()
    out = capsys.readouterr().out
    assert "accounts.spotify.com/authorize" in out
    assert "phone" in out.lower()
    assert "unauthorized_client" in out
    assert SECRET_TOKEN not in out
    assert SECRET_REFRESH not in out
    assert "AQ_TEST_CODE" not in out
    assert "client_secret" not in out.lower()
    assert "Login successful" in out


def test_run_paste_auth_accepts_raw_code(capsys):
    oauth = _oauth_mock(state=None)
    oauth.state = None
    run_paste_auth(oauth, prompt=lambda _: "RAWCODEONLY")
    oauth.get_access_token.assert_called_once_with(
        code="RAWCODEONLY", as_dict=True, check_cache=False
    )
    out = capsys.readouterr().out
    assert SECRET_TOKEN not in out
    assert "RAWCODEONLY" not in out


def test_run_paste_auth_state_mismatch():
    oauth = _oauth_mock(state="expected")
    with pytest.raises(AuthError, match="State mismatch"):
        run_paste_auth(
            oauth,
            prompt=lambda _: f"{REDIRECT}?code=AQ&state=other",
        )
    oauth.get_access_token.assert_not_called()


def test_run_paste_auth_wraps_spotify_error():
    oauth = _oauth_mock()
    oauth.get_access_token.side_effect = SpotifyOauthError(
        "invalid_grant", error="invalid_grant"
    )
    with pytest.raises(AuthError, match="token exchange failed"):
        run_paste_auth(oauth, prompt=lambda _: FULL_URL)


def test_has_usable_cache():
    oauth = _oauth_mock(cached={"access_token": SECRET_TOKEN})
    assert has_usable_cache(oauth) is True
    oauth.get_cached_token.return_value = None
    assert has_usable_cache(oauth) is False


def test_ensure_login_skips_paste_when_cached():
    oauth = _oauth_mock(cached={"access_token": SECRET_TOKEN})
    assert ensure_login(oauth, paste=True) == "cached"
    oauth.get_access_token.assert_not_called()
    oauth.get_auth_response.assert_not_called()


def test_ensure_login_desktop_uses_access_token(monkeypatch):
    oauth = _oauth_mock(cached=None)
    monkeypatch.setattr(
        "spotify_organizer.auth.access_token",
        lambda _oauth: SECRET_TOKEN,
    )
    assert ensure_login(oauth, paste=False) == "desktop"
    oauth.get_auth_response.assert_not_called()


def test_help_mentions_paste(capsys):
    with pytest.raises(SystemExit) as ei:
        main(["auth", "--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "--paste" in out
    assert "listen" in out.lower() or "phone" in out.lower()

    with pytest.raises(SystemExit) as ei:
        main(["analyze", "--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "--paste-auth" in out


def test_auth_is_not_swallowed_as_analyze():
    parser = _build_parser()
    args = parser.parse_args(["auth", "--paste"])
    assert args.command == "auth"
    assert args.paste is True


def test_auth_paste_cli_writes_cache_without_printing_secrets(monkeypatch, capsys):
    settings = Settings("public-client-id", "super-secret-client", REDIRECT)
    oauth = _oauth_mock(cached=None)
    captured_kwargs: dict = {}

    def fake_build(_settings, **kwargs):
        captured_kwargs.update(kwargs)
        return oauth

    monkeypatch.setattr("spotify_organizer.cli.load_settings", lambda: settings)
    monkeypatch.setattr("spotify_organizer.cli.build_oauth", fake_build)
    monkeypatch.setattr("builtins.input", lambda _: FULL_URL)

    code = main(["auth", "--paste"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured_kwargs.get("open_browser") is False
    assert "Login successful" in captured.out
    assert SECRET_TOKEN not in captured.out
    assert SECRET_REFRESH not in captured.out
    assert "super-secret-client" not in captured.out
    assert "super-secret-client" not in captured.err
    oauth.get_access_token.assert_called_once()
    oauth.get_auth_response.assert_not_called()


def test_auth_paste_uses_cache_without_prompt(monkeypatch, capsys):
    settings = Settings("public-client-id", "super-secret-client", REDIRECT)
    oauth = _oauth_mock(cached={"access_token": SECRET_TOKEN})
    monkeypatch.setattr("spotify_organizer.cli.load_settings", lambda: settings)
    monkeypatch.setattr("spotify_organizer.cli.build_oauth", lambda *a, **k: oauth)
    monkeypatch.setattr(
        "builtins.input",
        lambda _=None: (_ for _ in ()).throw(AssertionError("should not prompt")),
    )
    code = main(["auth", "--paste"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Already authenticated" in out
    assert SECRET_TOKEN not in out
    oauth.get_access_token.assert_not_called()


def test_analyze_paste_auth_uses_cache_then_dry_run(monkeypatch, tmp_path):
    settings = Settings("public-client-id", "super-secret-client", REDIRECT)
    oauth = _oauth_mock(cached={"access_token": SECRET_TOKEN})
    monkeypatch.setattr("spotify_organizer.cli.load_settings", lambda: settings)
    monkeypatch.setattr("spotify_organizer.cli.build_oauth", lambda *a, **k: oauth)

    from tests.factories import diverse_library

    library = diverse_library()
    monkeypatch.setattr(
        "spotify_organizer.cli.scan_liked_songs",
        lambda *a, **k: library,
    )

    out = tmp_path / "reports"
    code = main(["analyze", "--paste-auth", "--output-dir", str(out)])
    assert code == 0
    oauth.get_auth_response.assert_not_called()
    assert (out / "suggestions.json").exists()
