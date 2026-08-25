"""
MongoDB client — user storage for email/password authentication.

Connection
----------
Uses a lazy singleton ``pymongo.MongoClient`` backed by ``MONGODB_URL``.
On first connection the ``users`` collection gets a unique index on
``email`` (idempotent — ``create_index`` is a no-op if it already exists).

User document schema
--------------------
{
    "_id":           ObjectId,
    "email":         "user@example.com",     # unique
    "password_hash": "$2b$12$...",           # bcrypt via passlib
    "full_name":     "Jane Doe",
    "created_at":    ISODate("2026-...")
}
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from passlib.hash import bcrypt
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger("app.auth.mongodb")

_client: Optional[MongoClient] = None
_DB_NAME = "docintel"


def _get_collection() -> Collection:
    """Return the ``users`` collection, creating the client + index on first call."""
    global _client
    if _client is None:
        url = os.getenv("MONGODB_URL", "mongodb://localhost:27017/docintel")
        _client = MongoClient(url, serverSelectionTimeoutMS=5000)
        # Ensure unique email index (idempotent)
        _client[_DB_NAME]["users"].create_index("email", unique=True)
        logger.info("MongoDB client initialised", extra={"url": url.split("@")[-1]})
    return _client[_DB_NAME]["users"]


def get_mongo_client() -> Optional[MongoClient]:
    """Return the raw MongoClient (for health checks). May be None if never used."""
    return _client


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

def create_user(email: str, password: str, full_name: Optional[str] = None) -> dict:
    """
    Hash *password* with bcrypt and insert a new user document.

    Returns the inserted document (with ``_id`` converted to ``str``).
    Raises ``DuplicateKeyError`` if the email is already registered.
    """
    col = _get_collection()
    doc = {
        "email": email.lower().strip(),
        "password_hash": bcrypt.hash(password),
        "full_name": full_name,
        "created_at": datetime.now(timezone.utc),
    }
    result = col.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    logger.info("User created", extra={"user_id": doc["_id"], "email": doc["email"]})
    return doc


def get_user_by_email(email: str) -> Optional[dict]:
    """Return the user document or ``None``."""
    col = _get_collection()
    doc = col.find_one({"email": email.lower().strip()})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


def get_user_by_id(user_id: str) -> Optional[dict]:
    """Return the user document or ``None``."""
    from bson import ObjectId

    col = _get_collection()
    try:
        doc = col.find_one({"_id": ObjectId(user_id)})
    except Exception:
        return None
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Check a plain-text password against its bcrypt hash."""
    return bcrypt.verify(plain_password, password_hash)
