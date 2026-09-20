from __future__ import annotations

from dataclasses import dataclass, field

from spotify_organizer.config import PLAYLIST_ADD_LIMIT, PLAYLIST_DESCRIPTION_LIMIT
from spotify_organizer.models import Suggestion

APPLY_REFUSAL = (
    "Refusing to create or modify playlists. Review reports/suggestions.json first, "
    "then re-run with an explicit flag:\n"
    "  spotify-organizer apply --apply"
)


class ApplyRefused(RuntimeError):
    """Raised when `apply` is invoked without --apply."""


@dataclass
class ApplyAction:
    suggestion_id: str
    name: str
    playlist_id: str | None
    existed: bool
    would_add: int
    already_present: int
    created: bool = False
    added: int = 0


@dataclass
class ApplyReport:
    dry_run: bool
    actions: list[ApplyAction] = field(default_factory=list)
    refused: bool = False


def chunk_uris(uris: list[str], size: int = PLAYLIST_ADD_LIMIT) -> list[list[str]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    return [uris[i : i + size] for i in range(0, len(uris), size)]


def apply_suggestions(
    client,
    suggestions: list[Suggestion],
    *,
    do_apply: bool,
    only_ids: list[str] | None = None,
    public: bool = False,
) -> ApplyReport:
    """Create or top-up playlists. No writes unless do_apply is True."""
    selected = _select(suggestions, only_ids)
    if not selected:
        return ApplyReport(dry_run=not do_apply)

    report = ApplyReport(dry_run=not do_apply)
    if not do_apply:
        for suggestion in selected:
            report.actions.append(
                ApplyAction(
                    suggestion_id=suggestion.id,
                    name=suggestion.name,
                    playlist_id=None,
                    existed=False,
                    would_add=len(suggestion.track_uris),
                    already_present=0,
                )
            )
        report.refused = True
        raise ApplyRefused(APPLY_REFUSAL)

    for suggestion in selected:
        report.actions.append(
            _apply_one(client, suggestion, public=public)
        )
    return report


def _select(suggestions: list[Suggestion], only_ids: list[str] | None) -> list[Suggestion]:
    if not only_ids:
        return list(suggestions)
    wanted = {value.casefold() for value in only_ids}
    return [
        s
        for s in suggestions
        if s.id.casefold() in wanted or s.name.casefold() in wanted
    ]


def _apply_one(client, suggestion: Suggestion, *, public: bool) -> ApplyAction:
    existing = client.find_playlist_by_name(suggestion.name)
    description = suggestion.description[:PLAYLIST_DESCRIPTION_LIMIT]
    if existing:
        playlist_id = str(existing["id"])
        present = client.playlist_track_uris(playlist_id)
        missing = [uri for uri in suggestion.track_uris if uri and uri not in present]
        added = client.add_track_uris(playlist_id, missing) if missing else 0
        return ApplyAction(
            suggestion_id=suggestion.id,
            name=suggestion.name,
            playlist_id=playlist_id,
            existed=True,
            would_add=len(missing),
            already_present=len(present & set(suggestion.track_uris)),
            created=False,
            added=added,
        )

    created = client.create_playlist(suggestion.name, description, public=public)
    playlist_id = str(created["id"])
    uris = [uri for uri in suggestion.track_uris if uri]
    added = client.add_track_uris(playlist_id, uris) if uris else 0
    return ApplyAction(
        suggestion_id=suggestion.id,
        name=suggestion.name,
        playlist_id=playlist_id,
        existed=False,
        would_add=len(uris),
        already_present=0,
        created=True,
        added=added,
    )
