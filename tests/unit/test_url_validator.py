from __future__ import annotations

import pytest

from app.config import Settings
from app.core.exceptions import URLNotAllowedError, URLValidationError
from app.services.url_validator import enforce_ssrf_guard, validate_url_structure


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


class TestValidateUrlStructure:
    def test_accepts_valid_https_url(self, settings: Settings) -> None:
        result = validate_url_structure("https://example.com/path", settings)
        assert result == "https://example.com/path"

    def test_accepts_valid_http_url(self, settings: Settings) -> None:
        result = validate_url_structure("http://example.com", settings)
        assert result.startswith("http://example.com")

    def test_rejects_empty_url(self, settings: Settings) -> None:
        with pytest.raises(URLValidationError):
            validate_url_structure("", settings)

    def test_rejects_whitespace_only_url(self, settings: Settings) -> None:
        with pytest.raises(URLValidationError):
            validate_url_structure("   ", settings)

    def test_rejects_disallowed_scheme(self, settings: Settings) -> None:
        with pytest.raises(URLValidationError):
            validate_url_structure("ftp://example.com", settings)

    def test_rejects_javascript_scheme(self, settings: Settings) -> None:
        with pytest.raises(URLValidationError):
            validate_url_structure("javascript:alert(1)", settings)

    def test_rejects_url_missing_hostname(self, settings: Settings) -> None:
        with pytest.raises(URLValidationError):
            validate_url_structure("https:///path-only", settings)

    def test_rejects_url_exceeding_max_length(self, settings: Settings) -> None:
        long_url = "https://example.com/" + "a" * 3000
        with pytest.raises(URLValidationError):
            validate_url_structure(long_url, settings)


class TestSsrfGuard:
    def test_blocks_localhost_hostname(self, settings: Settings) -> None:
        with pytest.raises(URLNotAllowedError):
            enforce_ssrf_guard("http://localhost:8080/", settings)

    def test_blocks_loopback_ip_literal(self, settings: Settings) -> None:
        with pytest.raises(URLNotAllowedError):
            enforce_ssrf_guard("http://127.0.0.1/", settings)

    def test_blocks_private_ip_literal(self, settings: Settings) -> None:
        with pytest.raises(URLNotAllowedError):
            enforce_ssrf_guard("http://10.0.0.5/", settings)

    def test_blocks_link_local_metadata_ip(self, settings: Settings) -> None:
        with pytest.raises(URLNotAllowedError):
            enforce_ssrf_guard("http://169.254.169.254/latest/meta-data/", settings)

    def test_allows_public_hostname(self, settings: Settings) -> None:
        # example.com is IANA-reserved for documentation and always
        # resolves publicly, so this is safe to assert without network
        # flakiness concerns in CI.
        enforce_ssrf_guard("https://example.com/", settings)

    def test_guard_is_bypassable_via_settings_flag(self) -> None:
        permissive_settings = Settings(_env_file=None, block_private_networks=False)
        # Should not raise even for a private IP when the guard is disabled.
        enforce_ssrf_guard("http://127.0.0.1/", permissive_settings)
