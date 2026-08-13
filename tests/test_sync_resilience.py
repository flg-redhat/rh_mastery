"""Sync and PDF discovery resilience tests."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rh_mastery import RHDocsMaster


@pytest.fixture
def master(tmp_path):
    cfg = tmp_path / "rh_config.json"
    cfg.write_text(
        '{"settings": {"base_url": "https://docs.redhat.com/en/documentation", '
        '"download_base": "."}, "tracked_products": {}}',
        encoding="utf-8",
    )
    storage = tmp_path / "rh_storage.json"
    storage.write_text('{"download_base": "' + str(tmp_path) + '"}', encoding="utf-8")
    m = RHDocsMaster(config_path=str(cfg), storage_config_path=str(storage))
    m.session = MagicMock()
    return m


def test_fetch_docs_page_returns_none_on_timeout(master):
    master.session.get.side_effect = TimeoutError("timed out")
    assert master._fetch_docs_page("https://example.test/doc") is None


def test_mirror_survives_fetch_failure(master):
    master._fetch_docs_page = MagicMock(return_value=None)
    assert master.mirror("red_hat_quay", "3.18") is False


def test_collect_html_topics_finds_relative_paths(master):
    html = """
    <a href="/html/apicurio_registry_user_guide">Guide</a>
    <a href="/en/documentation/red_hat_build_of_apicurio_registry/3.2/html/release_notes">RN</a>
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    topics = master._collect_html_topics(
        "red_hat_build_of_apicurio_registry",
        "3.2",
        soup,
        html,
    )
    assert "apicurio_registry_user_guide" in topics
    assert "release_notes" in topics


def test_is_documentation_hub(master):
    hub_html = """
    <a href="/en/documentation/red_hat_amq_broker/">AMQ</a>
    <a href="/en/documentation/red_hat_data_grid/">Data Grid</a>
    <a href="/en/documentation/red_hat_build_of_apache_camel/">Camel</a>
    """
    assert master._is_documentation_hub(
        "red_hat_application_foundations", "2024", hub_html
    )
