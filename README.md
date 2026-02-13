# FixAI — On-Call AI Debugging Agent

An AI-powered debugging assistant that integrates with Code Parser, Metrics Explorer, and Logs Explorer to help engineers diagnose and resolve production issues.

## Architecture

- **Backend**: Python / FastAPI / LangGraph / SQLAlchemy (async)
- **Frontend**: React / TypeScript / Vite / Tailwind CSS
- **AI**: Claude via Bedrock Proxy (configurable)
- **Database**: PostgreSQL

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 14+

### 1. Database

```bash
createdb fixai
```

### 2. Backend

```bash
cd backend
cp .env.example .env        # Edit with your credentials
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run migrations (or let dev mode auto-create tables)
# alembic upgrade head

# Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8100 --reload
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev                  # Starts on http://localhost:3006
```

The Vite dev server proxies `/api/*` requests to the backend on port 8100.

### 4. Production Build

```bash
cd frontend && npm run build    # Creates frontend/dist/
# Backend auto-serves frontend/dist/ as static files
uvicorn app.main:app --host 0.0.0.0 --port 8100
```

## Configuration

All configuration via environment variables (see `backend/.env.example`):

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection |
| `CODE_PARSER_BASE_URL` | `http://localhost:8000` | Code Parser service URL |
| `METRICS_EXPLORER_BASE_URL` | `http://localhost:8000` | Metrics Explorer service URL |
| `LOGS_EXPLORER_BASE_URL` | `http://localhost:8003` | Logs Explorer service URL |
| `CLAUDE_BEDROCK_URL` | (empty) | Claude Bedrock proxy URL (set via CodeCircle AI Settings) |
| `CLAUDE_MODEL_ID` | (empty) | Claude model ID (set via CodeCircle AI Settings) |
| `CLAUDE_API_KEY` | (empty) | API key (set via CodeCircle AI Settings or env var) |

## Organization Setup

Each organization maps to identifiers in the three downstream services:

- **Code Parser**: `repo_id` (UUID of the parsed repository)
- **Metrics Explorer**: `org_id` (UUID, sent as `X-Organization-Id` header)
- **Logs Explorer**: `org_id` (UUID, used as path parameter)

Configure these via the UI's "Create Organization" modal or the REST API:

```bash
curl -X POST http://localhost:8100/api/v1/organizations \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "My Team",
    "slug": "my-team",
    "code_parser_base_url": "http://localhost:8000",
    "code_parser_repo_id": "...",
    "metrics_explorer_base_url": "http://localhost:8000",
    "metrics_explorer_org_id": "...",
    "logs_explorer_base_url": "http://localhost:8003",
    "logs_explorer_org_id": "..."
  }'
```

## Agent Tools

The AI agent has 13 tools across three services:

**Code Parser** (5): `search_symbols`, `get_symbol_details`, `get_call_graph`, `list_entry_points`, `get_entry_point_flow`

**Metrics Explorer** (4): `query_metrics`, `list_monitors`, `get_monitor_details`, `list_dashboards`

**Logs Explorer** (4): `search_logs`, `list_log_indexes`, `list_log_sources`, `list_applications`

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/api/v1/organizations` | Create organization |
| `GET` | `/api/v1/organizations` | List organizations |
| `GET` | `/api/v1/organizations/:id` | Get organization |
| `PATCH` | `/api/v1/organizations/:id` | Update organization |
| `DELETE` | `/api/v1/organizations/:id` | Delete organization |
| `POST` | `/api/v1/organizations/:id/conversations` | Create conversation |
| `GET` | `/api/v1/organizations/:id/conversations` | List conversations |
| `GET` | `/api/v1/conversations/:id` | Get conversation detail |
| `DELETE` | `/api/v1/conversations/:id` | Delete conversation |
| `POST` | `/api/v1/conversations/:id/messages` | Send message (SSE stream) |
