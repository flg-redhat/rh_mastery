"""Unit tests for OKF chunking."""

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rh_okf.chunk import split_markdown_body


def test_chunk_h2_basic():
    body = "## Alpha\n\nOne.\n\n## Beta\n\nTwo.\n"
    chunks = split_markdown_body(body, heading_level=2, max_concept_chars=0)
    titled = [c for c in chunks if c.title]
    assert len(titled) == 2
    assert titled[0].title == "Alpha"
    assert "One." in titled[0].body
    assert titled[1].title == "Beta"


def test_chunk_no_split_in_code():
    body = "## Install\n\n```bash\necho '## not a heading'\n```\n\nDone.\n"
    chunks = split_markdown_body(body, heading_level=2, max_concept_chars=0)
    install = [c for c in chunks if c.title == "Install"][0]
    assert "## not a heading" in install.body
    assert len([c for c in chunks if c.title]) == 1


def test_chunk_overflow():
    para = "word " * 3000
    body = f"## Big section\n\n{para}\n"
    chunks = split_markdown_body(body, heading_level=2, max_concept_chars=500)
    parts = [c for c in chunks if c.title and "part" in (c.title or "")]
    assert len(parts) >= 2
    assert "Continued in" in parts[0].body or "Continued from" in parts[1].body
