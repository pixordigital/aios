"""SSRF guard tests.

Regression: etl_url had no SSRF protection at all — it followed redirects
blindly and would fetch http://169.254.169.254/ or internal services, then
index the body into the knowledge base where an agent could read it back.
http_get and http_request each had their own copy of the blocklist; they now
share aios.tools.ssrf.
"""

import pytest

from aios.tools.ssrf import check_url, is_private_host


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.0.0.1:8777/health",
        "http://localhost/",
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://[::1]/",
        "http://0.0.0.0/",
        "http://100.64.0.1/",  # CGNAT
    ],
)
def test_internal_targets_blocked(url):
    assert check_url(url) is not None, f"{url} should be blocked"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/",
        "gopher://example.com/",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
    ],
)
def test_non_http_schemes_blocked(url):
    assert check_url(url) is not None


def test_public_url_allowed():
    assert check_url("https://example.com/") is None


def test_allow_private_override():
    assert check_url("http://127.0.0.1/", allow_private=True) is None


def test_fails_closed_on_unresolvable_host():
    assert is_private_host("this-host-does-not-exist.invalid") is True
    assert check_url("https://this-host-does-not-exist.invalid/") is not None

def test_no_hostname():
    assert check_url("http://") is not None


def test_etl_url_imports_guard():
    import aios.tools.etl_url as m

    src = open(m.__file__).read()
    assert "check_url" in src, "etl_url must guard URLs"
    assert "follow_redirects=True" not in src, "etl_url must not follow redirects blindly"


def test_http_get_uses_shared_guard():
    import aios.tools.http_get as m

    src = open(m.__file__).read()
    assert "from aios.tools.ssrf import" in src
