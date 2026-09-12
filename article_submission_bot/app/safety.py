"""Safety guards: account separation, final-submit locks, authorship order, fee/contract stops."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.audit import audit, redact_secrets
from app.models import AuthorConfig, AuthorEntry
from app.settings import Settings, get_settings

# Expected hard identity rules
EXPECTED_CORRESPONDING = "joaopedro.passos@mail.uft.edu.br"
EXPECTED_DRIVE = "jp.criatividade@gmail.com"
EXPECTED_AUTHOR_NAME = "João Pedro Pereira Passos"

# In-process simultaneous submit lock
_submit_lock = threading.Lock()
_active_submits: set[str] = set()


class SafetyError(Exception):
    """Raised when a safety policy is violated."""

    def __init__(self, message: str, code: str = "SAFETY_VIOLATION"):
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def verify_account_separation(settings: Optional[Settings] = None) -> None:
    """Ensure Drive and institutional/Gmail accounts are distinct and correct."""
    settings = settings or get_settings()
    inst = normalize_email(settings.institutional_email)
    drive = normalize_email(settings.drive_email)
    gmail = normalize_email(settings.gmail_email)

    if drive == inst:
        raise SafetyError(
            "Drive email must not equal institutional/corresponding email",
            code="ACCOUNT_MIX",
        )
    if drive != normalize_email(EXPECTED_DRIVE):
        raise SafetyError(
            f"Drive email must be {EXPECTED_DRIVE}, got {settings.drive_email}",
            code="DRIVE_EMAIL_MISMATCH",
        )
    if inst != normalize_email(EXPECTED_CORRESPONDING):
        raise SafetyError(
            f"Institutional email must be {EXPECTED_CORRESPONDING}",
            code="INSTITUTIONAL_EMAIL_MISMATCH",
        )
    if gmail != normalize_email(EXPECTED_CORRESPONDING):
        raise SafetyError(
            f"Gmail (editorial) email must be {EXPECTED_CORRESPONDING}",
            code="GMAIL_EMAIL_MISMATCH",
        )

    # Token / client secrets paths must differ
    if settings.google_drive_client_secrets.resolve() == settings.google_gmail_client_secrets.resolve():
        raise SafetyError(
            "Drive and Gmail OAuth client secrets must be separate files",
            code="OAUTH_CLIENT_MIX",
        )
    if settings.google_drive_token.resolve() == settings.google_gmail_token.resolve():
        raise SafetyError(
            "Drive and Gmail OAuth tokens must be separate files",
            code="OAUTH_TOKEN_MIX",
        )

    # Scopes must not overlap incorrectly (Drive must not have gmail scopes and vice-versa)
    drive_scopes = set(settings.drive_scopes_list())
    gmail_scopes = set(settings.gmail_scopes_list())
    if any("gmail" in s for s in drive_scopes):
        raise SafetyError("Drive scopes must not include Gmail scopes", code="SCOPE_MIX")
    if any("drive" in s for s in gmail_scopes):
        raise SafetyError("Gmail scopes must not include Drive scopes", code="SCOPE_MIX")


def verify_authenticated_email(actual: str, expected: str, service: str) -> None:
    if normalize_email(actual) != normalize_email(expected):
        raise SafetyError(
            f"{service} authenticated as {actual!r}, expected {expected!r}",
            code=f"{service.upper()}_ACCOUNT_MISMATCH",
        )


def assert_final_submission_allowed(settings: Optional[Settings] = None) -> None:
    settings = settings or get_settings()
    if not settings.allow_final_submission:
        raise SafetyError(
            "ALLOW_FINAL_SUBMISSION is false — final submit blocked",
            code="FINAL_SUBMIT_DISABLED",
        )
    if settings.dry_run:
        raise SafetyError(
            "DRY_RUN is true — final submit blocked",
            code="DRY_RUN_BLOCKS_FINAL",
        )


def require_final_auth_file(package_hash: str, auth_file: Optional[Path] = None,
                            settings: Optional[Settings] = None) -> Path:
    """Require a temp auth file whose content matches the package hash."""
    settings = settings or get_settings()
    if auth_file is None:
        candidates = sorted(
            settings.final_auth_dir.glob(f"{settings.final_auth_prefix}*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise SafetyError(
                "No temporary final-auth file found — create one with the package hash",
                code="MISSING_FINAL_AUTH",
            )
        auth_file = candidates[0]

    auth_file = Path(auth_file)
    if not auth_file.is_file():
        raise SafetyError(f"Final auth file not found: {auth_file}", code="MISSING_FINAL_AUTH")

    content = auth_file.read_text(encoding="utf-8").strip()
    if content != package_hash:
        raise SafetyError(
            "Final auth file package hash does not match submission package",
            code="FINAL_AUTH_HASH_MISMATCH",
        )
    return auth_file


def create_final_auth_file(package_hash: str, settings: Optional[Settings] = None) -> Path:
    settings = settings or get_settings()
    settings.final_auth_dir.mkdir(parents=True, exist_ok=True)
    path = settings.final_auth_dir / f"{settings.final_auth_prefix}{package_hash[:16]}"
    path.write_text(package_hash, encoding="utf-8")
    return path


def acquire_submit_lock(key: str, settings: Optional[Settings] = None) -> None:
    settings = settings or get_settings()
    if not settings.block_simultaneous_submit:
        return
    with _submit_lock:
        if key in _active_submits:
            raise SafetyError(
                f"Simultaneous submission blocked for {key}",
                code="SIMULTANEOUS_SUBMIT",
            )
        if _active_submits:
            raise SafetyError(
                "Another submission is already in progress",
                code="SIMULTANEOUS_SUBMIT",
            )
        _active_submits.add(key)


def release_submit_lock(key: str) -> None:
    with _submit_lock:
        _active_submits.discard(key)


def clear_submit_locks() -> None:
    with _submit_lock:
        _active_submits.clear()


def detect_fee_or_contract(
    page_text: str,
    fee_keywords: Optional[Sequence[str]] = None,
    contract_keywords: Optional[Sequence[str]] = None,
) -> Tuple[bool, List[str]]:
    """Return (should_stop, matched_keywords)."""
    text = (page_text or "").lower()
    fee_keywords = fee_keywords or [
        "article processing charge",
        "apc",
        "publication fee",
        "payment required",
        "pay to publish",
    ]
    contract_keywords = contract_keywords or [
        "copyright transfer",
        "exclusive license",
        "terms of agreement",
        "assign copyright",
    ]
    hits: List[str] = []
    for kw in list(fee_keywords) + list(contract_keywords):
        if kw.lower() in text:
            hits.append(kw)
    return (len(hits) > 0, hits)


def stop_on_fee_or_contract(
    page_text: str,
    fee_keywords: Optional[Sequence[str]] = None,
    contract_keywords: Optional[Sequence[str]] = None,
) -> None:
    should_stop, hits = detect_fee_or_contract(page_text, fee_keywords, contract_keywords)
    if should_stop:
        audit(
            "fee_or_contract_stop",
            success=False,
            message="Stopped due to fee/contract indicators",
            details={"hits": hits},
        )
        raise SafetyError(
            f"Fee or contract indicators detected — human intervention required: {hits}",
            code="FEE_OR_CONTRACT",
        )


def preserve_author_order(authors: Sequence[AuthorEntry]) -> List[AuthorEntry]:
    """Return authors in their declared order; never auto-reorder."""
    # Stable sort by explicit order field only (user-declared). Do not invent order.
    return sorted(list(authors), key=lambda a: a.order)


def validate_author_config(config: AuthorConfig) -> List[str]:
    """Validate author config. Never invent missing fields. Return list of gaps."""
    gaps: List[str] = []
    if config.full_name != EXPECTED_AUTHOR_NAME:
        raise SafetyError(
            f"Author full_name must be {EXPECTED_AUTHOR_NAME!r}",
            code="AUTHOR_NAME_MISMATCH",
        )
    if config.publication_name != EXPECTED_AUTHOR_NAME:
        raise SafetyError(
            f"publication_name must be {EXPECTED_AUTHOR_NAME!r}",
            code="AUTHOR_NAME_MISMATCH",
        )
    if normalize_email(str(config.corresponding_email)) != normalize_email(EXPECTED_CORRESPONDING):
        raise SafetyError(
            f"corresponding_email must be {EXPECTED_CORRESPONDING}",
            code="CORRESPONDING_EMAIL_MISMATCH",
        )

    corresponding = [a for a in config.authors if a.corresponding]
    if not corresponding:
        gaps.append("No corresponding author marked in authors list")
    else:
        for a in corresponding:
            if normalize_email(a.email) != normalize_email(EXPECTED_CORRESPONDING):
                raise SafetyError(
                    "Corresponding author email must be institutional UFT address",
                    code="CORRESPONDING_EMAIL_MISMATCH",
                )

    # Empty optional fields are OK — never invent
    optional = [
        "institution",
        "orcid",
        "affiliation",
        "department",
        "phone",
        "address",
        "city",
        "state",
        "postal_code",
    ]
    for field in optional:
        val = getattr(config, field, "")
        if not val:
            gaps.append(f"optional_empty:{field}")

    # Ensure order is preserved / not mutated unexpectedly
    orders = [a.order for a in config.authors]
    if orders != sorted(orders):
        # Not an error — we preserve as declared via preserve_author_order
        pass

    return gaps


def assert_no_auto_reorder(
    original: Sequence[str],
    result: Sequence[str],
) -> None:
    if list(original) != list(result):
        raise SafetyError(
            "Authorship order was altered — auto-reorder is forbidden",
            code="AUTHOR_ORDER_CHANGED",
        )


def package_hash_from_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package_hash_from_files(files: Iterable[Path]) -> str:
    h = hashlib.sha256()
    for path in sorted(files, key=lambda p: str(p)):
        p = Path(path)
        h.update(p.name.encode("utf-8"))
        h.update(b"\0")
        if p.is_file():
            h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def safe_details(details: Dict[str, Any]) -> Dict[str, Any]:
    return redact_secrets(details)


def defaults_are_safe(settings: Optional[Settings] = None) -> bool:
    settings = settings or get_settings()
    return (
        settings.dry_run is True
        and settings.save_draft is True
        and settings.allow_final_submission is False
    )
