"""
VeriaChain — Configuration
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    # Security
    SECRET_KEY = os.getenv("SECRET_KEY", "veriachain-dev-key-change-in-production")
    WTF_CSRF_ENABLED = True

    # Database
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{BASE_DIR / 'veriachain.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload
    UPLOAD_FOLDER = BASE_DIR / "uploads"
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20 MB
    ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png", "webp", "bmp", "tiff"}
    ALLOWED_DOC_EXT   = {"pdf", "docx", "txt", "eml", "msg"}

    # Detection model
    # Options: "huggingface" | "frequency" | "ensemble"
    # "huggingface" downloads ~100MB model on first run (requires internet)
    # "frequency"   uses only local FFT/texture analysis (offline, less accurate)
    # "ensemble"    combines both (recommended)
    DETECTION_MODE = os.getenv("DETECTION_MODE", "ensemble")
    HF_MODEL_ID    = "umm-maybe/AI-image-detector"
    MODEL_CACHE_DIR = BASE_DIR / "models"

    # Blockchain (Polygon Mumbai testnet for dev, Polygon Mainnet for prod)
    POLYGON_RPC      = os.getenv("POLYGON_RPC", "https://polygon-rpc.com")
    CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS", "")   # deploy contract first
    PRIVATE_KEY      = os.getenv("PRIVATE_KEY", "")        # never commit this
    IPFS_API_KEY     = os.getenv("IPFS_API_KEY", "")       # Pinata API key

    # Session
    PERMANENT_SESSION_LIFETIME = 86400  # 24h
