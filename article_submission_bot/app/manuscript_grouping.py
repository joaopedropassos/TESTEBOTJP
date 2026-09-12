"""Group related manuscript files into logical submission units."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ManuscriptGroup:
    code: str
    title_hint: str = ""
    files: Dict[str, Path] = field(default_factory=dict)
    extras: List[Path] = field(default_factory=list)


ROLE_PATTERNS = [
    ("blinded", re.compile(r"(?i)(blind|anonym|cego|sem[_-]?ident)")),
    ("identified", re.compile(r"(?i)(identif|with[_-]?author|completo|full)")),
    ("title_page", re.compile(r"(?i)(title[_-]?page|folha[_-]?rosto|cover[_-]?page)")),
    ("cover_letter", re.compile(r"(?i)(cover[_-]?letter|carta[_-]?apresent)")),
    ("checklist", re.compile(r"(?i)(checklist|check[_-]?list)")),
    ("supplement", re.compile(r"(?i)(suppl|apêndice|appendix|anexo)")),
    ("figures", re.compile(r"(?i)(figure|figura|fig)")),
    ("tables", re.compile(r"(?i)(table|tabela)")),
    ("manuscript", re.compile(r"(?i)(manuscript|artigo|paper|ms)")),
]


def infer_role(filename: str) -> str:
    name = Path(filename).name
    for role, pat in ROLE_PATTERNS:
        if pat.search(name):
            return role
    suffix = Path(name).suffix.lower()
    if suffix in {".docx", ".pdf", ".txt", ".md"}:
        return "manuscript"
    return "other"


def infer_code(filename: str) -> str:
    stem = Path(filename).stem
    # Strip role tokens
    cleaned = stem
    for _, pat in ROLE_PATTERNS:
        cleaned = pat.sub(" ", cleaned)
    cleaned = re.sub(r"[_\-\s]+", "_", cleaned).strip("_")
    return cleaned or stem


def group_manuscript_files(paths: List[Path]) -> Dict[str, ManuscriptGroup]:
    groups: Dict[str, ManuscriptGroup] = {}
    for path in paths:
        path = Path(path)
        code = infer_code(path.name)
        role = infer_role(path.name)
        if code not in groups:
            groups[code] = ManuscriptGroup(code=code, title_hint=code.replace("_", " "))
        group = groups[code]
        if role in group.files:
            group.extras.append(path)
        else:
            if role == "other":
                group.extras.append(path)
            else:
                group.files[role] = path
    return groups


def select_primary_manuscript(group: ManuscriptGroup) -> Optional[Path]:
    for key in ("identified", "manuscript", "blinded"):
        if key in group.files:
            return group.files[key]
    if group.extras:
        return group.extras[0]
    return None
