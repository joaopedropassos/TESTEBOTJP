"""Journal requirements loading and snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.models import JournalConfig
from app.settings import get_settings


def load_journals(path: Optional[Path] = None) -> Dict[str, JournalConfig]:
    settings = get_settings()
    path = path or settings.journals_config_path
    if not Path(path).is_file():
        # Fall back to example
        example = settings.journals_config_path.parent / "journals.example.yaml"
        path = example if example.is_file() else path
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    journals_raw = raw.get("journals", raw)
    result: Dict[str, JournalConfig] = {}
    for key, val in journals_raw.items():
        data = dict(val)
        data.setdefault("code", key.upper() if not data.get("code") else data["code"])
        data.setdefault("selectors_key", key)
        result[key] = JournalConfig.model_validate(data)
    return result


def load_journal(code_or_key: str, path: Optional[Path] = None) -> JournalConfig:
    journals = load_journals(path)
    if code_or_key in journals:
        return journals[code_or_key]
    for j in journals.values():
        if j.code.lower() == code_or_key.lower():
            return j
    raise KeyError(f"Journal not found: {code_or_key}")


@dataclass
class JournalRequirements:
    code: str
    name: str
    requires_cover_letter: bool = True
    requires_title_page: bool = True
    requires_blinded_manuscript: bool = True
    requires_checklist: bool = True
    accepts_docx: bool = True
    accepts_pdf: bool = True
    max_file_mb: int = 20
    fee_warning_keywords: List[str] = field(default_factory=list)
    contract_warning_keywords: List[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_journal(cls, journal: JournalConfig) -> "JournalRequirements":
        return cls(
            code=journal.code,
            name=journal.name,
            requires_cover_letter=journal.requires_cover_letter,
            requires_title_page=journal.requires_title_page,
            requires_blinded_manuscript=journal.requires_blinded_manuscript,
            requires_checklist=journal.requires_checklist,
            accepts_docx=journal.accepts_docx,
            accepts_pdf=journal.accepts_pdf,
            max_file_mb=journal.max_file_mb,
            fee_warning_keywords=list(journal.fee_warning_keywords),
            contract_warning_keywords=list(journal.contract_warning_keywords),
            notes=journal.notes,
        )

    def checklist_items(self) -> List[str]:
        items = [
            "Title matches manuscript",
            "Corresponding email is institutional (UFT)",
            "Author order preserved as declared",
            "All co-authors approved submission",
            "No simultaneous submission elsewhere",
        ]
        if self.requires_blinded_manuscript:
            items.append("Blinded manuscript without author identifiers")
        if self.requires_title_page:
            items.append("Separate title page with author details")
        if self.requires_cover_letter:
            items.append("Cover letter included")
        if self.requires_checklist:
            items.append("Journal checklist completed")
        items.append(f"Files within {self.max_file_mb} MB limit")
        return items


def snapshot_requirements(journal: JournalConfig) -> Dict[str, Any]:
    reqs = JournalRequirements.from_journal(journal)
    return {
        "code": reqs.code,
        "name": reqs.name,
        "requires_cover_letter": reqs.requires_cover_letter,
        "requires_title_page": reqs.requires_title_page,
        "requires_blinded_manuscript": reqs.requires_blinded_manuscript,
        "requires_checklist": reqs.requires_checklist,
        "accepts_docx": reqs.accepts_docx,
        "accepts_pdf": reqs.accepts_pdf,
        "max_file_mb": reqs.max_file_mb,
        "fee_warning_keywords": reqs.fee_warning_keywords,
        "contract_warning_keywords": reqs.contract_warning_keywords,
        "checklist_items": reqs.checklist_items(),
        "notes": reqs.notes,
        "portal_url": journal.portal_url,
        "adapter": journal.adapter,
    }


def load_selectors(path: Optional[Path] = None) -> Dict[str, Any]:
    settings = get_settings()
    path = path or settings.selectors_config_path
    if not Path(path).is_file():
        example = path.parent / "selectors.example.yaml"
        path = example if example.is_file() else path
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
