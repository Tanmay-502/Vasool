"""
Drops every table and recreates them from whatever models.py currently
says, then leaves the DB empty.

Why this exists: there's no Alembic in this project (see ARCHITECTURE.md's
decision log — "no migration tool yet ... reset via a fresh branch
instead"). init_db.py's create_all() only creates NEW tables; it never
adds a column to a table that already exists with the old shape. So every
time a model gains/changes a column, the live Neon DB silently falls out
of sync with the code until something writes to that column and blows up
with UndefinedColumn — exactly what happened when agent_decisions.py
started writing tokens_used/latency_ms against a table created before
those columns existed.

    python -m scripts.reset_schema
    python -m scripts.generate_synthetic_data   # repopulate afterward

Refuses to run if ENV=production, same safety rule as
generate_synthetic_data's --reset flag.
"""
from app.config import settings
from app.db import Base, engine
from app import models  # noqa: F401  (registers all tables on Base.metadata)


def main():
    if settings.ENV == "production":
        raise RuntimeError("Refusing to drop tables with ENV=production. Aborting.")
    print("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    print("Recreating tables from current models.py...")
    Base.metadata.create_all(bind=engine)
    print("Done. Tables:", list(Base.metadata.tables.keys()))
    print("DB is now empty — run `python -m scripts.generate_synthetic_data` to repopulate.")


if __name__ == "__main__":
    main()