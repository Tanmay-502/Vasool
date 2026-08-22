"""
Run once your .env DATABASE_URL points to your real Neon connection string:

    python -m scripts.init_db

Re-running is safe — create_all only creates tables that don't exist yet.
"""
from app.db import Base, engine
from app import models  # noqa: F401  (import registers all tables on Base)


def main():
    Base.metadata.create_all(bind=engine)
    print("Tables created:", list(Base.metadata.tables.keys()))


if __name__ == "__main__":
    main()