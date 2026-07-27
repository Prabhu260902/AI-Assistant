"""Derive plausible import-name fragments for a file path, for fuzzy
matching against stored import text (Phase 3's `Import.module_path`/
`raw_source`) — not exact import resolution, a disclosed heuristic.

Used in both directions: `impact_analysis.py` searches other files' imports
for a fragment of a *target* file (reverse: "who imports this file"), and
`architecture_graph.py` searches a *source* file's own imports for a
fragment matching a candidate file (forward: "what does this file's import
likely refer to").
"""

from pathlib import Path

MIN_FRAGMENT_LENGTH = 3


def fragments_for(file_path: str) -> list[str]:
    path = Path(file_path)
    stem = path.stem
    fragments = set()
    if len(stem) >= MIN_FRAGMENT_LENGTH:
        fragments.add(stem)
    if path.parent != Path("."):
        dotted = f"{path.parent.name}.{stem}"
        if len(dotted) >= MIN_FRAGMENT_LENGTH:
            fragments.add(dotted)
    return list(fragments)
