#!/usr/bin/env python3
"""
Verify local environment WITHOUT requiring live Google credentials.

Checks: Python version, imports, configs, safety defaults, directory layout,
author identity rules, and that final-submit gates are in place.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


REQUIRED_MODULES = [
    "fastapi",
    "pydantic",
    "pydantic_settings",
    "sqlalchemy",
    "yaml",
    "structlog",
    "docx",
    "pypdf",
    "playwright",
]

REQUIRED_PATHS = [
    "README.md",
    "pyproject.toml",
    ".env.example",
    ".gitignore",
    "config/author.yaml",
    "config/journals.example.yaml",
    "config/selectors.example.yaml",
    "app/main.py",
    "app/settings.py",
    "app/safety.py",
    "app/confirmations.py",
    "app/drive_client.py",
    "app/gmail_client.py",
    "app/portal_runner.py",
    "app/adapters/generic_portal.py",
    "scripts/verify_environment.py",
    "tests/test_safety.py",
    "data/originals/.gitkeep",
    "data/packages/.gitkeep",
    "storage/.gitkeep",
]


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def main() -> int:
    print("=== article_submission_bot environment verification ===")
    print("(Works WITHOUT live Google credentials)\n")
    errors = 0

    # Python version
    if sys.version_info >= (3, 11):
        ok(f"Python {sys.version.split()[0]} >= 3.11")
    else:
        fail(f"Python {sys.version} < 3.11")
        errors += 1

    # Paths
    print("\n-- Project layout --")
    for rel in REQUIRED_PATHS:
        p = ROOT / rel
        if p.exists():
            ok(rel)
        else:
            fail(f"missing: {rel}")
            errors += 1

    # Imports
    print("\n-- Dependencies --")
    for mod in REQUIRED_MODULES:
        try:
            importlib.import_module(mod)
            ok(mod)
        except Exception as exc:
            fail(f"{mod}: {exc}")
            errors += 1

    # Optional Google libs (present but no live call)
    print("\n-- Google client libraries (no live auth) --")
    for mod in ("google.oauth2.credentials", "google_auth_oauthlib.flow", "googleapiclient.discovery"):
        try:
            importlib.import_module(mod)
            ok(mod)
        except Exception as exc:
            fail(f"{mod}: {exc}")
            errors += 1

    # Settings & safety defaults
    print("\n-- Safety defaults --")
    try:
        from app.settings import get_settings
        from app.safety import (
            EXPECTED_CORRESPONDING,
            EXPECTED_DRIVE,
            defaults_are_safe,
            verify_account_separation,
        )
        from app.package_builder import load_author_config
        from app.safety import validate_author_config

        # Clear lru cache in case env polluted
        get_settings.cache_clear()
        settings = get_settings()
        if defaults_are_safe(settings):
            ok("DRY_RUN=true, SAVE_DRAFT=true, ALLOW_FINAL_SUBMISSION=false")
        else:
            fail(
                f"Unsafe defaults: dry_run={settings.dry_run} "
                f"save_draft={settings.save_draft} "
                f"allow_final={settings.allow_final_submission}"
            )
            errors += 1

        verify_account_separation(settings)
        ok(f"Account separation: Drive={EXPECTED_DRIVE} / Inst={EXPECTED_CORRESPONDING}")

        author = load_author_config()
        gaps = validate_author_config(author)
        ok(f"Author config valid ({len(gaps)} empty optional fields noted)")
        if str(author.corresponding_email) != EXPECTED_CORRESPONDING:
            fail("corresponding_email mismatch")
            errors += 1
        else:
            ok(f"corresponding_email={author.corresponding_email}")
    except Exception as exc:
        fail(f"settings/safety: {exc}")
        errors += 1

    # Confirm phrase template
    print("\n-- Confirmation phrase --")
    try:
        from app.confirmations import build_confirmation_phrase, PHRASE_TEMPLATE

        phrase = build_confirmation_phrase("MS-001", "Example Journal", "abc123")
        if "CONFIRMO O ENVIO DO MANUSCRITO" in phrase and "USANDO O PACOTE" in phrase:
            ok(phrase)
        else:
            fail(f"Unexpected phrase: {phrase}")
            errors += 1
        if "CONFIRMO O ENVIO" not in PHRASE_TEMPLATE:
            fail("PHRASE_TEMPLATE broken")
            errors += 1
    except Exception as exc:
        fail(str(exc))
        errors += 1

    # Final-submit endpoint exists and defaults block
    print("\n-- API gates --")
    try:
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["allow_final_submission"] is False
        ok("/health reports allow_final_submission=false")

        r2 = client.post(
            "/final-submit",
            json={
                "manuscript_code": "X",
                "journal_code": "example_journal",
                "package_hash": "deadbeef",
                "confirmation_phrase": "nope",
            },
        )
        if r2.status_code == 403:
            ok("/final-submit returns 403 when ALLOW_FINAL_SUBMISSION=false")
        else:
            fail(f"/final-submit status {r2.status_code}")
            errors += 1
    except Exception as exc:
        fail(f"API gate check: {exc}")
        errors += 1

    # Secrets not required
    print("\n-- Credentials (optional) --")
    drive_secrets = ROOT / "secrets" / "drive_client_secrets.json"
    gmail_secrets = ROOT / "secrets" / "gmail_client_secrets.json"
    if drive_secrets.is_file():
        ok("drive_client_secrets.json present (optional)")
    else:
        ok("drive_client_secrets.json absent — OK for offline verify")
    if gmail_secrets.is_file():
        ok("gmail_client_secrets.json present (optional)")
    else:
        ok("gmail_client_secrets.json absent — OK for offline verify")

    print("\n=== RESULT ===")
    if errors == 0:
        print("GREEN — environment verified (no live Google creds required)")
        return 0
    print(f"RED — {errors} error(s)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
