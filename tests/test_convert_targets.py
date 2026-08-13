"""Convert target resolution tests."""

import os
import sys
from argparse import Namespace

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rh_mastery import (
    get_aliases,
    has_partial_convert_selection,
    list_mirrored_products,
    resolve_convert_targets,
)


class FakeMaster:
    config = {
        "tracked_products": {
            "red_hat_offline_knowledge_portal": "1",
            "red_hat_quay": "3.18",
        }
    }


def _empty_args(**kwargs):
    base = {alias: False for alias in get_aliases()}
    base.update(
        {
            "all": False,
            "all_mirrored": False,
            "product": None,
            "force_version": None,
        }
    )
    base.update(kwargs)
    return Namespace(**base)


def test_list_mirrored_products_finds_offline_portal():
    base = os.path.join(ROOT, "Notebookml", "RHDocumentation")
    if not os.path.isdir(base):
        return
    found = list_mirrored_products(base, "markdown", "okf")
    slugs = {slug for slug, _ver in found}
    assert "red_hat_offline_knowledge_portal" in slugs
    assert len(found) > 5


def test_default_convert_targets_entire_mirror():
    base = os.path.join(ROOT, "Notebookml", "RHDocumentation")
    if not os.path.isdir(base):
        return
    args = _empty_args()
    assert has_partial_convert_selection(args) is False
    targets = resolve_convert_targets(args, FakeMaster(), base, "markdown", "okf")
    assert len(targets) == len(list_mirrored_products(base, "markdown", "okf"))


def test_resolve_convert_targets_all_mirrored_explicit():
    base = os.path.join(ROOT, "Notebookml", "RHDocumentation")
    if not os.path.isdir(base):
        return
    args = _empty_args(all_mirrored=True)
    targets = resolve_convert_targets(args, FakeMaster(), base, "markdown", "okf")
    assert len(targets) >= 1


def test_resolve_convert_targets_single_alias():
    base = os.path.join(ROOT, "Notebookml", "RHDocumentation")
    args = _empty_args(offline_knowledge_portal=True)
    assert has_partial_convert_selection(args) is True
    targets = resolve_convert_targets(args, FakeMaster(), base, "markdown", "okf")
    assert targets == [("red_hat_offline_knowledge_portal", "1")]


def test_resolve_convert_targets_all_tracked():
    base = os.path.join(ROOT, "Notebookml", "RHDocumentation")
    args = _empty_args(all=True)
    targets = resolve_convert_targets(args, FakeMaster(), base, "markdown", "okf")
    assert targets == [
        ("red_hat_offline_knowledge_portal", "1"),
        ("red_hat_quay", "3.18"),
    ]
