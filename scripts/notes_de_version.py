"""Notes d'une version, tirées de CHANGELOG.md, et contrôle tag = version du manifest.

Usage : python scripts/notes_de_version.py v0.1.0 > notes.md
Code de sortie 1 si le tag ne correspond pas à manifest.json ou si la version manque au journal.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from loguru import logger

RACINE = Path(__file__).resolve().parents[1]


def version_manifest() -> str:
    logger.debug("version_manifest() called")
    version = json.loads(
        (RACINE / "custom_components/ginko_trafic/manifest.json").read_text(encoding="utf-8")
    )["version"]
    logger.debug("version_manifest() returning | {}", version)
    return version


def notes(version: str, journal: str) -> str:
    """Section ``## [version]`` du journal, sans son titre."""
    logger.debug("notes() called | version={}", version)
    motif = re.compile(rf"^## \[{re.escape(version)}\].*?$(.*?)(?=^## \[|\Z)", re.MULTILINE | re.DOTALL)
    trouve = motif.search(journal)
    if trouve is None or not trouve.group(1).strip():
        logger.error("version {} absente de CHANGELOG.md", version)
        raise ValueError(f"version {version} absente de CHANGELOG.md")
    texte = trouve.group(1).strip() + "\n"
    logger.debug("notes() returning | {} caractère(s)", len(texte))
    return texte


def main(argv: list[str]) -> int:
    logger.debug("main() called | {} argument(s)", len(argv))
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        logger.debug("main() returning | 2 (arguments incorrects)")
        return 2
    version = argv[1].removeprefix("v")
    if version != version_manifest():
        print(f"tag v{version} ≠ manifest.json {version_manifest()}", file=sys.stderr)
        logger.debug("main() returning | 1 (tag ≠ manifest)")
        return 1
    try:
        sys.stdout.write(notes(version, (RACINE / "CHANGELOG.md").read_text(encoding="utf-8")))
    except ValueError as err:
        print(err, file=sys.stderr)
        logger.debug("main() returning | 1 (version absente du journal)")
        return 1
    logger.debug("main() returning | 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
