"""Rule file loaders for data/rules/*.yaml and *.md."""

from __future__ import annotations

from pathlib import Path

import yaml

_RULES_DIR = Path(__file__).resolve().parents[3] / "data" / "rules"


def load_rules(name: str) -> dict | str:
    """Load a rule file by name (without extension).

    Tries .yaml first, then .md. YAML files are returned as dicts;
    Markdown files are returned as the raw text string.
    """
    yaml_path = _RULES_DIR / f"{name}.yaml"
    md_path = _RULES_DIR / f"{name}.md"

    if yaml_path.exists():
        with open(yaml_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    if md_path.exists():
        return md_path.read_text(encoding="utf-8")

    raise FileNotFoundError(
        f"No rule file found for '{name}' in {_RULES_DIR}. "
        f"Looked for {yaml_path.name} and {md_path.name}."
    )


def load_yaml_rules(name: str) -> dict:
    """Load a YAML rule file by name. Raises if not found or not YAML."""
    path = _RULES_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Rule file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_md_rules(name: str) -> str:
    """Load a Markdown rule file by name. Raises if not found."""
    path = _RULES_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Rule file not found: {path}")
    return path.read_text(encoding="utf-8")


def rules_dir() -> Path:
    """Return the path to the rules directory."""
    return _RULES_DIR
