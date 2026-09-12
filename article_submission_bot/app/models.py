"""Pydantic and domain models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class SubmissionStatus(str, Enum):
    DRAFT = "draft"
    PREPARED = "prepared"
    DRAFT_SAVED = "draft_saved"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    SUBMITTED = "submitted"
    BLOCKED = "blocked"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class AuthorEntry(BaseModel):
    full_name: str
    publication_name: str = ""
    email: str = ""
    corresponding: bool = False
    institution: str = ""
    orcid: str = ""
    affiliation: str = ""
    order: int = 1

    @field_validator("publication_name", mode="before")
    @classmethod
    def default_pub_name(cls, v: Any, info: Any) -> str:
        if v:
            return str(v)
        data = info.data if hasattr(info, "data") else {}
        return str(data.get("full_name") or "")


class AuthorConfig(BaseModel):
    full_name: str
    publication_name: str
    corresponding_email: EmailStr
    country: str = "Brasil"
    institution: str = ""
    orcid: str = ""
    affiliation: str = ""
    department: str = ""
    phone: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    authors: List[AuthorEntry] = Field(default_factory=list)


class JournalConfig(BaseModel):
    code: str
    name: str
    portal_url: str
    adapter: str = "generic"
    selectors_key: str = ""
    requires_cover_letter: bool = True
    requires_title_page: bool = True
    requires_blinded_manuscript: bool = True
    requires_checklist: bool = True
    accepts_docx: bool = True
    accepts_pdf: bool = True
    max_file_mb: int = 20
    fee_warning_keywords: List[str] = Field(default_factory=list)
    contract_warning_keywords: List[str] = Field(default_factory=list)
    notes: str = ""


class PackageManifest(BaseModel):
    package_id: str
    package_hash: str
    created_at: datetime
    manuscript_code: str
    journal_code: str
    journal_name: str
    files: Dict[str, str] = Field(default_factory=dict)
    author_order: List[str] = Field(default_factory=list)
    corresponding_email: str = ""
    dry_run: bool = True
    notes: str = ""


class ConfirmationRecord(BaseModel):
    phrase: str
    manuscript_code: str
    journal_name: str
    package_hash: str
    created_at: datetime
    expires_at: datetime
    used: bool = False
    auth_file: Optional[str] = None


class SubmissionRequest(BaseModel):
    manuscript_code: str
    journal_code: str
    package_hash: str
    package_dir: Optional[str] = None
    dry_run: Optional[bool] = None
    save_draft: Optional[bool] = None


class FinalSubmitRequest(BaseModel):
    manuscript_code: str
    journal_code: str
    package_hash: str
    confirmation_phrase: str
    auth_file_path: Optional[str] = None


class PreSubmitReport(BaseModel):
    manuscript_code: str
    journal_code: str
    journal_name: str
    package_hash: str
    corresponding_email: str
    drive_account: str
    dry_run: bool
    save_draft: bool
    allow_final_submission: bool
    author_order: List[str]
    files: Dict[str, str]
    blockers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    human_interventions: List[str] = Field(default_factory=list)
    ready_for_draft: bool = False


class AuditEvent(BaseModel):
    event_type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    manuscript_code: str = ""
    journal_code: str = ""
    package_hash: str = ""
    actor: str = "system"
    details: Dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    message: str = ""


class DriveFileInfo(BaseModel):
    id: str
    name: str
    mime_type: str = ""
    modified_time: str = ""
    size: Optional[str] = None
    parents: List[str] = Field(default_factory=list)


class GmailMessageInfo(BaseModel):
    id: str
    thread_id: str = ""
    subject: str = ""
    snippet: str = ""
    from_addr: str = ""
    date: str = ""
    labels: List[str] = Field(default_factory=list)


class EditorialClassification(str, Enum):
    DESK_REJECT = "desk_reject"
    REVISION = "revision"
    ACCEPT = "accept"
    ACKNOWLEDGEMENT = "acknowledgement"
    QUERY = "query"
    UNKNOWN = "unknown"


class ReviewTask(BaseModel):
    message_id: str
    classification: EditorialClassification
    manuscript_id: Optional[str] = None
    deadline: Optional[str] = None
    summary: str = ""
    draft_reply_id: Optional[str] = None
