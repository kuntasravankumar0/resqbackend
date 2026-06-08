# Vercel serverless entry point
# Imports the FastAPI app from app/main.py
import sys
import os

# Add parent directory to path so app.main is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: F401 — Vercel needs this as 'app'

# Vercel uses the variable named 'app' from this module
