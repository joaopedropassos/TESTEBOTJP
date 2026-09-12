"""Confirmation phrase, TTL, and hash-invalidation tests (cases 13–15)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.confirmations import (
    build_confirmation_phrase,
    clear_confirmations,
    create_confirmation,
    get_confirmation,
    invalidate_on_hash_change,
    parse_confirmation_phrase,
    validate_confirmation,
)
from app.safety import SafetyError
from app.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def _reset():
    clear_confirmations()
    get_settings.cache_clear()
    yield
    clear_confirmations()
    get_settings.cache_clear()


def test_13_confirmation_phrase_format():
    """Case 13: exact confirmation phrase template."""
    phrase = build_confirmation_phrase("MS-42", "Example Open Access Journal", "deadbeef")
    assert phrase == (
        "CONFIRMO O ENVIO DO MANUSCRITO MS-42 AO PERIÓDICO Example Open Access Journal, "
        "USANDO O PACOTE deadbeef"
    )
    parsed = parse_confirmation_phrase(phrase)
    assert parsed["manuscript_code"] == "MS-42"
    assert parsed["journal_name"] == "Example Open Access Journal"
    assert parsed["package_hash"] == "deadbeef"


def test_13b_invalid_phrase():
    with pytest.raises(SafetyError) as ei:
        parse_confirmation_phrase("eu confirmo o envio")
    assert ei.value.code == "INVALID_CONFIRMATION_PHRASE"


def test_14_confirmation_ttl_expiry(tmp_path):
    """Case 14: confirmation expires after TTL."""
    s = Settings(confirmation_ttl_seconds=1, final_auth_dir=tmp_path)
    record = create_confirmation("MS-1", "Example Open Access Journal", "abc123", settings=s)
    # Force expiry
    record.expires_at = datetime.utcnow() - timedelta(seconds=5)
    from app import confirmations as mod

    mod._confirmations["abc123"] = record
    phrase = build_confirmation_phrase("MS-1", "Example Open Access Journal", "abc123")
    with pytest.raises(SafetyError) as ei:
        validate_confirmation(
            phrase,
            manuscript_code="MS-1",
            journal_name="Example Open Access Journal",
            package_hash="abc123",
            settings=s,
        )
    assert ei.value.code == "CONFIRM_EXPIRED"


def test_15_invalidate_on_hash_change(tmp_path):
    """Case 15: hash change invalidates confirmation."""
    s = Settings(final_auth_dir=tmp_path)
    create_confirmation("MS-1", "Example Open Access Journal", "hash_old", settings=s)
    assert get_confirmation("hash_old") is not None
    invalidate_on_hash_change("hash_old", "hash_new")
    assert get_confirmation("hash_old") is None


def test_confirmation_valid_flow(tmp_path):
    s = Settings(confirmation_ttl_seconds=900, final_auth_dir=tmp_path)
    record = create_confirmation("MS-9", "Example Open Access Journal", "ff00aa", settings=s)
    assert Path(record.auth_file).is_file()
    assert Path(record.auth_file).read_text().strip() == "ff00aa"
    phrase = record.phrase
    validated = validate_confirmation(
        phrase,
        manuscript_code="MS-9",
        journal_name="Example Open Access Journal",
        package_hash="ff00aa",
        settings=s,
    )
    assert validated.used is True
    with pytest.raises(SafetyError) as ei:
        validate_confirmation(
            phrase,
            manuscript_code="MS-9",
            journal_name="Example Open Access Journal",
            package_hash="ff00aa",
            settings=s,
        )
    assert ei.value.code == "CONFIRM_ALREADY_USED"
