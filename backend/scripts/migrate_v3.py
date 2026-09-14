"""Apply the non-destructive v3 schema changes to an existing database.

Run once during deployment:
    python -m scripts.migrate_v3
"""
from sqlalchemy import inspect, text

from app.db import engine
from app import models  # noqa: F401
from app.db import Base


def main() -> None:
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("actions")}
    if "not_before" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE actions ADD COLUMN not_before TIMESTAMP NULL"))
    print("v3 schema migration complete")


if __name__ == "__main__":
    main()
