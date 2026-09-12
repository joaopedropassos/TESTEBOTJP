"""Gmail client — institutional account only; drafts never send."""

from __future__ import annotations

import base64
import re
from datetime import datetime
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional, Tuple

from app.audit import audit
from app.models import (
    EditorialClassification,
    GmailMessageInfo,
    ReviewTask,
)
from app.safety import SafetyError, verify_authenticated_email
from app.settings import Settings, get_settings

GMAIL_EXPECTED_EMAIL = "joaopedro.passos@mail.uft.edu.br"

MANUSCRIPT_ID_PATTERNS = [
    re.compile(r"(?i)\b(?:ms|manuscript|submission|ref)[#:\s-]*([A-Z0-9][-A-Z0-9/]{3,})\b"),
    re.compile(r"(?i)\b([A-Z]{2,}-\d{4}-\d+)\b"),
]

DEADLINE_PATTERNS = [
    re.compile(r"(?i)deadline[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"),
    re.compile(r"(?i)due\s+(?:by|on)?\s*(\d{1,2}\s+\w+\s+\d{4})"),
    re.compile(r"(?i)until\s+(\d{1,2}\s+\w+\s+\d{4})"),
    re.compile(r"(?i)prazo[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"),
]


def _load_credentials(settings: Settings):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    scopes = settings.gmail_scopes_list()
    token_path = settings.google_gmail_token
    secrets_path = settings.google_gmail_client_secrets
    creds = None

    if token_path.is_file():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not secrets_path.is_file():
                raise SafetyError(
                    f"Gmail client secrets missing: {secrets_path}",
                    code="GMAIL_SECRETS_MISSING",
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), scopes)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_gmail_service(settings: Optional[Settings] = None, credentials: Any = None):
    settings = settings or get_settings()
    from googleapiclient.discovery import build

    creds = credentials if credentials is not None else _load_credentials(settings)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def verify_authenticated_google_account(
    service: Any = None,
    *,
    expected_email: str = GMAIL_EXPECTED_EMAIL,
    settings: Optional[Settings] = None,
    profile: Optional[dict] = None,
) -> str:
    settings = settings or get_settings()
    expected = expected_email or settings.gmail_email
    if profile is None:
        if service is None:
            service = get_gmail_service(settings=settings)
        profile = service.users().getProfile(userId="me").execute()
    email = profile.get("emailAddress") or ""
    verify_authenticated_email(email, expected, "gmail")
    # Never allow Drive email on Gmail client
    if email.lower() == "jp.criatividade@gmail.com":
        raise SafetyError(
            "Gmail client must not use Drive account",
            code="GMAIL_ACCOUNT_MIX",
        )
    audit("gmail_account_verified", details={"email": email}, message="Gmail account verified")
    return email


def search_gmail_messages(
    service: Any,
    query: str,
    *,
    max_results: int = 50,
) -> List[GmailMessageInfo]:
    resp = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    messages: List[GmailMessageInfo] = []
    for item in resp.get("messages", []):
        full = (
            service.users()
            .messages()
            .get(userId="me", id=item["id"], format="metadata",
                 metadataHeaders=["Subject", "From", "Date"])
            .execute()
        )
        headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])}
        messages.append(
            GmailMessageInfo(
                id=full["id"],
                thread_id=full.get("threadId", ""),
                subject=headers.get("subject", ""),
                snippet=full.get("snippet", ""),
                from_addr=headers.get("from", ""),
                date=headers.get("date", ""),
                labels=full.get("labelIds") or [],
            )
        )
    audit("gmail_search", details={"query": query, "count": len(messages)})
    return messages


def create_gmail_draft(
    service: Any,
    *,
    to: str,
    subject: str,
    body: str,
    thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a draft only — NEVER send."""
    message = MIMEText(body, _charset="utf-8")
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    draft_body: Dict[str, Any] = {"message": {"raw": raw}}
    if thread_id:
        draft_body["message"]["threadId"] = thread_id

    draft = service.users().drafts().create(userId="me", body=draft_body).execute()
    audit(
        "gmail_draft_created",
        details={"draft_id": draft.get("id"), "to": to, "subject": subject},
        message="Gmail draft created (not sent)",
    )
    return draft


def classify_editorial_message(subject: str, snippet: str) -> EditorialClassification:
    text = f"{subject} {snippet}".lower()
    if any(k in text for k in ("desk reject", "desk-reject", "not suitable", "outside scope")):
        return EditorialClassification.DESK_REJECT
    if any(k in text for k in ("accept", "accepted for publication", "congratulations")):
        return EditorialClassification.ACCEPT
    if any(k in text for k in ("revision", "revise", "major revision", "minor revision", "resubmit")):
        return EditorialClassification.REVISION
    if any(k in text for k in ("received", "acknowledg", "under review", "submitted successfully")):
        return EditorialClassification.ACKNOWLEDGEMENT
    if any(k in text for k in ("query", "clarification", "question regarding")):
        return EditorialClassification.QUERY
    return EditorialClassification.UNKNOWN


def extract_manuscript_id(text: str) -> Optional[str]:
    for pat in MANUSCRIPT_ID_PATTERNS:
        m = pat.search(text or "")
        if m:
            return m.group(1)
    return None


def extract_deadlines(text: str) -> List[str]:
    found: List[str] = []
    for pat in DEADLINE_PATTERNS:
        for m in pat.finditer(text or ""):
            found.append(m.group(1))
    return found


def create_review_task(
    message: GmailMessageInfo,
    *,
    body_text: Optional[str] = None,
) -> ReviewTask:
    text = body_text or f"{message.subject}\n{message.snippet}"
    classification = classify_editorial_message(message.subject, message.snippet)
    ms_id = extract_manuscript_id(text)
    deadlines = extract_deadlines(text)
    return ReviewTask(
        message_id=message.id,
        classification=classification,
        manuscript_id=ms_id,
        deadline=deadlines[0] if deadlines else None,
        summary=message.snippet[:500],
    )


def create_draft_reply(
    service: Any,
    message: GmailMessageInfo,
    *,
    body: str,
    to: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a draft reply — never send."""
    subject = message.subject if message.subject.lower().startswith("re:") else f"Re: {message.subject}"
    return create_gmail_draft(
        service,
        to=to or message.from_addr,
        subject=subject,
        body=body,
        thread_id=message.thread_id or None,
    )


# Explicit guard: no send helpers exported
def send_gmail_message(*_args: Any, **_kwargs: Any) -> None:
    raise SafetyError(
        "Sending Gmail messages is disabled — drafts only",
        code="GMAIL_SEND_FORBIDDEN",
    )
