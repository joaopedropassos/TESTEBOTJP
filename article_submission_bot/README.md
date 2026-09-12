# article_submission_bot

Safe academic manuscript submission assistant for **João Pedro Pereira Passos**.

**Defaults (hard):** `DRY_RUN=true`, `SAVE_DRAFT=true`, `ALLOW_FINAL_SUBMISSION=false`.  
**No real auto-submit.** Final submission requires interactive confirmation, a temp auth file with the package hash, and still does not automate the final portal click.

## Identity rules (do not mix)

| Role | Account |
|------|---------|
| Author / corresponding / institutional / Gmail editorial | `joaopedro.passos@mail.uft.edu.br` |
| Google Drive / files | `jp.criatividade@gmail.com` |

- Separate OAuth **clients**, **tokens**, and **scopes** per service.
- Verify authenticated email per service before any API call.
- Never use the Drive account as corresponding email (or vice-versa).

## Stack

Python 3.11+, async Playwright, FastAPI, Pydantic, SQLAlchemy+SQLite, Google Drive/Gmail APIs, google-auth-oauthlib, python-docx, pypdf/PyMuPDF, PyYAML, pytest, structlog.

## Install

```bash
cd article_submission_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
playwright install chromium
cp .env.example .env
cp config/journals.example.yaml config/journals.yaml
cp config/selectors.example.yaml config/selectors.yaml
```

### Verify (no live Google credentials required)

```bash
pytest -q
python scripts/verify_environment.py
```

### Optional scripts

```bash
python scripts/fill_author_data.py --json
python scripts/build_package.py --manuscript-code MS-001 --journal-code example_journal --source path/to/paper.docx
# Requires live Drive OAuth (jp.criatividade@gmail.com):
python scripts/inventory_drive.py --json
```

### API

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- `GET /health` — safety flags  
- `GET /author` — author.yaml  
- `GET /journals` — journal configs  
- `POST /packages/build` — build package  
- `POST /pre-submit-report` — human review report  
- `POST /prepare-draft` — portal draft only (`final_submitted` always false)  
- `POST /confirmations` — issue confirmation phrase + temp auth file  
- `POST /final-submit` — **403** unless `ALLOW_FINAL_SUBMISSION=true`, not dry-run, valid phrase, matching auth file; even then automated final click is **not** performed  

## OAuth — two accounts

1. **Drive** (`secrets/drive_client_secrets.json` → `secrets/drive_token.json`)  
   - Account: `jp.criatividade@gmail.com`  
   - Scopes: Drive readonly (see `.env.example`)  

2. **Gmail** (`secrets/gmail_client_secrets.json` → `secrets/gmail_token.json`)  
   - Account: `joaopedro.passos@mail.uft.edu.br`  
   - Scopes: gmail.compose + gmail.readonly  
   - **Drafts only — never send**

Place client secrets under `secrets/` (gitignored). Run flows via the respective clients; `verify_authenticated_google_account` enforces email per service.

## Dry-run / draft mode

With defaults:

- Packages are built locally under `data/packages/`.
- Portal runner may open a page and **save a draft** when `SAVE_DRAFT=true`.
- `/final-submit` returns **403**.
- Gmail helpers only create **drafts**.

## Human intervention list

Before any real submission:

1. Review blinded manuscript for residual identifiers.  
2. Confirm author order with all co-authors (order is never auto-reordered).  
3. Verify APC / copyright / license terms on the journal site.  
4. Complete CAPTCHA / 2FA in the portal if prompted.  
5. Fill empty optional fields (institution, ORCID, etc.) only with verified data — the bot **never invents** them.  
6. Issue confirmation phrase and temp auth file only when intentionally enabling final submission.  
7. Perform the final portal click **manually**.

## Security checklist

- [ ] `DRY_RUN=true` unless explicitly overridden  
- [ ] `ALLOW_FINAL_SUBMISSION=false` in normal operation  
- [ ] Drive ≠ institutional email; OAuth clients/tokens/scopes separated  
- [ ] Corresponding email is `joaopedro.passos@mail.uft.edu.br`  
- [ ] Authorship order preserved  
- [ ] Fee/contract keywords stop automation  
- [ ] Simultaneous submissions blocked  
- [ ] Confirmation phrase + TTL + package-hash auth file  
- [ ] Audit logs redact secrets  
- [ ] No Gmail send; drafts only  
- [ ] Adapters refuse `final_submit`  

## Confirmation phrase

```text
CONFIRMO O ENVIO DO MANUSCRITO [CODE] AO PERIÓDICO [NAME], USANDO O PACOTE [HASH]
```

TTL default: 900 seconds. Changing the package hash invalidates the confirmation.

## Pre-submit report example

```json
{
  "manuscript_code": "MS-001",
  "journal_code": "example_journal",
  "journal_name": "Example Open Access Journal",
  "package_hash": "…",
  "corresponding_email": "joaopedro.passos@mail.uft.edu.br",
  "drive_account": "jp.criatividade@gmail.com",
  "dry_run": true,
  "save_draft": true,
  "allow_final_submission": false,
  "author_order": ["João Pedro Pereira Passos"],
  "files": {
    "identified": "MS-001_identified.docx",
    "blinded": "MS-001_blinded.docx",
    "title_page": "MS-001_title_page.docx",
    "cover_letter": "MS-001_cover_letter.docx",
    "checklist": "MS-001_checklist.docx",
    "requirements_snapshot": "requirements_snapshot.json",
    "manifest": "manifest.json"
  },
  "blockers": [],
  "warnings": ["DRY_RUN=true — no live portal mutations expected beyond explicit draft flow"],
  "human_interventions": [
    "Review blinded manuscript for residual identifiers",
    "Confirm author order with all co-authors",
    "Verify journal APC / copyright terms manually",
    "Complete any CAPTCHA or 2FA in the portal",
    "Confirm institutional affiliation fields if required by journal"
  ],
  "ready_for_draft": true
}
```

## Project layout

See repository tree: `app/`, `config/`, `scripts/`, `tests/`, `data/`, `storage/`.

## License

MIT — Author: João Pedro Pereira Passos  
Corresponding: joaopedro.passos@mail.uft.edu.br
