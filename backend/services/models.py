"""SQLAlchemy models for the repository knowledge graph.

Deliberately avoids Postgres-only column types (e.g. JSONB) so the same
models work against an in-memory SQLite engine in tests, with the real
Postgres service used for actual runs.
"""

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[str] = mapped_column(String(63), unique=True, index=True)
    source: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    files: Mapped[list["File"]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )


class File(Base):
    __tablename__ = "files"
    __table_args__ = (UniqueConstraint("repository_id", "file_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    file_path: Mapped[str] = mapped_column(String)
    language: Mapped[str] = mapped_column(String(64))

    repository: Mapped[Repository] = relationship(back_populates="files")
    symbols: Mapped[list["Symbol"]] = relationship(back_populates="file", cascade="all, delete-orphan")
    imports: Mapped[list["Import"]] = relationship(back_populates="file", cascade="all, delete-orphan")
    calls: Mapped[list["Call"]] = relationship(
        back_populates="file", cascade="all, delete-orphan", foreign_keys="Call.file_id"
    )
    api_endpoints: Mapped[list["ApiEndpoint"]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )


class Symbol(Base):
    __tablename__ = "symbols"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String(32))
    start_line: Mapped[int]
    end_line: Mapped[int]

    file: Mapped[File] = relationship(back_populates="symbols")


class Import(Base):
    __tablename__ = "imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    raw_source: Mapped[str] = mapped_column(String)
    module_path: Mapped[str | None] = mapped_column(String, nullable=True)
    start_line: Mapped[int]

    file: Mapped[File] = relationship(back_populates="imports")


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    caller_symbol_id: Mapped[int | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="SET NULL"), nullable=True
    )
    callee_name: Mapped[str] = mapped_column(String)
    callee_symbol_id: Mapped[int | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="SET NULL"), nullable=True
    )
    start_line: Mapped[int]

    file: Mapped[File] = relationship(back_populates="calls", foreign_keys=[file_id])


class ApiEndpoint(Base):
    __tablename__ = "api_endpoints"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    method: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(String)
    handler_symbol_id: Mapped[int | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="SET NULL"), nullable=True
    )
    framework_hint: Mapped[str] = mapped_column(String(32))
    start_line: Mapped[int]

    file: Mapped[File] = relationship(back_populates="api_endpoints")
