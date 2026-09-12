#!/usr/bin/env python3
"""Build a submission package from a local manuscript file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.package_builder import build_package
from app.safety import verify_account_separation
from app.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Build manuscript submission package")
    parser.add_argument("--manuscript-code", required=True)
    parser.add_argument("--journal-code", required=True)
    parser.add_argument("--source", required=True, help="Path to manuscript file")
    parser.add_argument("--identified", default=None)
    parser.add_argument("--out", default=None, help="Output directory")
    args = parser.parse_args()

    settings = get_settings()
    verify_account_separation(settings)
    out = Path(args.out) if args.out else None
    manifest = build_package(
        args.manuscript_code,
        args.journal_code,
        Path(args.source),
        identified_file=Path(args.identified) if args.identified else None,
        output_dir=out,
    )
    print(json.dumps(manifest.model_dump(mode="json"), indent=2, default=str))
    print(f"\nPackage hash: {manifest.package_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
