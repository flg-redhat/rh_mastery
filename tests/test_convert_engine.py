"""Tests for convert engine resolution."""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rh_mastery import fips_mode_enabled, resolve_convert_engine


def test_fips_mode_enabled_on_this_host():
    # CI/RHEL FIPS hosts expose /proc/sys/crypto/fips_enabled
    val = fips_mode_enabled()
    assert isinstance(val, bool)


def test_okf_defaults_to_docling_off_fips(monkeypatch):
    monkeypatch.setattr("rh_mastery.fips_mode_enabled", lambda: False)
    assert resolve_convert_engine("okf", None) == "docling"


def test_okf_falls_back_to_pymupdf_on_fips(monkeypatch):
    monkeypatch.setattr("rh_mastery.fips_mode_enabled", lambda: True)
    assert resolve_convert_engine("okf", None) == "pymupdf"


def test_explicit_docling_rejected_on_fips(monkeypatch):
    monkeypatch.setattr("rh_mastery.fips_mode_enabled", lambda: True)
    assert resolve_convert_engine("okf", "docling") is None


def test_markdown_defaults_to_pymupdf(monkeypatch):
    monkeypatch.setattr("rh_mastery.fips_mode_enabled", lambda: True)
    assert resolve_convert_engine("markdown", None) == "pymupdf"
