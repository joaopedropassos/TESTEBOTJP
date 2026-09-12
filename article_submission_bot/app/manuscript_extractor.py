"""Extract text and metadata from manuscript files (docx/pdf)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class ManuscriptMeta:
    path: str
    title: str = ""
    abstract: str = ""
    keywords: List[str] = field(default_factory=list)
    authors_found: List[str] = field(default_factory=list)
    text_sample: str = ""
    page_count: int = 0
    word_count: int = 0
    format: str = ""


def extract_docx(path: Path) -> ManuscriptMeta:
    from docx import Document

    doc = Document(str(path))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    full_text = "\n".join(paragraphs)
    title = paragraphs[0] if paragraphs else path.stem
    abstract = _find_section(full_text, "abstract") or _find_section(full_text, "resumo")
    keywords = _find_keywords(full_text)
    authors = _guess_authors(paragraphs[:8])
    words = len(re.findall(r"\w+", full_text))
    return ManuscriptMeta(
        path=str(path),
        title=title,
        abstract=abstract[:4000],
        keywords=keywords,
        authors_found=authors,
        text_sample=full_text[:2000],
        page_count=0,
        word_count=words,
        format="docx",
    )


def extract_pdf(path: Path) -> ManuscriptMeta:
    text = ""
    page_count = 0
    try:
        import fitz  # PyMuPDF

        with fitz.open(str(path)) as doc:
            page_count = doc.page_count
            parts = []
            for i, page in enumerate(doc):
                if i > 20:
                    break
                parts.append(page.get_text())
            text = "\n".join(parts)
    except Exception:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        page_count = len(reader.pages)
        parts = []
        for i, page in enumerate(reader.pages):
            if i > 20:
                break
            parts.append(page.extract_text() or "")
        text = "\n".join(parts)

    paragraphs = [ln.strip() for ln in text.splitlines() if ln.strip()]
    title = paragraphs[0] if paragraphs else path.stem
    abstract = _find_section(text, "abstract") or _find_section(text, "resumo")
    keywords = _find_keywords(text)
    authors = _guess_authors(paragraphs[:10])
    words = len(re.findall(r"\w+", text))
    return ManuscriptMeta(
        path=str(path),
        title=title[:500],
        abstract=abstract[:4000],
        keywords=keywords,
        authors_found=authors,
        text_sample=text[:2000],
        page_count=page_count,
        word_count=words,
        format="pdf",
    )


def extract_manuscript(path: Path) -> ManuscriptMeta:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix in {".docx"}:
        return extract_docx(path)
    if suffix in {".pdf"}:
        return extract_pdf(path)
    if suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        paragraphs = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return ManuscriptMeta(
            path=str(path),
            title=paragraphs[0] if paragraphs else path.stem,
            abstract=_find_section(text, "abstract"),
            keywords=_find_keywords(text),
            authors_found=[],
            text_sample=text[:2000],
            word_count=len(re.findall(r"\w+", text)),
            format=suffix.lstrip("."),
        )
    raise ValueError(f"Unsupported manuscript format: {suffix}")


def _find_section(text: str, heading: str) -> str:
    pat = re.compile(
        rf"(?is)\b{re.escape(heading)}\b[:\s]*\n*(.+?)(?:\n\s*\n|\n(?:keywords|palavras-chave|introduction|introdução)\b)",
    )
    m = pat.search(text)
    if m:
        return m.group(1).strip()
    return ""


def _find_keywords(text: str) -> List[str]:
    pat = re.compile(
        r"(?im)^(?:keywords|palavras-chave)\s*[:\-]\s*(.+)$",
    )
    m = pat.search(text)
    if not m:
        return []
    raw = m.group(1)
    parts = re.split(r"[;,]", raw)
    return [p.strip() for p in parts if p.strip()][:20]


def _guess_authors(paragraphs: List[str]) -> List[str]:
    """Heuristic only — never invent; return empty if unsure."""
    found: List[str] = []
    name_re = re.compile(r"^[A-ZÁÉÍÓÚÂÊÔÃÕÀ][a-záéíóúâêôãõàç]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÀ][a-záéíóúâêôãõàç\.]+){1,5}$")
    for p in paragraphs[1:6]:
        if "@" in p or "abstract" in p.lower() or "resumo" in p.lower():
            continue
        if name_re.match(p) and len(p) < 80:
            found.append(p)
    return found
