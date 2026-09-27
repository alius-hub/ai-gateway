from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import redis.asyncio as redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.db.models import ApiKey

# A single script owns admission and queue ordering across all gateway workers.
ADMIT = """
local qps, tpm, budget, queue, ticket = unpack(KEYS)
local now, cost, qlimit, tlimit, blimit, qttl, tttl, bttl, mode, fingerprint, waitms =
    tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3]), tonumber(ARGV[4]),
    tonumber(ARGV[5]), tonumber(ARGV[6]), tonumber(ARGV[7]), tonumber(ARGV[8]),
    ARGV[9], ARGV[10], tonumber(ARGV[11])
redis.call('ZREMRANGEBYSCORE', queue, '-inf', now - waitms)
if tlimit > 0 and cost > tlimit then return {'too_large', 0} end
if blimit > 0 and cost > blimit then return {'quota', 0} end
if blimit > 0 and tonumber(redis.call('GET', budget) or '0') + cost > blimit then
    return {'quota', 0}
end
local rank = redis.call('ZRANK', queue, ticket)
local existing = redis.call('GET', ticket)
if existing and existing ~= fingerprint then return {'invalid_ticket', 0} end
if existing and not rank then return {'invalid_ticket', 0} end
if not existing and ARGV[12] == '1' then return {'invalid_ticket', 0} end
if existing and rank and rank > 0 then return {'queued', rank + 1} end
if not existing and redis.call('ZCARD', queue) > 0 and mode == 'queue' then
    redis.call('ZADD', queue, now, ticket)
    redis.call('SET', ticket, fingerprint, 'PX', waitms)
    redis.call('PEXPIRE', queue, waitms + 1000)
    return {'queued', redis.call('ZCARD', queue)}
end
local limited = (qlimit > 0 and tonumber(redis.call('GET', qps) or '0') >= qlimit)
    or (tlimit > 0 and tonumber(redis.call('GET', tpm) or '0') + cost > tlimit)
if limited then
    if mode == 'queue' then
        if not existing then
            redis.call('ZADD', queue, now, ticket)
            redis.call('SET', ticket, fingerprint, 'PX', waitms)
            redis.call('PEXPIRE', queue, waitms + 1000)
        end
        return {'queued', (redis.call('ZRANK', queue, ticket) or 0) + 1}
    end
    return {'limited', 0}
end
if qlimit > 0 then redis.call('INCR', qps); redis.call('PEXPIRE', qps, qttl) end
if tlimit > 0 then redis.call('INCRBY', tpm, cost); redis.call('PEXPIRE', tpm, tttl) end
if blimit > 0 then redis.call('INCRBY', budget, cost); redis.call('PEXPIRE', budget, bttl) end
if existing then redis.call('ZREM', queue, ticket); redis.call('DEL', ticket) end
return {'admitted', 0}
"""

SETTLE = """
local difference = tonumber(ARGV[1])
if tonumber(ARGV[2]) > 0 and redis.call('EXISTS', KEYS[1]) == 1 then
    redis.call('INCRBY', KEYS[1], difference)
end
if tonumber(ARGV[3]) > 0 and redis.call('EXISTS', KEYS[2]) == 1 then
    redis.call('INCRBY', KEYS[2], difference)
end
"""

POSITION = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', tonumber(ARGV[1]) - tonumber(ARGV[2]))
if not redis.call('GET', KEYS[2]) then return 0 end
local rank = redis.call('ZRANK', KEYS[1], KEYS[2])
return rank and rank + 1 or 0
"""


def period(now: datetime, kind: str | None) -> tuple[str, int]:
    if kind == "week":
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        end = start + timedelta(days=7)
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (
            start.replace(year=start.year + 1, month=1)
            if start.month == 12 else start.replace(month=start.month + 1)
        )
    return start.strftime("%Y%m%d"), max(1, int((end - now).total_seconds() * 1000))


@dataclass
class Reservation:
    tpm_key: str
    budget_key: str
    tokens: int
    tpm_enabled: bool
    budget_enabled: bool


class Limiter:
    def __init__(self, client: redis.Redis):
        self.client = client

    def keys(self, key: ApiKey, now: datetime) -> tuple[list[str], int, int, int]:
        stamp = int(now.timestamp() * 1000)
        prefix = f"gateway:key:{key.id}"
        budget_stamp, budget_ttl = period(now, key.budget_period)
        return [
            f"{prefix}:qps:{stamp // 1000}",
            f"{prefix}:tpm:{stamp // 60000}",
            f"{prefix}:budget:{key.budget_period}:{budget_stamp}",
            f"{prefix}:queue",
        ], 1000 - stamp % 1000, 60000 - stamp % 60000, budget_ttl

    async def admit(self, key: ApiKey, cost: int, fingerprint: str, ticket: str | None,
                    now: datetime | None = None) -> tuple[str, int, str, Reservation | None]:
        now = now or datetime.now(UTC)
        keys, qttl, tttl, bttl = self.keys(key, now)
        token = ticket or uuid4().hex
        result = await self.client.eval(
            ADMIT, 5, *keys, f"gateway:ticket:{key.id}:{token}",
            int(now.timestamp() * 1000), cost, key.qps_limit or 0, key.tpm_limit or 0,
            key.token_budget or 0, qttl, tttl, bttl, key.wait_mode or "block",
            fingerprint, key.max_wait_ms or 30000, int(ticket is not None),
        )
        state = result[0].decode() if isinstance(result[0], bytes) else result[0]
        reservation = Reservation(keys[1], keys[2], cost, bool(key.tpm_limit),
                                  bool(key.token_budget)) if state == "admitted" else None
        return state, int(result[1]), token, reservation

    async def settle(self, reservation: Reservation, actual: int) -> None:
        await self.client.eval(
            SETTLE, 2, reservation.tpm_key, reservation.budget_key,
            actual - reservation.tokens, int(reservation.tpm_enabled),
            int(reservation.budget_enabled),
        )

    async def position(self, key: ApiKey, ticket: str) -> int:
        keys, _, _, _ = self.keys(key, datetime.now(UTC))
        return int(await self.client.eval(
            POSITION, 2, keys[3], f"gateway:ticket:{key.id}:{ticket}",
            int(datetime.now(UTC).timestamp() * 1000), key.max_wait_ms or 30000,
        ))

    async def wait(self, key: ApiKey, cost: int, fingerprint: str):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (key.max_wait_ms or 30000) / 1000
        while True:
            result = await self.admit(key, cost, fingerprint, None)
            if result[0] != "limited" or loop.time() >= deadline:
                return result
            await asyncio.sleep(min(0.1, max(0, deadline - loop.time())))


def limiter() -> Limiter:
    return Limiter(redis.from_url(
        get_settings().redis_url, decode_responses=False,
        socket_connect_timeout=2, socket_timeout=2,
    ))


def unavailable(exc: RedisError) -> None:
    from fastapi import HTTPException

    raise HTTPException(503, "限流服务不可用，网关已拒绝请求。") from exc
