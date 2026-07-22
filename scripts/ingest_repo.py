#!/usr/bin/env python
"""CLI: ingest a repository (local path or git URL) into the vector store.

Usage (run from backend/, so its uv-managed deps are on the interpreter):
    cd backend
    uv run python ../scripts/ingest_repo.py <path-or-url> [--repo-id NAME]
"""

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.ingest import ingest_repository  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a repository into the vector store.")
    parser.add_argument("source", help="Local path or git URL of the repository to ingest")
    parser.add_argument("--repo-id", default=None, help="Override the derived repo/collection id")
    args = parser.parse_args()

    summary = ingest_repository(args.source, repo_id=args.repo_id)

    print(f"repo_id:        {summary.repo_id}")
    print(f"files_scanned:  {summary.files_scanned}")
    print(f"files_indexed:  {summary.files_indexed}")
    print(f"files_skipped:  {summary.files_skipped}")
    print(f"chunks_indexed: {summary.chunks_indexed}")


if __name__ == "__main__":
    main()
