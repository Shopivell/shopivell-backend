# from pathlib import Path
# from dotenv import load_dotenv
# import os
# from sqlalchemy import create_engine
# from sqlalchemy.orm import sessionmaker, declarative_base
# # Set the correct path to the .env file inside the routers folder
# env_path = Path(__file__).resolve().parent / "routers" / ".env"
# load_dotenv(dotenv_path=env_path)

# DB_USERNAME = os.getenv("DB_USERNAME")
# DB_PASSWORD = os.getenv("DB_PASSWORD")  # FIXED here
# DB_HOST = os.getenv("DB_HOST")
# DB_PORT = os.getenv("DB_PORT")
# DB_NAME = os.getenv("DB_NAME")
# DB_SSLMODE = os.getenv("DB_SSLMODE", "prefer")  # default "prefer"

# # Validate all required env variables
# missing_vars = [var for var, val in {
#     "DB_USERNAME": DB_USERNAME,
#     "DB_PASSWORD": DB_PASSWORD,
#     "DB_HOST": DB_HOST,
#     "DB_PORT": DB_PORT,
#     "DB_NAME": DB_NAME,
# }.items() if not val]

# if missing_vars:
#     raise ValueError(f"Missing required environment variables: {missing_vars}")


# SQLALCHEMY_DATABASE_URL = (
#     f"postgresql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode={DB_SSLMODE}"
# )

# engine = create_engine(SQLALCHEMY_DATABASE_URL, echo=True)

# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base = declarative_base()


# def get_db():
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()

from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Define the path for the SQLite database file
# It will be created in the current working directory
DATABASE_FILE = "boneka.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_FILE}"

# Create the SQLAlchemy engine for SQLite
# The 'echo=True' will log all SQL statements to the console, useful for debugging
engine = create_engine(SQLALCHEMY_DATABASE_URL, echo=True)

# Configure a local session class
# autocommit=False means changes aren't saved until commit() is called
# autoflush=False means objects aren't flushed to the database until commit() or query
# bind=engine connects this session to our SQLite database engine
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for your declarative models
# Your database tables will inherit from this Base
Base = declarative_base()

def get_db():
    """
    Dependency to get a database session.
    This function provides a database session that can be used in your application.
    It ensures the session is properly closed after use, even if errors occur.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()