# Service Center Backend

FastAPI backend for the service-center React app.

## What it provides

- JWT login and employee self-registration
- Manager-only account creation and deletion
- Google-sheet-style service job import
- Technician worklogs, part requests, and approval queue
- Customer completion webhook logging
- Technician performance metrics for managers
- Full workspace snapshot for the frontend

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
py run.py
```

The API runs at `http://127.0.0.1:8000`.

## Default accounts

- `manager@company.com` / `manager123`
- `employee@company.com` / `employee123`
- `admin@company.com` / `admin123`

## Tests

```bash
pytest -q
```

## API

- `GET /health`
- `GET /api/state`
- `POST /api/auth/login`
- `POST /api/auth/register`
- `POST /api/users`
- `GET /api/jobs`
- `POST /api/jobs/import-sheet`
- `POST /api/jobs/{id}/notes`
- `POST /api/jobs/{id}/parts-request`
- `PATCH /api/jobs/{id}/status`
- `GET /api/manager/metrics`
- `GET /api/manager/approvals`
- `POST /api/manager/approvals/{id}`
- `GET /api/manager/webhooks`
