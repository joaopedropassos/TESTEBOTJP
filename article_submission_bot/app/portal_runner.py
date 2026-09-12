"""Orchestrate portal draft preparation — never auto final_submit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.adapters.generic_portal import GenericPortalAdapter
from app.audit import audit
from app.browser_session import browser_session
from app.confirmations import validate_confirmation
from app.journal_requirements import load_journal
from app.models import AuthorConfig, PackageManifest, PreSubmitReport, SubmissionStatus
from app.package_builder import load_author_config
from app.portal_adapter import PortalActionResult, PortalAdapter
from app.safety import (
    SafetyError,
    acquire_submit_lock,
    assert_final_submission_allowed,
    defaults_are_safe,
    release_submit_lock,
    require_final_auth_file,
    verify_account_separation,
)
from app.settings import Settings, get_settings


def get_adapter(journal_code: str) -> PortalAdapter:
    journal = load_journal(journal_code)
    if journal.adapter == "generic":
        return GenericPortalAdapter(
            selectors_key=journal.selectors_key or journal_code,
            fee_keywords=journal.fee_warning_keywords,
            contract_keywords=journal.contract_warning_keywords,
        )
    raise SafetyError(f"Unknown adapter: {journal.adapter}", code="UNKNOWN_ADAPTER")


def load_manifest(package_dir: Path) -> PackageManifest:
    path = Path(package_dir) / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return PackageManifest.model_validate(data)


def build_pre_submit_report(
    manuscript_code: str,
    journal_code: str,
    package_dir: Path,
    *,
    settings: Optional[Settings] = None,
    author: Optional[AuthorConfig] = None,
) -> PreSubmitReport:
    settings = settings or get_settings()
    author = author or load_author_config()
    journal = load_journal(journal_code)
    manifest = load_manifest(package_dir)
    blockers = []
    warnings = []
    interventions = [
        "Review blinded manuscript for residual identifiers",
        "Confirm author order with all co-authors",
        "Verify journal APC / copyright terms manually",
        "Complete any CAPTCHA or 2FA in the portal",
        "Confirm institutional affiliation fields if required by journal",
    ]
    if not defaults_are_safe(settings) and settings.allow_final_submission:
        warnings.append("ALLOW_FINAL_SUBMISSION is enabled — extreme caution")
    if settings.dry_run:
        warnings.append("DRY_RUN=true — no live portal mutations expected beyond explicit draft flow")

    try:
        verify_account_separation(settings)
    except SafetyError as exc:
        blockers.append(str(exc))

    ready = len(blockers) == 0
    return PreSubmitReport(
        manuscript_code=manuscript_code,
        journal_code=journal_code,
        journal_name=journal.name,
        package_hash=manifest.package_hash,
        corresponding_email=str(author.corresponding_email),
        drive_account=settings.drive_email,
        dry_run=settings.dry_run,
        save_draft=settings.save_draft,
        allow_final_submission=settings.allow_final_submission,
        author_order=list(manifest.author_order),
        files=dict(manifest.files),
        blockers=blockers,
        warnings=warnings,
        human_interventions=interventions,
        ready_for_draft=ready,
    )


async def prepare_submission_draft(
    *,
    manuscript_code: str,
    journal_code: str,
    package_dir: Path,
    portal_url: Optional[str] = None,
    title: str = "",
    abstract: str = "",
    keywords: str = "",
    settings: Optional[Settings] = None,
    author: Optional[AuthorConfig] = None,
    adapter: Optional[PortalAdapter] = None,
    headless: Optional[bool] = None,
) -> PortalActionResult:
    """
    Prepare and optionally save a draft on the journal portal.
    NEVER performs final_submit automatically.
    """
    settings = settings or get_settings()
    author = author or load_author_config()
    verify_account_separation(settings)
    journal = load_journal(journal_code)
    package_dir = Path(package_dir)
    manifest = load_manifest(package_dir)
    adapter = adapter or get_adapter(journal_code)
    url = portal_url or journal.portal_url

    lock_key = f"{manuscript_code}:{journal_code}"
    acquire_submit_lock(lock_key, settings=settings)
    try:
        report = build_pre_submit_report(
            manuscript_code, journal_code, package_dir, settings=settings, author=author
        )
        if report.blockers:
            return PortalActionResult(
                success=False,
                action="prepare_submission_draft",
                message="Pre-submit blockers",
                blockers=report.blockers,
            )

        if settings.dry_run and not settings.save_draft:
            audit(
                "dry_run_skip_portal",
                manuscript_code=manuscript_code,
                journal_code=journal_code,
                package_hash=manifest.package_hash,
                message="DRY_RUN without SAVE_DRAFT — skipping portal interaction",
            )
            return PortalActionResult(
                success=True,
                action="prepare_submission_draft",
                message="Dry-run: portal interaction skipped",
                details={"status": SubmissionStatus.PREPARED.value, "report": report.model_dump(mode="json")},
                final_submitted=False,
            )

        async with browser_session(settings=settings, headless=headless) as page:
            r1 = await adapter.open_submission(page, url)
            if not r1.success:
                return r1
            blockers = await adapter.detect_blockers(page)
            if blockers.blockers:
                audit(
                    "portal_blocked",
                    manuscript_code=manuscript_code,
                    journal_code=journal_code,
                    success=False,
                    details={"blockers": blockers.blockers},
                )
                return PortalActionResult(
                    success=False,
                    action="prepare_submission_draft",
                    message="Portal blockers detected",
                    blockers=blockers.blockers,
                    final_submitted=False,
                )

            await adapter.fill_metadata(
                page,
                title=title or manuscript_code,
                abstract=abstract,
                keywords=keywords,
                author=author,
            )
            await adapter.upload_files(page, package_dir, manifest)

            draft_result = PortalActionResult(
                success=True,
                action="prepare_submission_draft",
                message="Prepared without saving draft",
                draft_saved=False,
                final_submitted=False,
            )
            if settings.save_draft:
                draft_result = await adapter.save_draft(page)

            # Explicitly do NOT call final_submit
            audit(
                "draft_prepared",
                manuscript_code=manuscript_code,
                journal_code=journal_code,
                package_hash=manifest.package_hash,
                details={
                    "draft_saved": draft_result.draft_saved,
                    "final_submitted": False,
                },
                message="Submission draft prepared; final submit not executed",
            )
            return PortalActionResult(
                success=draft_result.success,
                action="prepare_submission_draft",
                message=draft_result.message,
                draft_saved=draft_result.draft_saved,
                final_submitted=False,
                blockers=draft_result.blockers,
                warnings=draft_result.warnings,
                details={"status": SubmissionStatus.DRAFT_SAVED.value if draft_result.draft_saved else SubmissionStatus.PREPARED.value},
            )
    finally:
        release_submit_lock(lock_key)


async def final_submit_with_confirmation(
    *,
    manuscript_code: str,
    journal_code: str,
    package_hash: str,
    confirmation_phrase: str,
    package_dir: Path,
    auth_file_path: Optional[str] = None,
    settings: Optional[Settings] = None,
    adapter: Optional[PortalAdapter] = None,
) -> PortalActionResult:
    """
    Final submit — requires ALLOW_FINAL_SUBMISSION, confirmation phrase, and auth file.
    Still refuses at adapter unless all gates pass; designed to be hard to misuse.
    """
    settings = settings or get_settings()
    assert_final_submission_allowed(settings)
    journal = load_journal(journal_code)
    validate_confirmation(
        confirmation_phrase,
        manuscript_code=manuscript_code,
        journal_name=journal.name,
        package_hash=package_hash,
        settings=settings,
    )
    auth_path = require_final_auth_file(
        package_hash,
        Path(auth_file_path) if auth_file_path else None,
        settings=settings,
    )

    # Even when gates pass, GenericPortalAdapter.final_submit refuses.
    # This method documents the required human path; real click is intentionally not automated.
    audit(
        "final_submit_attempt",
        manuscript_code=manuscript_code,
        journal_code=journal_code,
        package_hash=package_hash,
        success=False,
        details={"auth_file": str(auth_path)},
        message="Final submit gates passed but automated final click is not performed — human must submit",
    )
    return PortalActionResult(
        success=False,
        action="final_submit",
        message=(
            "All confirmation gates passed, but automated final submission is intentionally "
            "not performed. Complete final submit manually in the portal."
        ),
        final_submitted=False,
        blockers=["AUTOMATED_FINAL_SUBMIT_DISABLED"],
        details={"auth_file": str(auth_path)},
    )
