"""Ensure final submit is never automated; API returns 403; Gmail never sends."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.confirmations import clear_confirmations, create_confirmation
from app.gmail_client import create_gmail_draft, send_gmail_message
from app.main import app
from app.portal_adapter import PortalAdapter
from app.adapters.generic_portal import GenericPortalAdapter
from app.safety import SafetyError, clear_submit_locks
from app.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def _reset():
    clear_confirmations()
    clear_submit_locks()
    get_settings.cache_clear()
    yield
    clear_confirmations()
    clear_submit_locks()
    get_settings.cache_clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_final_submit_endpoint_403_by_default(client):
    r = client.post(
        "/final-submit",
        json={
            "manuscript_code": "MS-1",
            "journal_code": "example_journal",
            "package_hash": "abc",
            "confirmation_phrase": "CONFIRMO O ENVIO DO MANUSCRITO MS-1 AO PERIÓDICO X, USANDO O PACOTE abc",
        },
    )
    assert r.status_code == 403
    body = r.json()
    assert body.get("code") == "FINAL_SUBMIT_DISABLED" or "ALLOW_FINAL_SUBMISSION" in body.get("message", "")


def test_adapter_final_submit_refuses():
    adapter = GenericPortalAdapter(selectors_key="example_journal")

    async def _run():
        page = MagicMock()
        result = await adapter.final_submit(page)
        assert result.final_submitted is False
        assert result.success is False
        assert "FINAL_SUBMIT_DISABLED_ON_ADAPTER" in result.blockers

    import asyncio
    asyncio.run(_run())


def test_gmail_send_forbidden():
    with pytest.raises(SafetyError) as ei:
        send_gmail_message(to="x@y.com", subject="s", body="b")
    assert ei.value.code == "GMAIL_SEND_FORBIDDEN"


def test_gmail_draft_only_uses_create():
    service = MagicMock()
    service.users.return_value.drafts.return_value.create.return_value.execute.return_value = {
        "id": "draft1"
    }
    draft = create_gmail_draft(service, to="editor@journal.org", subject="Re: MS", body="Thanks")
    assert draft["id"] == "draft1"
    service.users.return_value.messages.return_value.send.assert_not_called()


def test_health_defaults(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["dry_run"] is True
    assert data["save_draft"] is True
    assert data["allow_final_submission"] is False


def test_safety_defaults_endpoint(client):
    r = client.get("/safety/defaults")
    assert r.status_code == 200
    data = r.json()
    assert data["defaults_safe"] is True
    assert data["account_separation_ok"] is True
    assert data["drive_email"] == "jp.criatividade@gmail.com"
    assert data["institutional_email"] == "joaopedro.passos@mail.uft.edu.br"


def test_drive_gmail_verify_email_helpers():
    from app.drive_client import verify_authenticated_google_account as drive_verify
    from app.gmail_client import verify_authenticated_google_account as gmail_verify

    email = drive_verify(about={"user": {"emailAddress": "jp.criatividade@gmail.com"}})
    assert email == "jp.criatividade@gmail.com"
    with pytest.raises(SafetyError):
        drive_verify(about={"user": {"emailAddress": "joaopedro.passos@mail.uft.edu.br"}})

    email2 = gmail_verify(profile={"emailAddress": "joaopedro.passos@mail.uft.edu.br"})
    assert email2 == "joaopedro.passos@mail.uft.edu.br"
    with pytest.raises(SafetyError):
        gmail_verify(profile={"emailAddress": "jp.criatividade@gmail.com"})


def test_mock_drive_list():
    from app.drive_client import list_drive_files

    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {
                "id": "1",
                "name": "paper.docx",
                "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "modifiedTime": "2026-01-01T00:00:00Z",
                "parents": ["root"],
            }
        ]
    }
    files = list_drive_files(service)
    assert len(files) == 1
    assert files[0].name == "paper.docx"


def test_prepare_draft_dry_run_skips_when_save_draft_false(tmp_path):
    """With dry_run and save_draft=False, portal is skipped and final_submitted stays false."""
    import asyncio
    import json
    from datetime import datetime

    from app.portal_runner import prepare_submission_draft
    from app.models import PackageManifest

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    manifest = PackageManifest(
        package_id="MS-DRY-example_journal",
        package_hash="hashdry",
        created_at=datetime.utcnow(),
        manuscript_code="MS-DRY",
        journal_code="example_journal",
        journal_name="Example Open Access Journal",
        files={"identified": "a.docx"},
        author_order=["João Pedro Pereira Passos"],
        corresponding_email="joaopedro.passos@mail.uft.edu.br",
        dry_run=True,
    )
    (pkg / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    (pkg / "a.docx").write_bytes(b"PK fake")

    s = Settings(dry_run=True, save_draft=False, allow_final_submission=False)

    async def _run():
        result = await prepare_submission_draft(
            manuscript_code="MS-DRY",
            journal_code="example_journal",
            package_dir=pkg,
            settings=s,
        )
        assert result.final_submitted is False
        assert result.success is True

    asyncio.run(_run())
