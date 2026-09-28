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
local qps, tpm, budget, queue, ticket, money, project = unpack(KEYS)
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
local cents, money_limit = tonumber(ARGV[13]), tonumber(ARGV[14])
local project_limit, money_ttl = tonumber(ARGV[15]), tonumber(ARGV[16])
if money_limit > 0 and tonumber(redis.call('GET', money) or '0') < tonumber(ARGV[17]) then
    redis.call('SET', money, ARGV[17], 'PX', money_ttl)
end
if project_limit > 0 and tonumber(redis.call('GET', project) or '0') < tonumber(ARGV[18]) then
    redis.call('SET', project, ARGV[18])
end
if money_limit > 0 and tonumber(redis.call('GET', money) or '0') + cents > money_limit then
    return {'amount_quota', 0}
end
if project_limit > 0 and tonumber(redis.call('GET', project) or '0') + cents > project_limit then
    return {'project_budget', 0}
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
if money_limit > 0 then
    redis.call('INCRBY', money, cents)
    redis.call('PEXPIRE', money, money_ttl)
end
if project_limit > 0 then redis.call('INCRBY', project, cents) end
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
local cents_difference = tonumber(ARGV[4])
if tonumber(ARGV[5]) > 0 and redis.call('EXISTS', KEYS[3]) == 1 then
    redis.call('INCRBY', KEYS[3], cents_difference)
end
if tonumber(ARGV[6]) > 0 and redis.call('EXISTS', KEYS[4]) == 1 then
    redis.call('INCRBY', KEYS[4], cents_difference)
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
    money_key: str = ""
    project_key: str = ""
    cents: int = 0
    money_enabled: bool = False
    project_enabled: bool = False


def cooldown_key(model_id: int) -> str:
    return f"gateway:model:{model_id}:cooldown"


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
                    now: datetime | None = None, *, cents: int = 0,
                    project_id: int | None = None, project_limit: int = 0,
                    money_baseline: int = 0, project_baseline: int = 0
                    ) -> tuple[str, int, str, Reservation | None]:
        now = now or datetime.now(UTC)
        keys, qttl, tttl, bttl = self.keys(key, now)
        money_key = f"{keys[2]}:amount"
        project_key = (
            f"gateway:project:{project_id}:amount" if project_id else "gateway:project:none"
        )
        token = ticket or uuid4().hex
        result = await self.client.eval(
            ADMIT, 7, *keys, f"gateway:ticket:{key.id}:{token}", money_key, project_key,
            int(now.timestamp() * 1000), cost, key.qps_limit or 0, key.tpm_limit or 0,
            key.token_budget or 0, qttl, tttl, bttl, key.wait_mode or "block",
            fingerprint, key.max_wait_ms or 30000, int(ticket is not None),
            cents, int(key.amount_budget * 100) if key.amount_budget is not None else 0,
            project_limit, bttl, money_baseline, project_baseline,
        )
        state = result[0].decode() if isinstance(result[0], bytes) else result[0]
        reservation = Reservation(keys[1], keys[2], cost, bool(key.tpm_limit),
                                  bool(key.token_budget), money_key, project_key, cents,
                                  key.amount_budget is not None, project_limit > 0
                                  ) if state == "admitted" else None
        return state, int(result[1]), token, reservation

    async def settle(self, reservation: Reservation, actual: int, actual_cents: int = 0) -> None:
        await self.client.eval(
            SETTLE, 4, reservation.tpm_key, reservation.budget_key,
            reservation.money_key, reservation.project_key,
            actual - reservation.tokens, int(reservation.tpm_enabled),
            int(reservation.budget_enabled), actual_cents - reservation.cents,
            int(reservation.money_enabled), int(reservation.project_enabled),
        )

    async def position(self, key: ApiKey, ticket: str) -> int:
        keys, _, _, _ = self.keys(key, datetime.now(UTC))
        return int(await self.client.eval(
            POSITION, 2, keys[3], f"gateway:ticket:{key.id}:{ticket}",
            int(datetime.now(UTC).timestamp() * 1000), key.max_wait_ms or 30000,
        ))

    async def wait(self, key: ApiKey, cost: int, fingerprint: str, *,
                   cents: int = 0, project_id: int | None = None, project_limit: int = 0,
                   money_baseline: int = 0, project_baseline: int = 0):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (key.max_wait_ms or 30000) / 1000
        while True:
            result = await self.admit(key, cost, fingerprint, None, cents=cents,
                                      project_id=project_id, project_limit=project_limit,
                                      money_baseline=money_baseline,
                                      project_baseline=project_baseline)
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
