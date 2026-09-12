"""Application settings via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Safety defaults
    dry_run: bool = True
    save_draft: bool = True
    allow_final_submission: bool = False

    # Config paths
    author_config_path: Path = PROJECT_ROOT / "config" / "author.yaml"
    journals_config_path: Path = PROJECT_ROOT / "config" / "journals.yaml"
    selectors_config_path: Path = PROJECT_ROOT / "config" / "selectors.yaml"

    # Identity emails
    institutional_email: str = "joaopedro.passos@mail.uft.edu.br"
    drive_email: str = "jp.criatividade@gmail.com"
    gmail_email: str = "joaopedro.passos@mail.uft.edu.br"

    # Google Drive OAuth (jp.criatividade@gmail.com)
    google_drive_client_secrets: Path = PROJECT_ROOT / "secrets" / "drive_client_secrets.json"
    google_drive_token: Path = PROJECT_ROOT / "secrets" / "drive_token.json"
    google_drive_scopes: str = "https://www.googleapis.com/auth/drive.readonly"

    # Google Gmail OAuth (institutional) — drafts only
    google_gmail_client_secrets: Path = PROJECT_ROOT / "secrets" / "gmail_client_secrets.json"
    google_gmail_token: Path = PROJECT_ROOT / "secrets" / "gmail_token.json"
    google_gmail_scopes: str = (
        "https://www.googleapis.com/auth/gmail.compose,"
        "https://www.googleapis.com/auth/gmail.readonly"
    )

    # Paths
    data_dir: Path = PROJECT_ROOT / "data"
    storage_dir: Path = PROJECT_ROOT / "storage"
    audit_dir: Path = PROJECT_ROOT / "data" / "audit"
    packages_dir: Path = PROJECT_ROOT / "data" / "packages"
    originals_dir: Path = PROJECT_ROOT / "data" / "originals"
    working_dir: Path = PROJECT_ROOT / "data" / "working"
    quarantine_dir: Path = PROJECT_ROOT / "data" / "quarantine"
    sqlite_url: str = f"sqlite:///{PROJECT_ROOT / 'storage' / 'article_bot.db'}"

    # Confirmation
    confirmation_ttl_seconds: int = 900
    final_auth_dir: Path = Path("/tmp")
    final_auth_prefix: str = "article_bot_final_auth_"

    # Playwright
    playwright_headless: bool = True
    playwright_timeout_ms: int = 30000
    browser_auth_dir: Path = PROJECT_ROOT / "playwright" / ".auth"

    # API
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "INFO"

    # Guards
    block_simultaneous_submit: bool = True

    @field_validator(
        "author_config_path",
        "journals_config_path",
        "selectors_config_path",
        "google_drive_client_secrets",
        "google_drive_token",
        "google_gmail_client_secrets",
        "google_gmail_token",
        "data_dir",
        "storage_dir",
        "audit_dir",
        "packages_dir",
        "originals_dir",
        "working_dir",
        "quarantine_dir",
        "final_auth_dir",
        "browser_auth_dir",
        mode="before",
    )
    @classmethod
    def _resolve_path(cls, v: object) -> Path:
        p = Path(str(v))
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p

    def drive_scopes_list(self) -> List[str]:
        return [s.strip() for s in self.google_drive_scopes.split(",") if s.strip()]

    def gmail_scopes_list(self) -> List[str]:
        return [s.strip() for s in self.google_gmail_scopes.split(",") if s.strip()]

    def ensure_directories(self) -> None:
        for d in (
            self.data_dir,
            self.storage_dir,
            self.audit_dir,
            self.packages_dir,
            self.originals_dir,
            self.working_dir,
            self.quarantine_dir,
            self.browser_auth_dir,
            PROJECT_ROOT / "secrets",
        ):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
