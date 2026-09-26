import json
import re
from pathlib import Path

ROOT = Path(__file__).with_name("profiles")


def catalog(extra=None):
    result = {"boards": {}, "systems": {}}
    for root in [ROOT] + ([Path(extra)] if extra else []):
        for kind in result:
            for path in sorted((root / kind).glob("*.json")):
                item = json.loads(path.read_text())
                if not re.fullmatch(r"[a-z0-9-]{1,64}", item.get("id", "")) or not isinstance(item.get("name"), str):
                    raise ValueError(f"Invalid {kind} profile")
                result[kind][item["id"]] = item
    return {kind: list(items.values()) for kind, items in result.items()}


def profile(kind, name, extra=None):
    return next((p for p in catalog(extra)[kind] if p["id"] == name), None)
