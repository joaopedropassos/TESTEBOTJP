"""Structured audit logging without secrets."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from app.models import AuditEvent
from app.settings import get_settings

SECRET_PATTERNS = [
    re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|authorization)\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[a-z0-9\-._~+/]+=*"),
    re.compile(r"(?i)ya29\.[a-z0-9\-._~+/]+"),
    re.compile(r"(?i)client_secret[\"']?\s*[:=]\s*[\"']?[^\"'\s]+"),
]

REDACT_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "client_secret",
    "api_key",
    "authorization",
    "auth",
    "credentials",
}


def redact_secrets(value: Any) -> Any:
    """Recursively redact secrets from nested structures and strings."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if str(k).lower() in REDACT_KEYS:
                out[k] = "[REDACTED]"
            else:
                out[k] = redact_secrets(v)
        return out
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    if isinstance(value, str):
        text = value
        for pat in SECRET_PATTERNS:
            text = pat.sub("[REDACTED]", text)
        return text
    return value


def configure_logging() -> None:
    settings = get_settings()
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(__import__("logging"), settings.log_level.upper(), 20)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _redact_processor(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    return redact_secrets(event_dict)


def get_logger(name: str = "article_bot"):
    return structlog.get_logger(name)


def write_audit_event(event: AuditEvent) -> Path:
    """Persist audit event to JSONL file (no secrets)."""
    settings = get_settings()
    settings.ensure_directories()
    day = datetime.utcnow().strftime("%Y-%m-%d")
    path = settings.audit_dir / f"audit_{day}.jsonl"
    payload = redact_secrets(event.model_dump(mode="json"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    try:
        from app.database import AuditORM, get_engine
        from sqlalchemy.orm import Session

        get_engine()
        from app.database import _SessionLocal

        assert _SessionLocal is not None
        with _SessionLocal() as session:
            row = AuditORM(
                event_type=event.event_type,
                timestamp=event.timestamp,
                manuscript_code=event.manuscript_code,
                journal_code=event.journal_code,
                package_hash=event.package_hash,
                actor=event.actor,
                details_json=json.dumps(redact_secrets(event.details), default=str),
                success=event.success,
                message=redact_secrets(event.message) if isinstance(event.message, str) else "",
            )
            session.add(row)
            session.commit()
    except Exception:
        # Audit file write is primary; DB is best-effort
        pass

    get_logger().info(
        "audit_event",
        event_type=event.event_type,
        manuscript_code=event.manuscript_code,
        success=event.success,
        message=event.message,
    )
    return path


def audit(
    event_type: str,
    *,
    manuscript_code: str = "",
    journal_code: str = "",
    package_hash: str = "",
    actor: str = "system",
    details: Optional[Dict[str, Any]] = None,
    success: bool = True,
    message: str = "",
) -> Path:
    return write_audit_event(
        AuditEvent(
            event_type=event_type,
            manuscript_code=manuscript_code,
            journal_code=journal_code,
            package_hash=package_hash,
            actor=actor,
            details=details or {},
            success=success,
            message=message,
        )
    )
