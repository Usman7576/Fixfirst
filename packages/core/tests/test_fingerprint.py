import string

from hypothesis import given
from hypothesis import strategies as st

from triage_core.domain import Severity, Tool
from triage_core.findings import Finding
from triage_core.fingerprint import (
    KEYWORDS,
    assign_fingerprints,
    code_fingerprint,
    normalise_snippet,
)

SQLI = 'const rows = db.query("SELECT * FROM users WHERE id = " + req.query.id);'


def _finding(
    snippet: str, *, line: int = 10, path: str = "routes/user.js", rule: str = "r1"
) -> Finding:
    return Finding(
        tool=Tool.SEMGREP,
        rule_id=rule,
        title="t",
        file_path=path,
        start_line=line,
        end_line=line,
        snippet=snippet,
        scanner_severity=Severity.HIGH,
    )


def test_whitespace_and_comments_do_not_matter() -> None:
    noisy = """
        const   rows = db.query(  // look up the user
            "SELECT * FROM users WHERE id = " +  req.query.id  ) ; /* TODO */
    """
    assert normalise_snippet(noisy) == normalise_snippet(SQLI)


def test_consistent_renames_do_not_matter() -> None:
    renamed = SQLI.replace("rows", "result").replace("db", "conn").replace("req", "request")
    assert normalise_snippet(renamed) == normalise_snippet(SQLI)


def test_attribute_names_and_keywords_are_kept() -> None:
    body = SQLI.replace("req.query.id", "req.body.id")
    assert normalise_snippet(body) != normalise_snippet(SQLI)
    assert "query" in normalise_snippet(SQLI)
    assert normalise_snippet("eval(x)") != normalise_snippet("exec(x)")


def test_long_string_contents_are_ignored_but_short_ones_kept() -> None:
    long_a = f'q("{"a" * 40}")'
    long_b = f'q("{"b" * 40}")'
    assert normalise_snippet(long_a) == normalise_snippet(long_b)
    assert normalise_snippet('q("md5")') != normalise_snippet('q("sha256")')


def test_line_numbers_do_not_change_the_fingerprint() -> None:
    [a] = assign_fingerprints([_finding(SQLI, line=10)])
    [b] = assign_fingerprints([_finding(SQLI, line=250)])
    assert a.fingerprint == b.fingerprint


def test_rule_and_file_are_part_of_identity() -> None:
    base = code_fingerprint("r1", "a.js", SQLI, 0)
    assert base != code_fingerprint("r2", "a.js", SQLI, 0)
    assert base != code_fingerprint("r1", "b.js", SQLI, 0)


def test_identical_matches_in_one_file_stay_distinct() -> None:
    findings = assign_fingerprints([_finding(SQLI, line=5), _finding(SQLI, line=50)])
    assert len({f.fingerprint for f in findings}) == 2


def test_exact_duplicate_reports_collapse() -> None:
    assert len(assign_fingerprints([_finding(SQLI), _finding(SQLI)])) == 1


def test_dependency_fingerprint_ignores_version() -> None:
    def osv(version: str) -> Finding:
        return Finding(
            tool=Tool.OSV,
            rule_id="GHSA-xxxx",
            title="t",
            file_path="package-lock.json",
            start_line=1,
            end_line=1,
            snippet="lodash",
            scanner_severity=Severity.HIGH,
            package="lodash",
            installed_version=version,
        )

    [a], [b] = assign_fingerprints([osv("4.17.10")]), assign_fingerprints([osv("4.17.11")])
    assert a.fingerprint == b.fingerprint


identifiers = st.text(string.ascii_lowercase, min_size=3, max_size=8).filter(
    lambda s: s not in KEYWORDS and s not in {"cursor", "request"}
)


@given(a=identifiers, b=identifiers, gap=st.text(" \t\n", min_size=1, max_size=5))
def test_property_stable_under_renames_and_spacing(a: str, b: str, gap: str) -> None:
    original = f"{a} = request.args.get('id'){gap}cursor.execute('SELECT ' + {a})"
    renamed = f"{b} = request.args.get('id')\ncursor.execute('SELECT ' +{gap}{b})"
    assert normalise_snippet(original) == normalise_snippet(renamed)
