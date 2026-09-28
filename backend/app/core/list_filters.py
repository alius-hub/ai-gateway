"""Validated, allowlisted filters shared by admin list endpoints."""

import json
import operator
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import and_, or_


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(min_length=1, max_length=64)
    operator: Literal["contains", "eq", "ne", "gt", "gte", "lt", "lte"]
    value: str = Field(min_length=1, max_length=255)


class Group(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["and", "or"]
    conditions: list[Condition] = Field(max_length=8)


# The endpoint chooses which columns are exposed. Never resolve fields from user input.
FilterColumns = dict[str, tuple[object, Literal["text", "number", "decimal", "date", "select",
                                               "boolean"]]
                     | tuple[object, Literal["select", "boolean"], set[str]]]


def filter_expression(raw: str | None, columns: FilterColumns):
    if not raw:
        return None
    if len(raw) > 4096:
        raise HTTPException(422, "筛选条件过长。")
    try:
        group = Group.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, "筛选条件格式无效。") from exc
    expressions = []
    for condition in group.conditions:
        entry = columns.get(condition.field)
        if entry is None:
            raise HTTPException(422, "筛选字段无效。")
        column, kind = entry[:2]
        operation = condition.operator
        value = condition.value.strip()
        if len(entry) == 3 and value not in entry[2]:
            raise HTTPException(422, "筛选选项无效。")
        if (not value or (kind != "text" and operation == "contains")
                or (kind == "text" and operation not in ("contains", "eq", "ne"))
                or (kind in ("select", "boolean") and operation not in ("eq", "ne"))):
            raise HTTPException(422, "此字段不支持该筛选值或运算符。")
        if kind == "text":
            pass
        elif kind in ("number", "select", "boolean"):
            try:
                value = int(value)
            except ValueError as exc:
                if kind == "select":
                    value = condition.value.strip()
                else:
                    raise HTTPException(422, "数字筛选值格式无效。") from exc
            if isinstance(value, int) and not 0 <= value <= 9223372036854775807:
                raise HTTPException(422, "数字筛选值超出范围。")
            if kind == "boolean":
                value = bool(value)
        elif kind == "decimal":
            try:
                value = Decimal(value)
            except InvalidOperation as exc:
                raise HTTPException(422, "金额筛选值格式无效。") from exc
            if not value.is_finite() or value < 0:
                raise HTTPException(422, "金额筛选值超出范围。")
        elif kind == "date":
            try:
                if len(value) != 10:
                    raise ValueError()
                value = datetime.combine(date.fromisoformat(value), time.min)
            except ValueError as exc:
                raise HTTPException(422, "日期筛选值格式无效。") from exc
        if kind == "date" and operation in ("eq", "ne"):
            try:
                next_day = value + timedelta(days=1)
            except OverflowError as exc:
                raise HTTPException(422, "日期筛选值超出范围。") from exc
            day = and_(column >= value, column < next_day)
            expressions.append(day if operation == "eq" else ~day)
        elif operation == "contains":
            escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            expressions.append(column.ilike(f"%{escaped}%", escape="\\"))
        else:
            expressions.append({
                "eq": operator.eq, "ne": operator.ne,
                "gt": operator.gt, "gte": operator.ge,
                "lt": operator.lt, "lte": operator.le,
            }[condition.operator](column, value))
    if not expressions:
        return None
    return and_(*expressions) if group.mode == "and" else or_(*expressions)
