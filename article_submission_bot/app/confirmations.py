"""Interactive confirmation phrases for final manuscript submission."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from app.audit import audit
from app.models import ConfirmationRecord
from app.safety import SafetyError, create_final_auth_file
from app.settings import Settings, get_settings

PHRASE_TEMPLATE = (
    "CONFIRMO O ENVIO DO MANUSCRITO {code} AO PERIÓDICO {name}, USANDO O PACOTE {hash}"
)

PHRASE_RE = re.compile(
    r"^CONFIRMO O ENVIO DO MANUSCRITO\s+(?P<code>.+?)\s+AO PERIÓDICO\s+(?P<name>.+?),"
    r"\s+USANDO O PACOTE\s+(?P<hash>[a-fA-F0-9]+)\s*$"
)

# In-memory store (also mirrored optionally to DB by callers)
_confirmations: dict[str, ConfirmationRecord] = {}


def build_confirmation_phrase(manuscript_code: str, journal_name: str, package_hash: str) -> str:
    return PHRASE_TEMPLATE.format(
        code=manuscript_code.strip(),
        name=journal_name.strip(),
        hash=package_hash.strip(),
    )


def parse_confirmation_phrase(phrase: str) -> dict:
    m = PHRASE_RE.match((phrase or "").strip())
    if not m:
        raise SafetyError(
            "Confirmation phrase does not match required template",
            code="INVALID_CONFIRMATION_PHRASE",
        )
    return {
        "manuscript_code": m.group("code").strip(),
        "journal_name": m.group("name").strip(),
        "package_hash": m.group("hash").strip().lower(),
    }


def create_confirmation(
    manuscript_code: str,
    journal_name: str,
    package_hash: str,
    *,
    settings: Optional[Settings] = None,
    write_auth_file: bool = True,
) -> ConfirmationRecord:
    settings = settings or get_settings()
    phrase = build_confirmation_phrase(manuscript_code, journal_name, package_hash)
    now = datetime.utcnow()
    expires = now + timedelta(seconds=settings.confirmation_ttl_seconds)
    auth_path: Optional[str] = None
    if write_auth_file:
        auth_path = str(create_final_auth_file(package_hash, settings=settings))

    record = ConfirmationRecord(
        phrase=phrase,
        manuscript_code=manuscript_code,
        journal_name=journal_name,
        package_hash=package_hash.lower(),
        created_at=now,
        expires_at=expires,
        used=False,
        auth_file=auth_path,
    )
    _confirmations[package_hash.lower()] = record
    audit(
        "confirmation_created",
        manuscript_code=manuscript_code,
        package_hash=package_hash,
        details={"journal_name": journal_name, "expires_at": expires.isoformat()},
        message="Confirmation phrase issued",
    )
    return record


def invalidate_confirmation(package_hash: str) -> None:
    key = package_hash.lower()
    if key in _confirmations:
        del _confirmations[key]
        audit(
            "confirmation_invalidated",
            package_hash=package_hash,
            message="Confirmation invalidated (hash change or explicit)",
        )


def invalidate_on_hash_change(old_hash: str, new_hash: str) -> None:
    if old_hash.lower() != new_hash.lower():
        invalidate_confirmation(old_hash)


def get_confirmation(package_hash: str) -> Optional[ConfirmationRecord]:
    return _confirmations.get(package_hash.lower())


def validate_confirmation(
    phrase: str,
    *,
    manuscript_code: str,
    journal_name: str,
    package_hash: str,
    settings: Optional[Settings] = None,
    mark_used: bool = True,
) -> ConfirmationRecord:
    """Validate interactive confirmation phrase + TTL + hash match."""
    settings = settings or get_settings()
    parsed = parse_confirmation_phrase(phrase)

    if parsed["manuscript_code"] != manuscript_code:
        raise SafetyError("Confirmation manuscript code mismatch", code="CONFIRM_CODE_MISMATCH")
    if parsed["journal_name"] != journal_name:
        raise SafetyError("Confirmation journal name mismatch", code="CONFIRM_JOURNAL_MISMATCH")
    if parsed["package_hash"] != package_hash.lower():
        raise SafetyError("Confirmation package hash mismatch", code="CONFIRM_HASH_MISMATCH")

    expected = build_confirmation_phrase(manuscript_code, journal_name, package_hash)
    if phrase.strip() != expected:
        # Allow case-insensitive hash already handled; phrase must otherwise match exactly
        if phrase.strip().upper() != expected.upper():
            raise SafetyError("Confirmation phrase mismatch", code="CONFIRM_PHRASE_MISMATCH")

    record = get_confirmation(package_hash)
    now = datetime.utcnow()
    if record is None:
        # Accept ephemeral validation if phrase is correct (still require TTL via create)
        # For safety, require a previously issued confirmation within TTL.
        raise SafetyError(
            "No active confirmation for this package hash — request a new confirmation",
            code="CONFIRM_NOT_FOUND",
        )
    if record.used:
        raise SafetyError("Confirmation already used", code="CONFIRM_ALREADY_USED")
    if now > record.expires_at:
        invalidate_confirmation(package_hash)
        raise SafetyError("Confirmation expired (TTL)", code="CONFIRM_EXPIRED")
    if record.package_hash != package_hash.lower():
        raise SafetyError("Stored confirmation hash mismatch", code="CONFIRM_HASH_MISMATCH")

    if mark_used:
        record.used = True
        _confirmations[package_hash.lower()] = record

    audit(
        "confirmation_validated",
        manuscript_code=manuscript_code,
        package_hash=package_hash,
        details={"journal_name": journal_name},
        message="Confirmation validated",
    )
    return record


def clear_confirmations() -> None:
    _confirmations.clear()


def auth_file_still_valid(package_hash: str, auth_file: Path) -> bool:
    if not auth_file.is_file():
        return False
    return auth_file.read_text(encoding="utf-8").strip() == package_hash
