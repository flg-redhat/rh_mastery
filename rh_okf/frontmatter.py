"""OKF v0.2 YAML frontmatter builders."""

from __future__ import annotations

import json
from typing import Any, Mapping


def yaml_quote(value: str) -> str:
    return json.dumps(value)


def format_yaml_value(value: Any, indent: int = 0) -> str:
    """Render a Python value as YAML (subset sufficient for OKF frontmatter)."""
    sp = " " * indent
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return yaml_quote(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        if all(isinstance(x, str) for x in value):
            inner = ", ".join(yaml_quote(x) for x in value)
            return f"[{inner}]"
        lines = []
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{sp}- {_inline_dict(item)}")
            else:
                lines.append(f"{sp}- {format_yaml_value(item)}")
        return "\n".join(lines)
    if isinstance(value, dict):
        lines = []
        for k, v in value.items():
            if isinstance(v, dict):
                lines.append(f"{sp}{k}:")
                for sk, sv in v.items():
                    lines.append(f"{sp}  {sk}: {format_yaml_value(sv)}")
            elif isinstance(v, list):
                lines.append(f"{sp}{k}:")
                for item in v:
                    if isinstance(item, dict):
                        lines.append(f"{sp}  - {_inline_dict(item)}")
                    else:
                        lines.append(f"{sp}  - {format_yaml_value(item)}")
            else:
                lines.append(f"{sp}{k}: {format_yaml_value(v)}")
        return "\n".join(lines)
    return yaml_quote(str(value))


def _inline_dict(d: Mapping[str, Any]) -> str:
    parts = [f"{k}: {format_yaml_value(v)}" for k, v in d.items()]
    return "{ " + ", ".join(parts) + " }"


def render_frontmatter(fields: Mapping[str, Any]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, dict):
            lines.append(f"{key}:")
            for sk, sv in value.items():
                lines.append(f"  {sk}: {format_yaml_value(sv)}")
        elif isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                if isinstance(item, dict):
                    lines.append("  -")
                    for sk, sv in item.items():
                        lines.append(f"    {sk}: {format_yaml_value(sv)}")
                else:
                    lines.append(f"  - {format_yaml_value(item)}")
        else:
            lines.append(f"{key}: {format_yaml_value(value)}")
    lines.append("---")
    return "\n".join(lines)


def wrap_concept(fields: Mapping[str, Any], body: str) -> str:
    b = (body or "").strip()
    fm = render_frontmatter(fields)
    return f"{fm}\n\n{b}\n" if b else f"{fm}\n"


def first_sentence(text: str, *, max_len: int = 240) -> str:
    t = " ".join((text or "").split())
    if not t:
        return ""
    for end in (". ", ".\n", "."):
        if end in t:
            sent = t.split(end, 1)[0] + "."
            if len(sent) <= max_len:
                return sent
    if len(t) <= max_len:
        return t
    return t[: max_len - 3].rstrip() + "..."
