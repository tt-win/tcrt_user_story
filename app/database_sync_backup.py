from sqlalchemy.orm import sessionmaker

from app.database import get_sync_engine
from app.db_migrations import upgrade_main_database

engine = get_sync_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    upgrade_main_database()
