from sqlalchemy import create_engine, MetaData, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from pathlib import Path

# 固定使用專案根目錄下的資料庫檔案，避免工作目錄差異
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_FILE = PROJECT_ROOT / "test_case_repo.db"
DATABASE_URL = f"sqlite:///{DB_FILE}"

# 改善 SQLite 並發設定
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        "timeout": 30  # 30 秒 busy timeout
    },
    pool_pre_ping=True,  # 檢查連線健康
    pool_recycle=3600    # 每小時回收連線
)

# 為每個連線設定 SQLite 優化參數
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    # 啟用 WAL 模式以改善並發
    cursor.execute("PRAGMA journal_mode=WAL")
    # 設定 busy timeout 為 30 秒
    cursor.execute("PRAGMA busy_timeout=30000")
    # 設定同步模式為 NORMAL（平衡性能與安全）
    cursor.execute("PRAGMA synchronous=NORMAL")
    # 啟用外鍵約束
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_tables():
    Base.metadata.create_all(bind=engine)