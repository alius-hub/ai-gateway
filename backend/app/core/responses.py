from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T | None = None
    request_id: str = Field(default="local-dev")


def success_response(data: Any = None, message: str = "ok") -> Envelope[Any]:
    return Envelope(data=data, message=message)
