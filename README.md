# FastAPI Template

FastAPI starter with PostgreSQL, SQLAlchemy, Alembic migrations, JWT auth,
password hashing, refresh/logout token handling, and role-based admin
protection.

## Requirements

- Python 3.14+
- Docker
- uv

## Setup

Install dependencies:
```bash
uv sync
```

Create local env file:
```bash
cp .env.example .env
```

Generate a JWT secret and put it in `.env`:
```bash
openssl rand -hex 32
```

Required env values:
```env
APP_NAME=fastapi-template
ENVIRONMENT=development
ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:8000","http://127.0.0.1:3000","http://127.0.0.1:8000"]

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=fastapi_template

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

JWT_SECRET_KEY=<long-random-secret>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30
ACCESS_TOKEN_COOKIE_NAME=access_token
REFRESH_TOKEN_COOKIE_NAME=refresh_token
AUTH_COOKIE_SECURE=false
AUTH_COOKIE_SAMESITE=lax
```

## Database

Start PostgreSQL and Redis:
```bash
docker compose up -d
```

PostgreSQL is exposed on `localhost:5432`; Redis is exposed on
`localhost:6379`.

Create the database if running PostgreSQL outside Docker:
```bash
createdb fastapi_template
```

Run migrations:
```bash
uv run alembic upgrade head
```

Create a migration after model changes:
```bash
uv run alembic revision --autogenerate -m "describe change"
```

## Run

```bash
uv run fastapi dev app/main.py
```

The API is served at `http://localhost:8000`. Interactive docs are available at
`http://localhost:8000/docs`.

Register a user:
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

Login with an email or username:
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=user@example.com&password=password123456"
```

Swagger OAuth2 login endpoint:
```bash
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=user@example.com&password=password123456"
```

Use token:
```bash
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <jwt-token>"
```

Browser auth:
- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, and
  `POST /api/v1/auth/token` return tokens in JSON and also set HttpOnly
  `access_token` and `refresh_token` cookies.
- Authenticated endpoints accept either `Authorization: Bearer <token>` or the
  `access_token` cookie.
- `POST /api/v1/auth/refresh` accepts either a bearer refresh token or the
  `refresh_token` cookie, then updates the `access_token` cookie.
- `POST /api/v1/auth/logout` clears both auth cookies and revokes any valid
  provided auth tokens.

## Auth Endpoints

```text
POST /api/v1/auth/register      Create a regular user and return token pair
POST /api/v1/auth/login         Return the user and token pair
POST /api/v1/auth/token         Return an OAuth2-compatible token pair
POST /api/v1/auth/refresh       Return a new access token from a refresh token
POST /api/v1/auth/logout        Revoke the presented access or refresh token
GET  /api/v1/auth/me            Return the current user
GET  /api/v1/auth/admin-only    Require an admin user
```

## Location WebSocket

Send the current user's location and receive nearby map data from Redis:
```text
WS /api/v1/location/ws
```

Authentication uses the `access_token` cookie. For clients that cannot send the
cookie during local development, pass the access token as a query parameter:
```text
WS /api/v1/location/ws?token=<access-token>
```

Payload:
```json
{"lat":32.0853,"lng":34.7818}
```

Response:
```json
{
  "type": "nearby_map_data",
  "me": {"user_id": "...", "lat": 32.0853, "lng": 34.7818},
  "users": [{"user_id": "...", "lat": 32.0854, "lng": 34.7819}],
  "reports": [{"id": "...", "report_type": "ROAD_DANGER", "latitude": 32.0853, "longitude": 34.7818}]
}
```

## Conversation Endpoints

```text
POST /api/v1/conversations/direct                 Create or return a direct chat
POST /api/v1/conversations/reports                Create a report discussion
GET  /api/v1/conversations                        List my conversations
GET  /api/v1/conversations/{id}                   Read one conversation
GET  /api/v1/conversations/{id}/messages          List messages
POST /api/v1/conversations/{id}/messages          Send a message
POST /api/v1/conversations/{id}/read              Mark a message as read
```

Create a direct conversation:
```json
{"user_id":"..."}
```

Send a message:
```json
{"body":"Are you near this report?"}
```

## User Settings

```text
GET   /api/v1/users/settings       Read current user's settings
PATCH /api/v1/users/settings       Update current user's settings
```

Update incoming messages:
```json
{"allow_incoming_messages":false}
```

When disabled, other users cannot create a new direct conversation with this
user or send new direct messages to them. Existing conversations remain
readable, and the user can still send outgoing messages.

Newly registered users use the `regular` role. The base migration creates the
users and token blocklist tables; it does not seed an admin user.

## Quality

Run Ruff:
```bash
uv run ruff check .
```

## Key Files

```text
app/main.py                       FastAPI app
app/api/v1/auth.py                Auth routes
app/core/security.py              Password hashing and JWT logic
app/core/settings.py              Env settings
app/db/models/user.py             User model and roles
app/db/models/token_blocklist.py  Revoked token model
alembic/versions/                 DB migrations
```

## Status

Done:
- Clean project structure
- Env variables support
- DB base model and migrations setup
- JWT auth with refresh/logout and role-based admin protection

To do:
- Docker pre-settings
- Docs
