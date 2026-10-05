"""The review page is served safely and its script never builds HTML from document data."""

import re
from pathlib import Path

STATIC = Path(__file__).parent.parent / "kyc" / "static"

# APIs that would turn untrusted text into markup or code.
FORBIDDEN_JS = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "eval(",
    "new Function",
    'setAttribute("style"',
    "setAttribute('style'",
)


def test_page_is_served_with_a_strict_csp(make_client):
    with make_client() as client:
        r = client.get("/ui")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert "frame-ancestors 'none'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"


def test_page_has_no_inline_script_or_style():
    html = (STATIC / "ui.html").read_text()
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)  # only external scripts
    assert "<style" not in html and 'style="' not in html
    assert " onclick=" not in html and " onload=" not in html


def test_script_never_builds_html_from_data():
    js = (STATIC / "app.js").read_text()
    for banned in FORBIDDEN_JS:
        assert banned not in js, f"{banned} must not be used in the review page"


def test_assets_are_served(make_client):
    with make_client() as client:
        js = client.get("/ui/app.js")
        css = client.get("/ui/style.css")
        root = client.get("/").json()
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    assert root["ui"] == "/ui"


def test_page_is_open_but_the_api_behind_it_needs_the_key(make_client):
    with make_client(api_key="test-key-not-a-secret") as client:  # gitleaks:allow
        assert client.get("/ui").status_code == 200
        assert client.get("/documents").status_code == 401
