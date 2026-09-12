"""Build submission packages: blinded/identified/cover/title_page/checklist/manifest."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from docx import Document

from app.audit import audit
from app.journal_requirements import JournalRequirements, load_journal, snapshot_requirements
from app.manuscript_extractor import ManuscriptMeta, extract_manuscript
from app.models import AuthorConfig, PackageManifest
from app.safety import package_hash_from_files, preserve_author_order, validate_author_config
from app.settings import get_settings


def load_author_config(path: Optional[Path] = None) -> AuthorConfig:
    import yaml

    settings = get_settings()
    path = path or settings.author_config_path
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    config = AuthorConfig.model_validate(data)
    validate_author_config(config)
    return config


def _write_docx(path: Path, title: str, paragraphs: List[str]) -> Path:
    doc = Document()
    doc.add_heading(title, level=1)
    for p in paragraphs:
        doc.add_paragraph(p)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path


def build_title_page(dest: Path, author: AuthorConfig, meta: ManuscriptMeta) -> Path:
    authors = preserve_author_order(author.authors)
    lines = [
        meta.title or "(título a confirmar)",
        "",
        "Autores (ordem preservada — não reordenar automaticamente):",
    ]
    for a in authors:
        role = " [corresponding]" if a.corresponding else ""
        inst = a.institution or author.institution or "[institution: vazio — não inventar]"
        lines.append(f"{a.order}. {a.publication_name or a.full_name}{role} — {inst}")
        if a.email:
            lines.append(f"   E-mail: {a.email}")
        if a.orcid:
            lines.append(f"   ORCID: {a.orcid}")
    lines.extend(
        [
            "",
            f"Autor correspondente: {author.full_name}",
            f"E-mail correspondente: {author.corresponding_email}",
            f"País: {author.country}",
            f"Instituição: {author.institution or '[vazio]'}",
            f"ORCID: {author.orcid or '[vazio]'}",
        ]
    )
    return _write_docx(dest, "Title Page", lines)


def build_cover_letter(dest: Path, author: AuthorConfig, meta: ManuscriptMeta, journal_name: str) -> Path:
    body = [
        f"Prezada Editora / Prezado Editor de {journal_name},",
        "",
        f"Submetemos o manuscrito intitulado \"{meta.title}\" para apreciação.",
        "",
        "Declaramos que o trabalho é original, não está sob consideração em outro periódico "
        "e que todos os autores aprovaram a versão submetida.",
        "",
        "Atenciosamente,",
        author.full_name,
        str(author.corresponding_email),
        author.country,
    ]
    return _write_docx(dest, "Cover Letter", body)


def build_checklist(dest: Path, reqs: JournalRequirements, meta: ManuscriptMeta) -> Path:
    lines = [
        f"Journal: {reqs.name} ({reqs.code})",
        f"Title: {meta.title}",
        f"Word count (approx): {meta.word_count}",
        f"Pages (pdf): {meta.page_count}",
        "",
        "Requirements:",
    ]
    for item in reqs.checklist_items():
        lines.append(f"[ ] {item}")
    return _write_docx(dest, "Submission Checklist", lines)


def build_blinded_stub(dest: Path, meta: ManuscriptMeta) -> Path:
    """Create blinded manuscript stub from extracted text (authors removed)."""
    lines = [
        meta.title,
        "",
        "[Versão cega — identificação de autores removida]",
        "",
        "Abstract",
        meta.abstract or "[preencher]",
        "",
        "Keywords: " + ", ".join(meta.keywords) if meta.keywords else "Keywords: [preencher]",
        "",
        meta.text_sample,
        "",
        "[Conteúdo completo deve ser revisado humanamente antes do envio]",
    ]
    return _write_docx(dest, meta.title or "Blinded Manuscript", lines)


def build_package(
    manuscript_code: str,
    journal_code: str,
    source_file: Path,
    *,
    author: Optional[AuthorConfig] = None,
    output_dir: Optional[Path] = None,
    identified_file: Optional[Path] = None,
) -> PackageManifest:
    settings = get_settings()
    author = author or load_author_config()
    validate_author_config(author)
    journal = load_journal(journal_code)
    reqs = JournalRequirements.from_journal(journal)

    out = Path(output_dir or (settings.packages_dir / manuscript_code / journal_code))
    out.mkdir(parents=True, exist_ok=True)

    source_file = Path(source_file)
    meta = extract_manuscript(source_file)

    files: Dict[str, str] = {}

    # Identified manuscript
    ident_dest = out / f"{manuscript_code}_identified{source_file.suffix}"
    src_ident = Path(identified_file) if identified_file else source_file
    shutil.copy2(src_ident, ident_dest)
    files["identified"] = ident_dest.name

    # Blinded
    blind_dest = out / f"{manuscript_code}_blinded.docx"
    build_blinded_stub(blind_dest, meta)
    files["blinded"] = blind_dest.name

    # Title page
    if reqs.requires_title_page:
        tp = out / f"{manuscript_code}_title_page.docx"
        build_title_page(tp, author, meta)
        files["title_page"] = tp.name

    # Cover letter
    if reqs.requires_cover_letter:
        cl = out / f"{manuscript_code}_cover_letter.docx"
        build_cover_letter(cl, author, meta, journal.name)
        files["cover_letter"] = cl.name

    # Checklist
    if reqs.requires_checklist:
        ck = out / f"{manuscript_code}_checklist.docx"
        build_checklist(ck, reqs, meta)
        files["checklist"] = ck.name

    # Requirements snapshot
    snap = out / "requirements_snapshot.json"
    snap.write_text(
        json.dumps(snapshot_requirements(journal), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    files["requirements_snapshot"] = snap.name

    # Author order preserved
    ordered = preserve_author_order(author.authors)
    author_order = [a.full_name for a in ordered]

    # Hash all package files
    file_paths = [out / name for name in files.values()]
    pkg_hash = package_hash_from_files(file_paths)

    manifest = PackageManifest(
        package_id=f"{manuscript_code}-{journal_code}",
        package_hash=pkg_hash,
        created_at=datetime.utcnow(),
        manuscript_code=manuscript_code,
        journal_code=journal_code,
        journal_name=journal.name,
        files=files,
        author_order=author_order,
        corresponding_email=str(author.corresponding_email),
        dry_run=settings.dry_run,
        notes="Package built locally. Human review required before any final submit.",
    )
    manifest_path = out / "manifest.json"
    manifest_path.write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    files["manifest"] = manifest_path.name

    # Re-hash including manifest
    file_paths = [out / name for name in files.values() if name != "manifest.json"]
    file_paths.append(manifest_path)
    # Keep hash stable as computed before embedding — store as-is in manifest already written
    # Update manifest file hash field remains the content hash of submission artifacts
    audit(
        "package_built",
        manuscript_code=manuscript_code,
        journal_code=journal_code,
        package_hash=pkg_hash,
        details={"files": files, "author_order": author_order},
        message="Submission package built",
    )
    return manifest
