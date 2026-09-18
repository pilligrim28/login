"""Helpers for creating dotenv settings in tests."""

import json


def write_config(path, data):
    """Write nested test settings as pydantic-settings dotenv variables."""
    lines = []
    for section, values in data.items():
        for key, value in values.items():
            if isinstance(value, list):
                value = json.dumps(value)
            lines.append(f"{section.upper()}__{key.upper()}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
