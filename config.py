import os
import logging
from logging.handlers import RotatingFileHandler
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Database Setup ---
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set.")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Azure Storage Setup ---
AZURE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME", "quickbooks-imports")
if not AZURE_CONNECTION_STRING:
    print("Warning: AZURE_STORAGE_CONNECTION_STRING not set. Attachment uploads will fail.")

# --- Logging Setup ---
LOG_DIR = 'logs'
if not os.path.exists(LOG_DIR):
    try:
        os.makedirs(LOG_DIR)
    except OSError as e:
        print(f"Error creating log directory 'logs': {e}. Please create it manually.")

# Create a logger
logger = logging.getLogger('importer')
logger.setLevel(logging.DEBUG)  # Capture all levels

# Create console handler and set level to INFO
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch_format = logging.Formatter('%(levelname)s: %(message)s')
ch.setFormatter(ch_format)

# Create file handler and set level to DEBUG
log_file = os.path.join(LOG_DIR, 'import.log')
# RotatingFileHandler: max 5MB per file, keep 3 backup files
try:
    fh = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3)
    fh.setLevel(logging.DEBUG)
    fh_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    fh.setFormatter(fh_format)
    # Add handlers to logger
    if not logger.handlers:
        logger.addHandler(ch)
        logger.addHandler(fh)
except Exception as e:
    print(f"Error setting up file logger. Check permissions for 'logs' directory. {e}")
    if not logger.handlers:
        logger.addHandler(ch)

# --- QuickBooks Config ---
# Load all QB settings
QB_CLIENT_ID = os.getenv("QB_CLIENT_ID")
QB_CLIENT_SECRET = os.getenv("QB_CLIENT_SECRET")
QB_ENVIRONMENT = os.getenv("QB_ENVIRONMENT", "sandbox")
QB_REDIRECT_URI = os.getenv("QB_REDIRECT_URI")
QB_ACCESS_TOKEN = os.getenv("QB_ACCESS_TOKEN")
QB_REFRESH_TOKEN = os.getenv("QB_REFRESH_TOKEN")
QB_REALM_ID = os.getenv("QB_REALM_ID")

def all_qb_keys_present():
    """Check if main keys for running the script are in .env"""
    return all([QB_CLIENT_ID, QB_CLIENT_SECRET, QB_ACCESS_TOKEN, QB_REFRESH_TOKEN, QB_REALM_ID])

def auth_keys_present():
    """Check if keys for initial auth are present."""
    return all([QB_CLIENT_ID, QB_CLIENT_SECRET, QB_REDIRECT_URI])