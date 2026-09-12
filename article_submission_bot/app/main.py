"""FastAPI application entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.audit import audit, configure_logging, redact_secrets
from app.confirmations import (
    build_confirmation_phrase,
    create_confirmation,
    invalidate_on_hash_change,
)
from app.database import get_engine
from app.journal_requirements import load_journal, load_journals
from app.models import FinalSubmitRequest, PreSubmitReport, SubmissionRequest
from app.package_builder import build_package, load_author_config
from app.portal_runner import (
    build_pre_submit_report,
    final_submit_with_confirmation,
    prepare_submission_draft,
)
from app.safety import (
    SafetyError,
    assert_final_submission_allowed,
    defaults_are_safe,
    verify_account_separation,
)
from app.settings import get_settings

configure_logging()
get_engine()

app = FastAPI(
    title="Article Submission Bot",
    description=(
        "Safe academic manuscript submission assistant. "
        "Defaults: DRY_RUN=true, SAVE_DRAFT=true, ALLOW_FINAL_SUBMISSION=false. "
        "No real auto-submit."
    ),
    version="0.1.0",
)


class BuildPackageBody(BaseModel):
    manuscript_code: str
    journal_code: str
    source_file: str
    identified_file: Optional[str] = None


class ConfirmationBody(BaseModel):
    manuscript_code: str
    journal_code: str
    package_hash: str


class DraftBody(SubmissionRequest):
    package_dir: str
    title: str = ""
    abstract: str = ""
    keywords: str = ""
    portal_url: Optional[str] = None


@app.get("/health")
def health() -> Dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "dry_run": settings.dry_run,
        "save_draft": settings.save_draft,
        "allow_final_submission": settings.allow_final_submission,
        "defaults_safe": defaults_are_safe(settings),
    }


@app.get("/author")
def get_author() -> Dict[str, Any]:
    author = load_author_config()
    return author.model_dump(mode="json")


@app.get("/journals")
def list_journals() -> Dict[str, Any]:
    journals = load_journals()
    return {k: v.model_dump(mode="json") for k, v in journals.items()}


@app.get("/journals/{journal_code}")
def get_journal(journal_code: str) -> Dict[str, Any]:
    try:
        return load_journal(journal_code).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/packages/build")
def api_build_package(body: BuildPackageBody) -> Dict[str, Any]:
    try:
        verify_account_separation()
        manifest = build_package(
            body.manuscript_code,
            body.journal_code,
            Path(body.source_file),
            identified_file=Path(body.identified_file) if body.identified_file else None,
        )
        return manifest.model_dump(mode="json")
    except SafetyError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message}) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/pre-submit-report")
def api_pre_submit_report(body: DraftBody) -> Dict[str, Any]:
    try:
        report = build_pre_submit_report(
            body.manuscript_code,
            body.journal_code,
            Path(body.package_dir),
        )
        return report.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/prepare-draft")
async def api_prepare_draft(body: DraftBody) -> Dict[str, Any]:
    try:
        result = await prepare_submission_draft(
            manuscript_code=body.manuscript_code,
            journal_code=body.journal_code,
            package_dir=Path(body.package_dir),
            portal_url=body.portal_url,
            title=body.title,
            abstract=body.abstract,
            keywords=body.keywords,
        )
        return {
            "success": result.success,
            "action": result.action,
            "message": result.message,
            "draft_saved": result.draft_saved,
            "final_submitted": result.final_submitted,
            "blockers": result.blockers,
            "warnings": result.warnings,
            "details": redact_secrets(result.details),
        }
    except SafetyError as exc:
        raise HTTPException(status_code=403, detail={"code": exc.code, "message": exc.message}) from exc


@app.post("/confirmations")
def api_create_confirmation(body: ConfirmationBody) -> Dict[str, Any]:
    try:
        journal = load_journal(body.journal_code)
        record = create_confirmation(
            body.manuscript_code,
            journal.name,
            body.package_hash,
        )
        return record.model_dump(mode="json")
    except SafetyError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message}) from exc


@app.post("/confirmations/preview-phrase")
def api_preview_phrase(body: ConfirmationBody) -> Dict[str, str]:
    journal = load_journal(body.journal_code)
    phrase = build_confirmation_phrase(body.manuscript_code, journal.name, body.package_hash)
    return {"phrase": phrase}


@app.post("/final-submit")
async def api_final_submit(body: FinalSubmitRequest) -> JSONResponse:
    """
    Final submit endpoint.
    Returns 403 when ALLOW_FINAL_SUBMISSION is false, DRY_RUN is true,
    confirmation is invalid, or auth file is missing/mismatched.
    Even when gates pass, automated final click is not performed.
    """
    settings = get_settings()
    try:
        if not settings.allow_final_submission:
            audit(
                "final_submit_forbidden",
                manuscript_code=body.manuscript_code,
                journal_code=body.journal_code,
                package_hash=body.package_hash,
                success=False,
                message="ALLOW_FINAL_SUBMISSION=false",
            )
            return JSONResponse(
                status_code=403,
                content={
                    "code": "FINAL_SUBMIT_DISABLED",
                    "message": "ALLOW_FINAL_SUBMISSION is false — final submit blocked",
                },
            )
        if settings.dry_run:
            return JSONResponse(
                status_code=403,
                content={
                    "code": "DRY_RUN_BLOCKS_FINAL",
                    "message": "DRY_RUN is true — final submit blocked",
                },
            )

        assert_final_submission_allowed(settings)
        # package_dir inferred from packages storage
        package_dir = settings.packages_dir / body.manuscript_code / body.journal_code
        result = await final_submit_with_confirmation(
            manuscript_code=body.manuscript_code,
            journal_code=body.journal_code,
            package_hash=body.package_hash,
            confirmation_phrase=body.confirmation_phrase,
            package_dir=package_dir,
            auth_file_path=body.auth_file_path,
            settings=settings,
        )
        status = 403 if not result.final_submitted else 200
        return JSONResponse(
            status_code=status,
            content={
                "success": result.success,
                "final_submitted": result.final_submitted,
                "message": result.message,
                "blockers": result.blockers,
                "details": redact_secrets(result.details),
            },
        )
    except SafetyError as exc:
        return JSONResponse(
            status_code=403,
            content={"code": exc.code, "message": exc.message},
        )


@app.post("/invalidate-confirmation")
def api_invalidate(old_hash: str, new_hash: str) -> Dict[str, str]:
    invalidate_on_hash_change(old_hash, new_hash)
    return {"status": "ok"}


@app.get("/safety/defaults")
def api_safety_defaults() -> Dict[str, Any]:
    settings = get_settings()
    try:
        verify_account_separation(settings)
        account_ok = True
        account_error = None
    except SafetyError as exc:
        account_ok = False
        account_error = {"code": exc.code, "message": exc.message}
    return {
        "dry_run": settings.dry_run,
        "save_draft": settings.save_draft,
        "allow_final_submission": settings.allow_final_submission,
        "defaults_safe": defaults_are_safe(settings),
        "account_separation_ok": account_ok,
        "account_error": account_error,
        "institutional_email": settings.institutional_email,
        "drive_email": settings.drive_email,
        "gmail_email": settings.gmail_email,
    }


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.api_host, port=settings.api_port, reload=False)


if __name__ == "__main__":
    run()
