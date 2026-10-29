import re

from triage_core.domain import ACTIVE_SCAN_STATUSES
from triage_db.models import ACTIVE_SCAN_PREDICATE


def test_active_scan_index_predicate_matches_the_domain() -> None:
    in_sql = set(re.findall(r"'(\w+)'", ACTIVE_SCAN_PREDICATE))

    assert in_sql == {s.value for s in ACTIVE_SCAN_STATUSES}
