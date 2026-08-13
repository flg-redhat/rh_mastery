"""Unit tests for OKF helpers."""

import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rh_okf.bundle import build_guide_bundle
from rh_okf.frontmatter import render_frontmatter
from rh_okf.index import render_global_index, render_guide_index
from rh_okf.links import slugify
from rh_okf.types import infer_concept_type


FIXTURE_MD = os.path.join(ROOT, "tests", "fixtures", "md", "sample-install.md")


def test_slugify():
    assert slugify("Installing the Controller!") == "installing-the-controller"


def test_type_heuristic_procedure():
    assert infer_concept_type("Installing the controller", "1. step\n2. step\n3. step") == "Procedure"


def test_frontmatter_v02():
    fm = render_frontmatter(
        {
            "type": "Procedure",
            "title": "Install",
            "generated": {"by": "process:rh-mastery", "at": "2026-08-13T10:00:00Z"},
            "sources": [{"id": "source-md", "resource": "../markdown/x.md", "title": "x"}],
        }
    )
    assert 'type: "Procedure"' in fm
    assert "generated:" in fm
    assert "sources:" in fm


def test_index_generation():
    idx = render_guide_index(
        [{"title": "Install", "description": "Steps", "filename": "install"}]
    )
    assert "* [Install](install.md)" in idx


def test_build_guide_bundle_integration():
    with tempfile.TemporaryDirectory() as tmp:
        bundle_root = os.path.join(tmp, "okf")
        info = build_guide_bundle(
            FIXTURE_MD,
            bundle_root=bundle_root,
            slug="red_hat_sample_product",
            version="1.0",
            guide_stem="sample-install-pdf",
            base_url="https://docs.redhat.com/en/documentation",
            force=True,
        )
        assert info["concept_count"] >= 2
        guide_dir = os.path.join(bundle_root, "red_hat_sample_product", "1.0", "sample-install-pdf")
        assert os.path.exists(os.path.join(guide_dir, "guide.md"))
        assert os.path.exists(os.path.join(guide_dir, "index.md"))
        for name in os.listdir(guide_dir):
            if name.endswith(".md") and name not in ("index.md",):
                with open(os.path.join(guide_dir, name), encoding="utf-8") as f:
                    text = f.read()
                assert text.startswith("---")
                assert "type:" in text.split("---")[1]


def test_manifest_skip():
    with tempfile.TemporaryDirectory() as tmp:
        bundle_root = os.path.join(tmp, "okf")
        kwargs = dict(
            bundle_root=bundle_root,
            slug="red_hat_sample_product",
            version="1.0",
            guide_stem="sample-install-pdf",
            base_url="https://docs.redhat.com/en/documentation",
        )
        build_guide_bundle(FIXTURE_MD, force=True, **kwargs)
        second = build_guide_bundle(FIXTURE_MD, force=False, **kwargs)
        assert second.get("skipped") is True


def test_force_rebuild():
    with tempfile.TemporaryDirectory() as tmp:
        bundle_root = os.path.join(tmp, "okf")
        kwargs = dict(
            bundle_root=bundle_root,
            slug="red_hat_sample_product",
            version="1.0",
            guide_stem="sample-install-pdf",
            base_url="https://docs.redhat.com/en/documentation",
        )
        build_guide_bundle(FIXTURE_MD, force=True, **kwargs)
        second = build_guide_bundle(FIXTURE_MD, force=True, **kwargs)
        assert second.get("skipped") is not True


def test_global_index():
    content = render_global_index(
        [{"slug": "red_hat_sample_product", "version": "1.0"}],
        okf_version="0.2",
    )
    assert 'okf_version: "0.2"' in content
    assert "red_hat_sample_product/1.0/index.md" in content
