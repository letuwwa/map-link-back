from redis.asyncio import Redis
from redis import Redis as SyncRedis
from collections.abc import AsyncGenerator

from app.core import settings


def create_sync_redis_client() -> SyncRedis:
    return SyncRedis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


def create_redis_client() -> Redis:
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


async def get_redis_client() -> AsyncGenerator[Redis]:
    redis_client = create_redis_client()
    try:
        yield redis_client
    finally:
        await redis_client.aclose()
