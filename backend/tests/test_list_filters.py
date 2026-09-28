import json
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    select,
)

from app.core.list_filters import filter_expression


def test_and_or_filters_run_before_limit():
    engine = create_engine("sqlite://")
    table = Table("records", MetaData(),
                  Column("id", Integer, primary_key=True),
                  Column("name", String), Column("enabled", Boolean),
                  Column("created_at", DateTime))
    table.create(engine)
    with engine.begin() as connection:
        connection.execute(table.insert(), [
            {"id": 1, "name": "Alpha", "enabled": True, "created_at": datetime(2026, 9, 28, 10)},
            {"id": 2, "name": "Beta", "enabled": False, "created_at": datetime(2026, 9, 27, 10)},
            {"id": 3, "name": "Alpine", "enabled": True, "created_at": datetime(2026, 9, 28, 22)},
        ])
        columns = {
            "id": (table.c.id, "number"),
            "name": (table.c.name, "text"),
            "enabled": (table.c.enabled, "boolean", {"0", "1"}),
            "created_at": (table.c.created_at, "date"),
        }
        conditions = [
            {"field": "name", "operator": "contains", "value": "alp"},
            {"field": "enabled", "operator": "eq", "value": "0"},
        ]
        matching = filter_expression(json.dumps({"mode": "or", "conditions": conditions}), columns)
        assert connection.execute(select(table.c.id).where(matching).order_by(
            table.c.id).limit(2)).scalars().all() == [1, 2]
        matching = filter_expression(json.dumps({"mode": "and", "conditions": conditions}), columns)
        assert connection.execute(select(table.c.id).where(matching)).scalars().all() == []
        exact = filter_expression(json.dumps({"mode": "and", "conditions": [
            {"field": "id", "operator": "eq", "value": "1"},
        ]}), columns)
        assert connection.execute(select(table.c.id).where(exact)).scalar_one() == 1
        day = filter_expression(json.dumps({"mode": "and", "conditions": [
            {"field": "created_at", "operator": "eq", "value": "2026-09-28"},
        ]}), columns)
        assert connection.execute(select(table.c.id).where(day).order_by(
            table.c.id)).scalars().all() == [1, 3]


@pytest.mark.parametrize("condition", [
    {"field": "secret", "operator": "eq", "value": "x"},
    {"field": "id", "operator": "contains", "value": "1"},
    {"field": "id", "operator": "eq", "value": "one"},
    {"field": "enabled", "operator": "eq", "value": "2"},
    {"field": "name", "operator": "gt", "value": "x"},
])
def test_invalid_filter_rejected(condition):
    columns = {"id": (Column(Integer), "number"), "name": (Column(String), "text"),
               "enabled": (Column(Boolean), "boolean", {"0", "1"})}
    with pytest.raises(HTTPException) as error:
        filter_expression(json.dumps({"mode": "and", "conditions": [condition]}), columns)
    assert error.value.status_code == 422
