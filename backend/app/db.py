from sqlalchemy import inspect, text
from sqlmodel import SQLModel, Session, create_engine

from .config import settings

engine = create_engine(f"sqlite:///{settings.db_path}", connect_args={"check_same_thread": False})

# Columns added to the MediaItem model over time: anyone with a database
# created by an earlier version of the app doesn't have them on disk yet.
# SQLModel.metadata.create_all() creates MISSING tables but doesn't add
# columns to a table that already exists — without this migration, every
# query on MediaItem would fail with "no such column" for anyone upgrading
# from an earlier version (for anyone creating the DB from scratch,
# create_all() is enough: the table is born already complete, these
# ALTERs become no-ops).
_MEDIAITEM_MIGRATIONS = {
    "season": "ALTER TABLE mediaitem ADD COLUMN season INTEGER",
    "episode": "ALTER TABLE mediaitem ADD COLUMN episode INTEGER",
    "description": "ALTER TABLE mediaitem ADD COLUMN description TEXT",
    "tags": "ALTER TABLE mediaitem ADD COLUMN tags JSON",
}


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_mediaitem_schema()


def _migrate_mediaitem_schema() -> None:
    inspector = inspect(engine)
    if "mediaitem" not in inspector.get_table_names():
        return  # new table: create_all already created it with the correct schema

    existing_columns = {col["name"] for col in inspector.get_columns("mediaitem")}
    with engine.begin() as conn:
        for column, ddl in _MEDIAITEM_MIGRATIONS.items():
            if column not in existing_columns:
                conn.execute(text(ddl))


def get_session():
    with Session(engine) as session:
        yield session
