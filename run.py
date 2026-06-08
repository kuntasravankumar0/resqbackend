from __future__ import annotations

import os
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"


def load_env_file() -> None:
    if not ENV_FILE.exists():
        return
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()


def main() -> None:
    load_env_file()
    os.environ.setdefault("JWT_SECRET", "resq_service_jwt_secret_2026")
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    os.environ.setdefault("CUSTOMER_WEBHOOK_URL", "")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
