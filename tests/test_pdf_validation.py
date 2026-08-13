"""PDF validation helpers."""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rh_mastery import is_valid_pdf, pdf_problem


def test_is_valid_pdf_real_file():
    path = os.path.join(
        ROOT,
        "Notebookml/RHDocumentation/red_hat_offline_knowledge_portal/1/"
        "Red_Hat_Offline_Knowledge_Portal-1-What_is_the_Red_Hat_Offline_Knowledge_Portal-en-US.pdf",
    )
    if os.path.exists(path):
        assert is_valid_pdf(path)
        assert pdf_problem(path) is None


def test_is_valid_pdf_xml_error_page():
    path = os.path.join(
        ROOT,
        "Notebookml/RHDocumentation/red_hat_offline_knowledge_portal/1/rhokp-discover-1-0-pdf.pdf",
    )
    if os.path.exists(path):
        assert not is_valid_pdf(path)
        assert pdf_problem(path) is not None
        assert "re-sync" in pdf_problem(path)
