"""Scanner output parsing and clone-sandbox rules (no binaries or network needed)."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from triage_core.domain import Severity, Tool
from triage_core.settings import Settings
from triage_worker.errors import PermanentJobError
from triage_worker.process import ProcessTimeoutError, run
from triage_worker.sandbox import clone_args, enforce_limits
from triage_worker.scanners.osv import parse_osv
from triage_worker.scanners.semgrep import parse_semgrep, rule_id

RULES = Path("/opt/semgrep-rules")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "routes").mkdir()
    (tmp_path / "routes" / "search.ts").write_text(
        "import db from './db'\n"
        "export function search(req, res) {\n"
        "  const q = req.query.q\n"
        '  return db.query("SELECT * FROM products WHERE name LIKE \'%" + q + "%\'")\n'
        "}\n"
    )
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "helper.js").write_text("eval(x)\n")
    lockfile = {"packages": {"lodash": {"version": "4.17.4"}}}
    (tmp_path / "package-lock.json").write_text(json.dumps(lockfile, indent=2))
    return tmp_path


def _semgrep_result(path: str, line: int, **extra: Any) -> dict[str, Any]:
    return {
        "check_id": "opt.semgrep-rules.typescript.sequelize.security.audit.sqli",
        "path": path,
        "start": {"line": line, "col": 3},
        "end": {"line": line, "col": 80},
        "extra": {
            "message": "Detected a raw SQL query built from user input. Use bind parameters.",
            "severity": "ERROR",
            "lines": "requires login",
            "metadata": {"cwe": ["CWE-89: Improper Neutralization of SQL"], "impact": "HIGH"},
            **extra,
        },
    }


def test_semgrep_results_become_findings_with_real_snippets(repo: Path) -> None:
    data = {"results": [_semgrep_result("routes/search.ts", 4)], "errors": []}

    [finding] = parse_semgrep(data, repo, RULES)

    assert finding.tool is Tool.SEMGREP
    assert finding.rule_id == "typescript.sequelize.security.audit.sqli"
    assert finding.title == "Detected a raw SQL query built from user input."
    assert finding.cwe == ["CWE-89"]
    assert finding.scanner_severity is Severity.HIGH
    assert "SELECT * FROM products" in finding.snippet  # read from the file, not "requires login"
    assert finding.is_test_code is False


def test_semgrep_critical_needs_high_impact_and_likelihood(repo: Path) -> None:
    result = _semgrep_result("routes/search.ts", 4)
    result["extra"]["metadata"]["likelihood"] = "HIGH"

    [finding] = parse_semgrep({"results": [result]}, repo, RULES)

    assert finding.scanner_severity is Severity.CRITICAL


def test_semgrep_marks_test_code_and_drops_paths_outside_the_clone(repo: Path) -> None:
    data = {
        "results": [
            _semgrep_result("test/helper.js", 1, severity="WARNING"),
            _semgrep_result("../../etc/passwd", 1),
            _semgrep_result("/etc/passwd", 1),
        ]
    }

    findings = parse_semgrep(data, repo, RULES)

    assert [f.file_path for f in findings] == ["test/helper.js"]
    assert findings[0].is_test_code
    assert findings[0].scanner_severity is Severity.MEDIUM


def test_rule_ids_do_not_depend_on_install_location() -> None:
    assert rule_id("opt.semgrep-rules.python.flask.xss", Path("/opt/semgrep-rules")) == (
        "python.flask.xss"
    )
    assert rule_id("python.flask.xss", Path("/opt/semgrep-rules")) == "python.flask.xss"


OSV_OUTPUT = {
    "results": [
        {
            "source": {"path": "package-lock.json", "type": "lockfile"},
            "packages": [
                {
                    "package": {"name": "lodash", "version": "4.17.4", "ecosystem": "npm"},
                    "vulnerabilities": [
                        {
                            "id": "GHSA-jf85-cpcp-j695",
                            "aliases": ["CVE-2019-10744"],
                            "summary": "Prototype Pollution in lodash",
                            "affected": [
                                {
                                    "package": {"name": "lodash", "ecosystem": "npm"},
                                    "ranges": [
                                        {"events": [{"introduced": "0"}, {"fixed": "4.17.12"}]}
                                    ],
                                }
                            ],
                            "database_specific": {"severity": "CRITICAL", "cwe_ids": ["CWE-1321"]},
                        },
                        {"id": "CVE-2019-10744", "summary": "dup"},
                    ],
                    "groups": [
                        {"ids": ["CVE-2019-10744", "GHSA-jf85-cpcp-j695"], "max_severity": "9.1"}
                    ],
                }
            ],
        }
    ]
}


def test_osv_groups_aliases_into_one_finding(repo: Path) -> None:
    [finding] = parse_osv(OSV_OUTPUT, repo)

    assert finding.tool is Tool.OSV
    assert finding.rule_id == "GHSA-jf85-cpcp-j695"
    assert finding.package == "lodash"
    assert finding.installed_version == "4.17.4"
    assert finding.fixed_version == "4.17.12"
    assert finding.scanner_severity is Severity.CRITICAL
    assert finding.cwe == ["CWE-1321"]
    assert finding.title.startswith("lodash 4.17.4: Prototype Pollution")
    assert finding.start_line == 3  # line of "lodash" in the lockfile


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        ("9.8", Severity.CRITICAL),
        ("7.5", Severity.HIGH),
        ("5.0", Severity.MEDIUM),
        ("2.0", Severity.LOW),
    ],
)
def test_osv_cvss_scores_map_to_severity(repo: Path, score: str, expected: Severity) -> None:
    data: Any = {"results": [dict(OSV_OUTPUT["results"][0])]}
    data["results"][0]["packages"] = [dict(OSV_OUTPUT["results"][0]["packages"][0])]
    data["results"][0]["packages"][0]["groups"] = [
        {"ids": ["GHSA-jf85-cpcp-j695"], "max_severity": score}
    ]

    [finding] = parse_osv(data, repo)

    assert finding.scanner_severity is expected


def test_osv_with_no_results_is_empty(repo: Path) -> None:
    assert parse_osv({"results": []}, repo) == []
    assert parse_osv({}, repo) == []


@pytest.mark.parametrize(
    ("name", "branch"),
    [
        ("acme/app; rm -rf /", "main"),
        ("../../etc", "main"),
        ("acme/app", "--upload-pack=evil"),
        ("acme/app", "main..evil"),
        ("acme/app", "main branch"),
    ],
)
def test_clone_rejects_hostile_names(name: str, branch: str, tmp_path: Path) -> None:
    with pytest.raises(PermanentJobError):
        clone_args(name, branch, tmp_path)


def test_clone_args_harden_git(tmp_path: Path) -> None:
    args = clone_args("juice-shop/juice-shop", "master", tmp_path / "src")

    assert "core.hooksPath=/dev/null" in args
    assert "--no-recurse-submodules" in args
    assert args[args.index("--depth") + 1] == "1"
    assert args[-2] == "https://github.com/juice-shop/juice-shop.git"
    assert args[-3] == "--"  # nothing after it can be read as an option


def _base_settings() -> Settings:
    return Settings(database_url="postgresql+asyncpg://x/y", _env_file=None)  # type: ignore[call-arg]


def _limits(settings: Settings, **update: Any) -> Settings:
    return settings.model_copy(update=update)


def test_limits_reject_too_many_files(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"f{i}.py").write_text("x")
    settings = _limits(
        Settings(database_url="postgresql+asyncpg://x/y", _env_file=None), scan_max_files=3
    )  # type: ignore[call-arg]

    with pytest.raises(PermanentJobError, match="more than 3 files"):
        enforce_limits(tmp_path, settings)


def test_limits_reject_oversized_repos(tmp_path: Path) -> None:
    (tmp_path / "big.bin").write_bytes(b"\0" * (2 * 1024 * 1024))
    settings = _limits(
        Settings(database_url="postgresql+asyncpg://x/y", _env_file=None), scan_max_repo_mb=1
    )  # type: ignore[call-arg]

    with pytest.raises(PermanentJobError, match="larger than 1 MB"):
        enforce_limits(tmp_path, settings)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_symlinks_escaping_the_clone_are_removed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "inside.txt").write_text("ok")
    (repo / "escape").symlink_to("/etc/passwd")
    (repo / "local").symlink_to(repo / "inside.txt")
    enforce_limits(repo, _base_settings())

    assert not (repo / "escape").exists()
    assert (repo / "local").exists()


async def test_process_timeout_kills_the_child() -> None:
    with pytest.raises(ProcessTimeoutError):
        await run([sys.executable, "-c", "import time; time.sleep(30)"], timeout_s=0.5)


async def test_process_output_is_captured() -> None:
    result = await run([sys.executable, "-c", "print('hi')"], timeout_s=10)

    assert (result.returncode, result.stdout.strip()) == (0, "hi")
