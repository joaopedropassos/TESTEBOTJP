"""Google Drive client — jp.criatividade@gmail.com only."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, List, Optional

from app.audit import audit
from app.models import DriveFileInfo
from app.safety import SafetyError, verify_authenticated_email
from app.settings import Settings, get_settings

DRIVE_EXPECTED_EMAIL = "jp.criatividade@gmail.com"


def _load_credentials(settings: Settings):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    scopes = settings.drive_scopes_list()
    token_path = settings.google_drive_token
    secrets_path = settings.google_drive_client_secrets
    creds = None

    if token_path.is_file():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not secrets_path.is_file():
                raise SafetyError(
                    f"Drive client secrets missing: {secrets_path}",
                    code="DRIVE_SECRETS_MISSING",
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), scopes)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_drive_service(settings: Optional[Settings] = None, credentials: Any = None):
    """Build Drive API service. Uses separate OAuth client/token from Gmail."""
    settings = settings or get_settings()
    from googleapiclient.discovery import build

    creds = credentials if credentials is not None else _load_credentials(settings)
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return service


def verify_authenticated_google_account(
    service: Any = None,
    *,
    expected_email: str = DRIVE_EXPECTED_EMAIL,
    settings: Optional[Settings] = None,
    about: Optional[dict] = None,
) -> str:
    """Verify the authenticated Drive account email."""
    settings = settings or get_settings()
    expected = expected_email or settings.drive_email
    if about is None:
        if service is None:
            service = get_drive_service(settings=settings)
        about = service.about().get(fields="user(emailAddress,displayName)").execute()
    email = (about.get("user") or {}).get("emailAddress") or ""
    verify_authenticated_email(email, expected, "drive")
    audit(
        "drive_account_verified",
        details={"email": email},
        message="Drive account verified",
    )
    return email


def list_drive_files(
    service: Any,
    *,
    query: str = "trashed=false",
    page_size: int = 100,
    fields: str = "nextPageToken, files(id, name, mimeType, modifiedTime, size, parents)",
) -> List[DriveFileInfo]:
    results: List[DriveFileInfo] = []
    page_token = None
    while True:
        resp = (
            service.files()
            .list(q=query, pageSize=page_size, fields=fields, pageToken=page_token)
            .execute()
        )
        for f in resp.get("files", []):
            results.append(
                DriveFileInfo(
                    id=f["id"],
                    name=f.get("name", ""),
                    mime_type=f.get("mimeType", ""),
                    modified_time=f.get("modifiedTime", ""),
                    size=f.get("size"),
                    parents=f.get("parents") or [],
                )
            )
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    audit("drive_list_files", details={"count": len(results), "query": query})
    return results


def download_drive_file(
    service: Any,
    file_id: str,
    dest_path: Path,
    *,
    mime_type: Optional[str] = None,
) -> Path:
    from googleapiclient.http import MediaIoBaseDownload

    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Export Google Docs if needed
    if mime_type and mime_type.startswith("application/vnd.google-apps"):
        export_map = {
            "application/vnd.google-apps.document": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            "application/vnd.google-apps.spreadsheet": (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            "application/vnd.google-apps.presentation": (
                "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            ),
        }
        export_mime = export_map.get(mime_type, "application/pdf")
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
    else:
        request = service.files().get_media(fileId=file_id)

    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    dest_path.write_bytes(fh.getvalue())
    audit(
        "drive_download",
        details={"file_id": file_id, "dest": str(dest_path)},
        message="Downloaded Drive file",
    )
    return dest_path
