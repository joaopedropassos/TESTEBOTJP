#!/usr/bin/env python3
"""Validate and display author.yaml — never invent missing fields."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.package_builder import load_author_config
from app.safety import preserve_author_order, validate_author_config
from app.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate author config")
    parser.add_argument("--config", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    path = Path(args.config) if args.config else settings.author_config_path
    author = load_author_config(path)
    gaps = validate_author_config(author)
    ordered = preserve_author_order(author.authors)

    payload = {
        "author": author.model_dump(mode="json"),
        "author_order": [a.full_name for a in ordered],
        "gaps": gaps,
        "notes": (
            "Empty optional fields are intentional. "
            "Do not invent institution/ORCID/etc. "
            "Author order is preserved as declared."
        ),
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Full name: {author.full_name}")
        print(f"Corresponding: {author.corresponding_email}")
        print(f"Country: {author.country}")
        print("Authors (order preserved):")
        for a in ordered:
            print(f"  {a.order}. {a.full_name} corresponding={a.corresponding}")
        print("Gaps (empty optional fields):")
        for g in gaps:
            print(f"  - {g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
