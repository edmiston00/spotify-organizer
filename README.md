# Spotify Liked Songs Organizer

A free, local Python CLI that scans **your** Spotify Liked Songs and proposes review-first playlists.

- Default `analyze` still builds **5–10 data-driven playlists** from genres, release years, and save dates when Spotify artist genres are available.
- `analyze --style-only --allow-overlap` builds **~8–15 overlapping style playlists** from **MusicBrainz** genres/tags (plus name/co-artist fallbacks). Names are prefixed `GB `.

It is a **review-first** tool. `analyze` is dry-run only. Playlists are **never** created unless you explicitly run:

```bash
spotify-organizer apply --apply
```

`spotify-organizer apply` without `--apply` always refuses.

This is a personal organizer for one Spotify account on your machine. It is not a hosted service.

## What the Web API actually allows

The scan uses only documented Spotify Web API endpoints. It does **not** call removed or new-app-blocked surfaces (Recommendations, Audio Features, Audio Analysis, Related Artists).

| Signal | Source | Notes |
| --- | --- | --- |
| Liked Songs | `GET /me/tracks` | Paginated, max 50 per page. Local files and missing tracks are skipped. |
| Album release year | `album.release_date` on each saved track | No extra album lookup. |
| Artist genres (Spotify) | `GET /artists?ids=` (50/id) or `GET /artists/{id}` | Batch `GET /artists` was **removed for Development Mode** in February 2026. Extended Quota apps still have it. The client tries the batch path, then falls back to concurrent single-artist fetches with `429` / `Retry-After` backoff. Dev Mode often **403s**, so style clustering uses MusicBrainz instead. |
| Artist genres (MusicBrainz) | `GET https://musicbrainz.org/ws/2/artist` search + `inc=genres+tags` lookup | No API key. **~1 request/second** and a descriptive User-Agent are required. Lookups are cached under `.cache/spotify-organizer/musicbrainz_artists.json` and can resume. |
| Optional listening signal | `GET /me/top/artists` (`user-top-read`) | Still available. Used only as an overlap hint, never as a fake “taste API”. |
| Save recency | `added_at` on saved tracks | 90-day and calendar-year “saved in” slices when they are distinctive. |

Suggestions for the default analyzer are **not** a fixed taxonomy. Style-only mode maps MusicBrainz tags onto overlapping sound clusters (Southern trap *and* Hip-Hop, House *and* Electronic) instead of date/era buckets.

## MusicBrainz enrichment

