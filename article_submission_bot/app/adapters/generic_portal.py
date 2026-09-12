"""Generic YAML-selector-driven portal adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from app.audit import audit
from app.journal_requirements import load_selectors
from app.models import AuthorConfig, PackageManifest
from app.portal_adapter import PortalActionResult, PortalAdapter
from app.safety import stop_on_fee_or_contract


class GenericPortalAdapter(PortalAdapter):
    name = "generic"

    def __init__(
        self,
        selectors_key: str = "example_journal",
        selectors: Optional[Dict[str, Any]] = None,
        fee_keywords: Optional[list] = None,
        contract_keywords: Optional[list] = None,
    ):
        all_sel = selectors if selectors is not None else load_selectors()
        if selectors_key not in all_sel:
            raise KeyError(f"Selectors key not found: {selectors_key}")
        self.selectors = all_sel[selectors_key]
        self.selectors_key = selectors_key
        self.fee_keywords = fee_keywords
        self.contract_keywords = contract_keywords

    def _sel(self, *keys: str) -> Optional[str]:
        node: Any = self.selectors
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return None
            node = node[k]
        return node if isinstance(node, str) else None

    async def open_submission(self, page: Any, portal_url: str) -> PortalActionResult:
        await page.goto(portal_url)
        new_sub = self._sel("navigation", "new_submission")
        if new_sub:
            loc = page.locator(new_sub)
            if await loc.count() > 0:
                await loc.first.click()
        audit("portal_open", details={"url": portal_url, "adapter": self.name})
        return PortalActionResult(success=True, action="open_submission", message="Opened submission page")

    async def fill_metadata(
        self,
        page: Any,
        *,
        title: str,
        abstract: str,
        keywords: str,
        author: AuthorConfig,
    ) -> PortalActionResult:
        mapping = {
            ("form", "title"): title,
            ("form", "abstract"): abstract,
            ("form", "keywords"): keywords,
            ("form", "corresponding_email"): str(author.corresponding_email),
            ("form", "corresponding_name"): author.full_name,
        }
        filled = []
        for keys, value in mapping.items():
            sel = self._sel(*keys)
            if not sel:
                continue
            loc = page.locator(sel)
            if await loc.count() == 0:
                continue
            tag = await loc.first.evaluate("el => el.tagName.toLowerCase()")
            if tag == "select":
                try:
                    await loc.first.select_option(label=author.country)
                except Exception:
                    await loc.first.select_option(value=author.country)
            else:
                await loc.first.fill(value)
            filled.append(sel)

        country_sel = self._sel("form", "country")
        if country_sel:
            loc = page.locator(country_sel)
            if await loc.count() > 0:
                try:
                    await loc.first.select_option(label=author.country)
                except Exception:
                    try:
                        await loc.first.select_option(value=author.country)
                    except Exception:
                        await loc.first.fill(author.country)

        return PortalActionResult(
            success=True,
            action="fill_metadata",
            message=f"Filled {len(filled)} fields",
            details={"filled": filled},
        )

    async def upload_files(
        self,
        page: Any,
        package_dir: Path,
        manifest: PackageManifest,
    ) -> PortalActionResult:
        package_dir = Path(package_dir)
        upload_map = {
            "manuscript_blinded": "blinded",
            "manuscript_identified": "identified",
            "title_page": "title_page",
            "cover_letter_file": "cover_letter",
            "checklist": "checklist",
        }
        uploaded = []
        for sel_key, file_key in upload_map.items():
            sel = self._sel("upload", sel_key)
            fname = manifest.files.get(file_key)
            if not sel or not fname:
                continue
            path = package_dir / fname
            if not path.is_file():
                continue
            loc = page.locator(sel)
            if await loc.count() == 0:
                continue
            await loc.first.set_input_files(str(path))
            uploaded.append(fname)
        return PortalActionResult(
            success=True,
            action="upload_files",
            message=f"Uploaded {len(uploaded)} files",
            details={"uploaded": uploaded},
        )

    async def save_draft(self, page: Any) -> PortalActionResult:
        # Check fee/contract before saving
        content = await page.content()
        text = await page.inner_text("body")
        try:
            stop_on_fee_or_contract(text, self.fee_keywords, self.contract_keywords)
        except Exception as exc:
            return PortalActionResult(
                success=False,
                action="save_draft",
                message=str(exc),
                blockers=["FEE_OR_CONTRACT"],
            )

        sel = self._sel("actions", "save_draft")
        if not sel:
            return PortalActionResult(
                success=False,
                action="save_draft",
                message="save_draft selector missing",
                blockers=["MISSING_SELECTOR"],
            )
        await page.locator(sel).first.click()
        indicator = self._sel("indicators", "draft_saved")
        draft_saved = False
        if indicator:
            try:
                await page.locator(indicator).first.wait_for(state="visible", timeout=5000)
                draft_saved = True
            except Exception:
                draft_saved = "draft" in (await page.content()).lower()
        else:
            draft_saved = True

        audit("portal_draft_saved", details={"adapter": self.name, "selectors_key": self.selectors_key})
        return PortalActionResult(
            success=True,
            action="save_draft",
            message="Draft saved",
            draft_saved=draft_saved,
            final_submitted=False,
        )

    async def detect_blockers(self, page: Any) -> PortalActionResult:
        text = await page.inner_text("body")
        blockers = []
        warnings = []
        fee_sel = self._sel("indicators", "fee_notice")
        contract_sel = self._sel("indicators", "contract_notice")
        if fee_sel and await page.locator(fee_sel).count() > 0:
            blockers.append("FEE_NOTICE_VISIBLE")
        if contract_sel and await page.locator(contract_sel).count() > 0:
            blockers.append("CONTRACT_NOTICE_VISIBLE")
        from app.safety import detect_fee_or_contract

        stop, hits = detect_fee_or_contract(text, self.fee_keywords, self.contract_keywords)
        if stop:
            blockers.extend([f"KEYWORD:{h}" for h in hits])
        return PortalActionResult(
            success=len(blockers) == 0,
            action="detect_blockers",
            blockers=blockers,
            warnings=warnings,
            message="ok" if not blockers else "blockers found",
        )

    async def final_submit(self, page: Any) -> PortalActionResult:
        # Hard refusal at adapter level — portal_runner must gate further
        return await super().final_submit(page)
