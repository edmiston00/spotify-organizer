from __future__ import annotations

import json
from pathlib import Path

from tests.factories import diverse_library

from spotify_organizer.cli import main
from spotify_organizer.models import library_to_dict
from spotify_organizer.reports import write_reports
from spotify_organizer.suggest import discover_suggestions


def test_analyze_from_library_json(tmp_path: Path, capsys):
    library = diverse_library()
    snapshot = tmp_path / "library.json"
    snapshot.write_text(json.dumps(library_to_dict(library)), encoding="utf-8")
    out = tmp_path / "reports"

    code = main(
        [
            "analyze",
            "--library-json",
            str(snapshot),
            "--output-dir",
            str(out),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "dry-run" in captured.out.lower()
    assert (out / "suggestions.json").exists()
    assert (out / "suggestions.csv").exists()
    payload = json.loads((out / "suggestions.json").read_text(encoding="utf-8"))
    assert payload["dry_run"] is True
    assert 5 <= len(payload["suggestions"]) <= 10
    first = payload["suggestions"][0]
    assert first["name"]
    assert first["description"]
    assert first["approx_track_count"]
    assert first["sample_tracks"]
    assert first["rationale"]


def test_apply_without_flag_refuses(tmp_path: Path, capsys):
    library = diverse_library()
    suggestions = discover_suggestions(library)
    report_dir = tmp_path / "reports"
    write_reports(library, suggestions, report_dir, dry_run=True)

    code = main(["apply", "--suggestions", str(report_dir / "suggestions.json")])
    captured = capsys.readouterr()
    assert code == 2
    assert "--apply" in captured.err or "--apply" in captured.out
    assert "Refusing" in captured.err or "Refusing" in captured.out


def test_apply_paste_auth_without_flag_still_refuses(tmp_path: Path, capsys, monkeypatch):
    library = diverse_library()
    suggestions = discover_suggestions(library)
    report_dir = tmp_path / "reports"
    write_reports(library, suggestions, report_dir, dry_run=True)

    monkeypatch.setattr(
        "spotify_organizer.cli._client",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not auth")),
    )
    code = main(
        [
            "apply",
            "--paste-auth",
            "--suggestions",
            str(report_dir / "suggestions.json"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "Refusing" in captured.err or "Refusing" in captured.out


def test_default_command_is_analyze(tmp_path: Path):
    library = diverse_library()
    snapshot = tmp_path / "library.json"
    snapshot.write_text(json.dumps(library_to_dict(library)), encoding="utf-8")
    out = tmp_path / "out"
    code = main(["--library-json", str(snapshot), "--output-dir", str(out)])
    assert code == 0
    assert (out / "suggestions.json").exists()
