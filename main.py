"""
Entry point.
Run with:  uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""
import os
from dotenv import load_dotenv

load_dotenv()

from src.api.main import app  # noqa: E402 — must be after load_dotenv

__all__ = ["app"]
