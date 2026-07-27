#!/usr/bin/env python
"""CLI: ingest a repository (local path or git URL) — indexes it into the
vector store and extracts its knowledge graph (imports/symbols/calls/API
endpoints) into Postgres.

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
from services.knowledge_graph import build_knowledge_graph  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a repository into the vector store and knowledge graph.")
    parser.add_argument("source", help="Local path or git URL of the repository to ingest")
    parser.add_argument("--repo-id", default=None, help="Override the derived repo/collection id")
    args = parser.parse_args()

    vector_summary = ingest_repository(args.source, repo_id=args.repo_id)
    graph_summary = build_knowledge_graph(args.source, repo_id=vector_summary.repo_id)

    print(f"repo_id:        {vector_summary.repo_id}")
    print("--- vector index ---")
    print(f"files_scanned:  {vector_summary.files_scanned}")
    print(f"files_indexed:  {vector_summary.files_indexed}")
    print(f"files_skipped:  {vector_summary.files_skipped}")
    print(f"chunks_indexed: {vector_summary.chunks_indexed}")
    print("--- knowledge graph ---")
    print(f"files:          {graph_summary.files}")
    print(f"symbols:        {graph_summary.symbols}")
    print(f"imports:        {graph_summary.imports}")
    print(f"calls:          {graph_summary.calls}")
    print(f"endpoints:      {graph_summary.endpoints}")


if __name__ == "__main__":
    main()