Spotify artist-genre fetches frequently 403 in Development Mode. Style proposals therefore look up each unique artist on [MusicBrainz](https://musicbrainz.org/doc/MusicBrainz_API):

1. Search `artist:"Name"` and pick a hit (exact name, skip tributes/karaoke, extra weight for known collisions such as Sublime = US ska-punk group).
2. Lookup `inc=genres+tags`. Official **genres** plus **high-count tags** are kept; nationality/era meta-tags (`american`, `90s`, `seen live`) are ignored.
3. If MusicBrainz is empty (common for some dance producers, e.g. Dom Dolla), fall back to a name/keyword map and co-artists on the same liked tracks. Last.fm/Discogs are not required and are not called unless you add your own keys later.
4. Cache every result under `.cache/spotify-organizer/musicbrainz_artists.json`. Re-runs skip completed artists.

Rate limit: **one request per second per IP**. A ~1,600-artist library is typically **30–60+ minutes** because each artist needs a search plus a detail lookup. That is expected. Do not parallelize; MusicBrainz will 503 and then block the IP.

```bash
# Resumable genre lookup (no Spotify writes)
spotify-organizer enrich-genres \
  --library-json reports/library.json \
  --artists-json reports/unique_artists.json

# Style-only overlapping proposals (dry-run)
spotify-organizer analyze \
  --library-json reports/library.json \
  --style-only --allow-overlap
```

`enrich-genres` and `analyze` never create Spotify playlists. Review `reports/suggestions.json` (full URI lists, gitignored) and `reports/suggestions.sample.json` (committed preview).

## Review-first workflow

1. Create a Spotify app and local `.env` (below).
2. Run `spotify-organizer analyze` (this is also the default command).
3. Read `reports/suggestions.json` and `reports/suggestions.csv`. Each suggestion has a name, one-line description, approximate track count, sample tracks, and a rationale.
4. Only if you want those playlists on your account:

   ```bash
   spotify-organizer apply --apply
   ```

   Optional: `--only genre-indie-soul` to apply a subset.

`analyze` never writes playlists. Bare `apply` prints the refusal and exits with status 2.

## Spotify Developer Dashboard setup

1. Open [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and sign in.
2. **Create app**. Give it any name/description. For “Redirect URI” enter exactly:

   ```text
   http://127.0.0.1:8888/callback
   ```

   Do not use `localhost`; Spotify treats it as different from `127.0.0.1`.
3. Open the app → **Settings**. Copy **Client ID** and **Client Secret**.
4. Confirm the redirect URI is listed. Save.
5. Development Mode notes (as of the February 2026 Web API changes):
   - The app **owner needs Spotify Premium** or the app will not work.
   - New Dev Mode apps are limited to **5 authorized users**.
   - Batch metadata endpoints (`GET /artists`, `GET /albums`, `GET /tracks`) are gone in Dev Mode; this CLI already handles that.
   - Extended Quota apps keep the older endpoints; the client is compatible with both.

## Install

Python 3.10+ (stdlib + the packages in `pyproject.toml`).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# or, for tests
pip install -e ".[dev]"
```

Copy the example env file and fill in Dashboard values:

```bash
cp .env.example .env
```

`.env.example`:

```env
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
```

Never commit `.env`, OAuth token caches, or Client Secrets.

## First-run OAuth

The CLI uses the **Authorization Code** flow via Spotipy’s `SpotifyOAuth`, with a local redirect listener on `http://127.0.0.1:8888/callback`.

On first `analyze` or `apply --apply` it opens a browser (or prints a URL with `--no-browser`). Approve access. The refresh token is stored in `.spotify_token_cache` in the working directory (gitignored).

Scopes requested (one login covers later apply):

- `user-library-read` — Liked Songs
- `user-top-read` — optional top artists
- `playlist-modify-private` / `playlist-modify-public` — only used when you pass `--apply`

Write scopes are requested up front so apply does not force a second consent. They are unused until `--apply`.

## Commands

```bash
# Default = analyze (dry-run)
spotify-organizer
spotify-organizer analyze

# Re-run suggestions from a saved snapshot (no Spotify calls)
spotify-organizer analyze --library-json reports/library.json

# MusicBrainz style clusters (overlapping, GB-prefixed names)
spotify-organizer enrich-genres --library-json reports/library.json
spotify-organizer analyze --library-json reports/library.json --style-only --allow-overlap

# Skip top-artists call
spotify-organizer analyze --no-top-artists

# Review the JSON/CSV, then — only if you want writes:
spotify-organizer apply              # refuses, exit 2
spotify-organizer apply --apply      # create / top-up playlists
spotify-organizer apply --apply --only "Time Capsule: 1980s"
```

Outputs from `analyze` (all under `reports/` by default):

- `suggestions.json` — full proposal including track URIs for a later apply
- `suggestions.csv` — same fields without URI lists, for easy review
- `suggestions.sample.json` — playlist names, counts, samples, truncated URIs (safe to commit)
- `enrichment_summary.json` — MusicBrainz hit rates after `enrich-genres`
- `library.json` — local snapshot (track names, artists, genres, years)

### Apply behavior

- Idempotent **by playlist name**: if a playlist with that exact name already exists on your account, missing tracks are appended; existing tracks are left alone.
- Adds in batches of **at most 100 URIs** (`POST /playlists/{id}/items`, with a fallback to `/tracks` for Extended Quota apps).
- New playlists are created with `POST /me/playlists` (private unless `--public`).
- Does not delete tracks you added by hand.

## Development

```bash
python -m compileall spotify_organizer tests
python -c "import spotify_organizer; from spotify_organizer.cli import main"
pytest
```

## Privacy

Everything runs locally. Tokens stay in `.spotify_token_cache`. Spotify and MusicBrainz artist genre responses are cached under `.cache/spotify-organizer/` so enrichment can resume after a stop. None of these cache paths are committed.
