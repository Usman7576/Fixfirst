"""Declarative base, shared column types and naming conventions."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy import MetaData, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names keep Alembic autogenerate diffs stable across environments.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: sa.DateTime(timezone=True),
        dict[str, Any]: JSONB,
        bytes: sa.LargeBinary,
    }


def pg_enum(enum_cls: type[StrEnum], name: str) -> sa.Enum:
    """Native Postgres enum storing the enum *values* (lowercase strings)."""
    return sa.Enum(
        enum_cls,
        name=name,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
