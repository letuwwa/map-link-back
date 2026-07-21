# Map Link Backend

FastAPI backend for Map Link, a road reporting and live map application.

The backend provides:
- Cookie and bearer-token JWT authentication
- PostgreSQL persistence with SQLAlchemy and Alembic
- Redis-backed realtime map data
- Road reports cached for map display
- User privacy/message settings
- Direct and report conversation APIs
- Demo data seeding for presentations

## Requirements

- Python 3.14+
- `uv`
- Docker and Docker Compose

## Quick Start

Install dependencies:

```bash
uv sync
```

Create the local environment file:

```bash
cp .env.example .env
```

Start PostgreSQL and Redis:

```bash
docker compose up -d
```

Run migrations:

```bash
uv run alembic upgrade head
```

Start the API:

```bash
uv run fastapi dev app/main.py
```

The API runs at:

```text
http://localhost:8000
```

Swagger docs:

```text
http://localhost:8000/docs
```

## Environment

Main variables:

```env
APP_NAME=map-link
ENVIRONMENT=development
ALLOWED_ORIGINS=[]
ALLOWED_ORIGIN_REGEX=.*

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=map-link-db

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

JWT_SECRET_KEY=change-me-generate-a-long-random-secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30
ACCESS_TOKEN_COOKIE_NAME=access_token
REFRESH_TOKEN_COOKIE_NAME=refresh_token
AUTH_COOKIE_SECURE=false
AUTH_COOKIE_SAMESITE=lax
```

For local demos, `ALLOWED_ORIGIN_REGEX=.*` allows browser clients from any local IP/port. For production, replace this with a strict origin list.

Generate a better JWT secret:

```bash
openssl rand -hex 32
```

## Database

Create a migration after model changes:

```bash
uv run alembic revision --autogenerate -m "describe change"
```

Apply migrations:

```bash
uv run alembic upgrade head
```

Show current migration:

```bash
uv run alembic current
```

## Auth

Auth supports both:
- `Authorization: Bearer <token>`
- HttpOnly cookies set by login/register

Endpoints:

```text
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/token
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
GET  /api/v1/auth/me
GET  /api/v1/auth/admin-only
```

Register:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "username": "exampleuser",
    "first_name": "Example",
    "last_name": "User",
    "password": "password123456"
  }'
```

Login:

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=exampleuser&password=password123456"
```

## User Settings

Endpoints:

```text
GET   /api/v1/users/settings
PATCH /api/v1/users/settings
```

Settings:
- `allow_incoming_messages`: when false, other users cannot start/send direct messages to this user
- `hide_me`: when true, this user is not shown in nearby map users

Patch examples:

```json
{"allow_incoming_messages": false}
```

```json
{"hide_me": true}
```

The current user response and Redis user cache include both settings.

## Reports

Endpoints:

```text
POST /api/v1/reports
POST /api/v1/reports/deleteReport
```

Create report:

```json
{
  "report_type": "ROAD_DANGER",
  "latitude": 32.0853,
  "longitude": 34.7818
}
```

Report types:

```text
POLICE
FLOODING
ROAD_DANGER
TRAFFIC_JAM
MISSING_SIGN
CAR_ACCIDENT
CONSTRUCTION
SPEED_CAMERA
```

Reports are stored in PostgreSQL and cached in Redis for map websocket responses. Redis report cache lives for 3 hours.

## Location WebSocket

Endpoint:

```text
WS /api/v1/location/ws
```

Authentication:
- Browser clients use the `access_token` cookie
- Non-browser clients can pass `?token=<access-token>`

Client sends:

```json
{"lat": 32.0853, "lng": 34.7818}
```

Server responds:

```json
{
  "type": "nearby_map_data",
  "me": {
    "user_id": "...",
    "lat": 32.0853,
    "lng": 34.7818,
    "allow_incoming_messages": true,
    "hide_me": false
  },
  "users": [
    {
      "user_id": "...",
      "lat": 32.0856,
      "lng": 34.7821,
      "allow_incoming_messages": false,
      "hide_me": false
    }
  ],
  "reports": [
    {
      "id": "...",
      "user_id": "...",
      "report_type": "TRAFFIC_JAM",
      "latitude": 32.0856,
      "longitude": 34.7821,
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

If `hide_me=true`, the user still receives map data but is removed from the shared user-location Redis set.

## Conversations And Messages

Endpoints:

```text
POST /api/v1/conversations/direct
POST /api/v1/conversations/reports
GET  /api/v1/conversations
GET  /api/v1/conversations/{conversation_id}
GET  /api/v1/conversations/{conversation_id}/messages
POST /api/v1/conversations/{conversation_id}/messages
POST /api/v1/conversations/{conversation_id}/read
```

Create direct conversation:

```json
{"user_id": "..."}
```

Send message:

```json
{"body": "Are you near this report?"}
```

Direct conversations respect the target user's `allow_incoming_messages` setting.

## Demo Data

Seed predictable users, settings, reports, conversations, messages, and Redis map data:

```bash
uv run python scripts/seed_demo.py
```

Demo accounts:

```text
driver1 / password123456
driver2 / password123456
reporter / password123456
no_messages_user / password123456
hidden_user / password123456
```

Suggested geolocation overrides:

```text
driver1: 32.08530, 34.78180
driver2: 32.08565, 34.78210
reporter: 32.08495, 34.78145
no_messages_user: 32.08545, 34.78155
hidden_user: 32.08575, 34.78235
```

Use Chrome DevTools -> More tools -> Sensors -> Location to set one of these coordinates.

## Quality Checks

Run lint:

```bash
uv run ruff check .
```

Import check:

```bash
uv run python -c "from app.main import app; print('import ok')"
```

## Project Structure

```text
app/main.py                 FastAPI app and CORS
app/api/router.py           API router registration
app/api/v1/auth.py          Auth routes
app/api/v1/users.py         Location websocket
app/api/v1/reports.py       Report routes and Redis report cache
app/api/v1/user_settings.py User settings routes
app/api/v1/conversations.py Conversation/message routes
app/core/settings.py        Environment settings
app/core/security.py        JWT and password logic
app/core/redis.py           Redis clients
app/core/user_cache.py      Redis user cache
app/db/models/              SQLAlchemy models
alembic/versions/           Database migrations
scripts/seed_demo.py        Demo data seeder
```
