from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv
from urllib.parse import quote_plus
import time

# Load env variables
load_dotenv()

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = quote_plus(os.getenv("DB_PASSWORD"))  # handle special chars like @
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Retry logic (important for Docker startup)
for i in range(10):
    try:
        engine = create_engine(DATABASE_URL)
        connection = engine.connect()
        print("✅ Database connected successfully")
        connection.close()
        break
    except Exception as e:
        print(f"⏳ Waiting for DB... Attempt {i+1}/10")
        time.sleep(3)
else:
    raise Exception("❌ Could not connect to database")

# Session setup
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base model
Base = declarative_base()


# Dependency (FastAPI)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()