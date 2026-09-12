"""Async Playwright browser session helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from app.settings import Settings, get_settings


@asynccontextmanager
async def browser_session(
    *,
    headless: Optional[bool] = None,
    settings: Optional[Settings] = None,
    storage_state: Optional[Path] = None,
) -> AsyncIterator[Any]:
    """Yield a Playwright page within a browser context."""
    from playwright.async_api import async_playwright

    settings = settings or get_settings()
    headless = settings.playwright_headless if headless is None else headless
    settings.browser_auth_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context_kwargs: dict = {
            "viewport": {"width": 1280, "height": 900},
        }
        if storage_state and Path(storage_state).is_file():
            context_kwargs["storage_state"] = str(storage_state)
        context = await browser.new_context(**context_kwargs)
        context.set_default_timeout(settings.playwright_timeout_ms)
        page = await context.new_page()
        try:
            yield page
        finally:
            await context.close()
            await browser.close()


async def save_storage_state(page: Any, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    await page.context.storage_state(path=str(path))
    return path
