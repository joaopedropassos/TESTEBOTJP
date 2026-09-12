#!/usr/bin/env python3
"""List Drive files under configured account (jp.criatividade@gmail.com)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.drive_client import (
    get_drive_service,
    list_drive_files,
    verify_authenticated_google_account,
)
from app.safety import verify_account_separation
from app.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory Google Drive files")
    parser.add_argument("--query", default="trashed=false", help="Drive API query")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    settings = get_settings()
    verify_account_separation(settings)

    service = get_drive_service(settings=settings)
    email = verify_authenticated_google_account(service, settings=settings)
    files = list_drive_files(service, query=args.query, page_size=min(args.limit, 100))
    files = files[: args.limit]

    if args.json:
        print(json.dumps({"account": email, "files": [f.model_dump() for f in files]}, indent=2))
    else:
        print(f"Drive account: {email}")
        print(f"Files: {len(files)}")
        for f in files:
            print(f"  {f.id}\t{f.name}\t{f.mime_type}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
