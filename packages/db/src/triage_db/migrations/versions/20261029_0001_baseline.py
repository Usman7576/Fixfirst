"""Baseline revision. Week 2 adds the MVP tables on top of this.

Revision ID: 0001
Revises:
Create Date: 2026-10-29
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
