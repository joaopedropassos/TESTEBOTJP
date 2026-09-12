"""Security cases for safety.py guards (cases 1–11, 16–18)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.audit import redact_secrets
from app.models import AuthorConfig, AuthorEntry
from app.safety import (
    SafetyError,
    acquire_submit_lock,
    assert_final_submission_allowed,
    assert_no_auto_reorder,
    clear_submit_locks,
    create_final_auth_file,
    defaults_are_safe,
    detect_fee_or_contract,
    package_hash_from_bytes,
    preserve_author_order,
    release_submit_lock,
    require_final_auth_file,
    stop_on_fee_or_contract,
    validate_author_config,
    verify_account_separation,
)
from app.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_locks():
    clear_submit_locks()
    get_settings.cache_clear()
    yield
    clear_submit_locks()
    get_settings.cache_clear()


def test_01_defaults_are_safe():
    """Cases 1–3: DRY_RUN=true, SAVE_DRAFT=true, ALLOW_FINAL_SUBMISSION=false."""
    s = get_settings()
    assert s.dry_run is True
    assert s.save_draft is True
    assert s.allow_final_submission is False
    assert defaults_are_safe(s) is True


def test_04_account_separation_ok():
    """Case 4: Drive and institutional accounts distinct and correct."""
    verify_account_separation(get_settings())


def test_05_drive_email_mismatch():
    """Case 5: wrong Drive email raises."""
    s = Settings(
        drive_email="wrong@gmail.com",
        google_drive_client_secrets=Path("/tmp/drive_client.json"),
        google_gmail_client_secrets=Path("/tmp/gmail_client.json"),
        google_drive_token=Path("/tmp/drive_token.json"),
        google_gmail_token=Path("/tmp/gmail_token.json"),
    )
    with pytest.raises(SafetyError) as ei:
        verify_account_separation(s)
    assert ei.value.code in {"DRIVE_EMAIL_MISMATCH", "ACCOUNT_MIX"}


def test_06_institutional_email_mismatch():
    """Case 6: wrong institutional email raises."""
    s = Settings(
        institutional_email="other@mail.uft.edu.br",
        gmail_email="other@mail.uft.edu.br",
        google_drive_client_secrets=Path("/tmp/drive_client.json"),
        google_gmail_client_secrets=Path("/tmp/gmail_client.json"),
        google_drive_token=Path("/tmp/drive_token.json"),
        google_gmail_token=Path("/tmp/gmail_token.json"),
    )
    with pytest.raises(SafetyError) as ei:
        verify_account_separation(s)
    assert "MISMATCH" in ei.value.code or ei.value.code == "ACCOUNT_MIX"


def test_07_oauth_client_mix_blocked(tmp_path):
    """Case 7: same OAuth client secrets file blocked."""
    shared = tmp_path / "shared.json"
    shared.write_text("{}")
    s = Settings(
        google_drive_client_secrets=shared,
        google_gmail_client_secrets=shared,
        google_drive_token=tmp_path / "drive_token.json",
        google_gmail_token=tmp_path / "gmail_token.json",
    )
    with pytest.raises(SafetyError) as ei:
        verify_account_separation(s)
    assert ei.value.code == "OAUTH_CLIENT_MIX"


def test_08_oauth_token_mix_blocked(tmp_path):
    """Case 8: same OAuth token file blocked."""
    shared = tmp_path / "shared_token.json"
    shared.write_text("{}")
    s = Settings(
        google_drive_client_secrets=tmp_path / "drive_client.json",
        google_gmail_client_secrets=tmp_path / "gmail_client.json",
        google_drive_token=shared,
        google_gmail_token=shared,
    )
    with pytest.raises(SafetyError) as ei:
        verify_account_separation(s)
    assert ei.value.code == "OAUTH_TOKEN_MIX"


def test_09_scope_mix_blocked(tmp_path):
    """Case 9: Drive scopes must not include Gmail."""
    s = Settings(
        google_drive_client_secrets=tmp_path / "drive_client.json",
        google_gmail_client_secrets=tmp_path / "gmail_client.json",
        google_drive_token=tmp_path / "drive_token.json",
        google_gmail_token=tmp_path / "gmail_token.json",
        google_drive_scopes="https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/gmail.readonly",
    )
    with pytest.raises(SafetyError) as ei:
        verify_account_separation(s)
    assert ei.value.code == "SCOPE_MIX"


def test_10_final_submit_disabled():
    """Case 10: ALLOW_FINAL_SUBMISSION=false blocks final submit."""
    s = Settings(allow_final_submission=False, dry_run=False)
    with pytest.raises(SafetyError) as ei:
        assert_final_submission_allowed(s)
    assert ei.value.code == "FINAL_SUBMIT_DISABLED"


def test_11_dry_run_blocks_final():
    """Case 11: DRY_RUN=true blocks final submit even if allow flag true."""
    s = Settings(allow_final_submission=True, dry_run=True)
    with pytest.raises(SafetyError) as ei:
        assert_final_submission_allowed(s)
    assert ei.value.code == "DRY_RUN_BLOCKS_FINAL"


def test_12_final_auth_file_hash(tmp_path):
    """Case 12: temp auth file must contain matching package hash."""
    s = Settings(final_auth_dir=tmp_path, final_auth_prefix="article_bot_final_auth_")
    package_hash = package_hash_from_bytes(b"pkg")
    path = create_final_auth_file(package_hash, settings=s)
    assert require_final_auth_file(package_hash, path, settings=s) == path
    with pytest.raises(SafetyError) as ei:
        require_final_auth_file("otherhash", path, settings=s)
    assert ei.value.code == "FINAL_AUTH_HASH_MISMATCH"


def test_16_simultaneous_submit_blocked():
    """Case 16: simultaneous submissions blocked."""
    s = Settings(block_simultaneous_submit=True)
    acquire_submit_lock("A:J", settings=s)
    with pytest.raises(SafetyError) as ei:
        acquire_submit_lock("B:J", settings=s)
    assert ei.value.code == "SIMULTANEOUS_SUBMIT"
    release_submit_lock("A:J")
    acquire_submit_lock("B:J", settings=s)
    release_submit_lock("B:J")


def test_17_fee_or_contract_stop():
    """Case 17: fee/contract keywords stop automation."""
    text = "An Article Processing Charge (APC) of USD 2000 is required."
    stop, hits = detect_fee_or_contract(text)
    assert stop is True
    assert hits
    with pytest.raises(SafetyError) as ei:
        stop_on_fee_or_contract(text)
    assert ei.value.code == "FEE_OR_CONTRACT"


def test_18_author_order_preserved():
    """Case 18: authorship order preserved; no auto-reorder."""
    authors = [
        AuthorEntry(full_name="Alice", order=2, corresponding=False),
        AuthorEntry(full_name="João Pedro Pereira Passos", order=1, corresponding=True,
                    email="joaopedro.passos@mail.uft.edu.br"),
        AuthorEntry(full_name="Carol", order=3, corresponding=False),
    ]
    ordered = preserve_author_order(authors)
    names = [a.full_name for a in ordered]
    assert names == [
        "João Pedro Pereira Passos",
        "Alice",
        "Carol",
    ]
    # Declared order list (by order field) must match preserve output
    declared = [a.full_name for a in sorted(authors, key=lambda x: x.order)]
    assert_no_auto_reorder(declared, names)
    with pytest.raises(SafetyError):
        assert_no_auto_reorder(declared, list(reversed(names)))


def test_secret_redaction():
    """Secrets redacted from audit payloads."""
    payload = {
        "password": "supersecret",
        "token": "ya29.abc",
        "nested": {"client_secret": "xyz", "ok": "value"},
        "note": "Authorization: Bearer abcdef123",
    }
    red = redact_secrets(payload)
    assert red["password"] == "[REDACTED]"
    assert red["token"] == "[REDACTED]"
    assert red["nested"]["client_secret"] == "[REDACTED]"
    assert red["nested"]["ok"] == "value"
    assert "[REDACTED]" in red["note"]


def test_validate_author_config_ok():
    cfg = AuthorConfig(
        full_name="João Pedro Pereira Passos",
        publication_name="João Pedro Pereira Passos",
        corresponding_email="joaopedro.passos@mail.uft.edu.br",
        country="Brasil",
        authors=[
            AuthorEntry(
                full_name="João Pedro Pereira Passos",
                email="joaopedro.passos@mail.uft.edu.br",
                corresponding=True,
                order=1,
            )
        ],
    )
    gaps = validate_author_config(cfg)
    assert any(g.startswith("optional_empty:") for g in gaps)
