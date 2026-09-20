from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spotify_organizer.models import Library, Suggestion, library_from_dict, library_to_dict


def write_reports(
    library: Library,
    suggestions: list[Suggestion],
    output_dir: Path,
    *,
    dry_run: bool = True,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "library_track_count": library.track_count,
        "dry_run": dry_run,
        "suggestions": [s.to_public_dict() for s in suggestions],
    }

    json_path = output_dir / "suggestions.json"
    csv_path = output_dir / "suggestions.csv"
    library_path = output_dir / "library.json"

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    library_path.write_text(json.dumps(library_to_dict(library), indent=2), encoding="utf-8")
    _write_csv(csv_path, suggestions)

    return {"json": json_path, "csv": csv_path, "library": library_path}


def _write_csv(path: Path, suggestions: list[Suggestion]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "name",
                "description",
                "approx_track_count",
                "sample_tracks",
                "rationale",
                "kind",
            ],
        )
        writer.writeheader()
        for suggestion in suggestions:
            writer.writerow(
                {
                    "id": suggestion.id,
                    "name": suggestion.name,
                    "description": suggestion.description,
                    "approx_track_count": suggestion.approx_track_count,
                    "sample_tracks": " | ".join(suggestion.sample_tracks),
                    "rationale": suggestion.rationale,
                    "kind": suggestion.kind,
                }
            )


def load_suggestions(path: Path) -> list[Suggestion]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return suggestions_from_payload(data)


def suggestions_from_payload(data: dict[str, Any]) -> list[Suggestion]:
    out: list[Suggestion] = []
    for raw in data.get("suggestions") or []:
        out.append(
            Suggestion(
                id=str(raw.get("id") or ""),
                name=str(raw.get("name") or ""),
                description=str(raw.get("description") or ""),
                approx_track_count=int(raw.get("approx_track_count") or 0),
                sample_tracks=list(raw.get("sample_tracks") or []),
                rationale=str(raw.get("rationale") or ""),
                track_uris=list(raw.get("track_uris") or []),
                kind=str(raw.get("kind") or ""),
            )
        )
    return out


def load_library(path: Path) -> Library:
    return library_from_dict(json.loads(path.read_text(encoding="utf-8")))
