import pytest

from triage_core.findings import is_test_path, normalise_cwe, title_from_message
from triage_core.redaction import REDACTED, redact_secrets


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_app.py",
        "src/__tests__/a.js",
        "app/user.spec.ts",
        "pkg/foo_test.py",
        "conftest.py",
        "test/server/api.js",
        "cypress/e2e/login.cy.ts",
    ],
)
def test_test_paths_are_detected(path: str) -> None:
    assert is_test_path(path)


@pytest.mark.parametrize(
    "path", ["routes/login.ts", "lib/insecurity.ts", "src/testimonials.py", "contest/app.py"]
)
def test_production_paths_are_not_test_code(path: str) -> None:
    assert not is_test_path(path)


def test_title_is_first_sentence() -> None:
    message = "Detected SQL built from user input. Use parameterized queries instead."
    assert title_from_message(message, "rule") == "Detected SQL built from user input."
    assert title_from_message("   ", "rule.id") == "rule.id"


def test_cwe_ids_are_extracted() -> None:
    assert normalise_cwe(["CWE-89: Improper Neutralization", "CWE-89: dup"]) == ["CWE-89"]
    assert normalise_cwe("CWE-79: XSS") == ["CWE-79"]
    assert normalise_cwe(None) == []


@pytest.mark.parametrize(
    "secret",
    [
        "AKIAIOSFODNN7EXAMPLE",
        "ghp_" + "a1B2" * 9,
        "xoxb-1234567890-abcdefghij",
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----",
    ],
)
def test_known_secret_formats_are_redacted(secret: str) -> None:
    redacted = redact_secrets(f"key = {secret}\n")
    assert secret not in redacted
    assert REDACTED in redacted


def test_credential_assignments_are_redacted_but_code_shape_kept() -> None:
    redacted = redact_secrets('const password = "hunter2hunter2";')
    assert redacted == f'const password = "{REDACTED}";'


def test_high_entropy_strings_are_redacted_but_ordinary_strings_kept() -> None:
    random_key = "q8Zr3LmX0vB7tKp2Wn5Ys9Hd4Jf6Gc1A"
    assert random_key not in redact_secrets(f'key("{random_key}")')
    sql = '"SELECT * FROM users WHERE email = ?"'
    assert redact_secrets(sql) == sql
