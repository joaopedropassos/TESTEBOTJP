"""Abstract portal adapter for journal submission systems."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.models import AuthorConfig, PackageManifest


@dataclass
class PortalActionResult:
    success: bool
    action: str
    message: str = ""
    draft_saved: bool = False
    final_submitted: bool = False
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


class PortalAdapter(ABC):
    """ABC for journal portals. Adapters must never auto final-submit."""

    name: str = "base"

    @abstractmethod
    async def open_submission(self, page: Any, portal_url: str) -> PortalActionResult:
        ...

    @abstractmethod
    async def fill_metadata(
        self,
        page: Any,
        *,
        title: str,
        abstract: str,
        keywords: str,
        author: AuthorConfig,
    ) -> PortalActionResult:
        ...

    @abstractmethod
    async def upload_files(
        self,
        page: Any,
        package_dir: Path,
        manifest: PackageManifest,
    ) -> PortalActionResult:
        ...

    @abstractmethod
    async def save_draft(self, page: Any) -> PortalActionResult:
        ...

    @abstractmethod
    async def detect_blockers(self, page: Any) -> PortalActionResult:
        ...

    async def final_submit(self, page: Any) -> PortalActionResult:
        """Default: always refuse. Subclasses must keep this gated."""
        return PortalActionResult(
            success=False,
            action="final_submit",
            message="final_submit is disabled on adapter — use portal_runner with explicit confirmation",
            final_submitted=False,
            blockers=["FINAL_SUBMIT_DISABLED_ON_ADAPTER"],
        )
