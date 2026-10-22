import pytest
from fastapi import HTTPException

from app.api.gateway.router import ChatBody
from app.db.models import ProviderModel
from app.modules.gateway.generation import validate_output_tokens
from app.modules.model.router import AccessModelUpdate


def test_model_limits_are_independent_and_allow_large_requests():
    body = ChatBody(model="AAA", messages=[{"role": "user", "content": "Hello"}],
                    max_tokens=64000)
    changes = AccessModelUpdate(context_window=128000, max_output_tokens=64000)
    model = ProviderModel(access_model_code="large", context_window=changes.context_window,
                          max_output_tokens=changes.max_output_tokens)
    validate_output_tokens(model, body.max_tokens)
    with pytest.raises(HTTPException) as exc:
        validate_output_tokens(model, 64001)
    assert exc.value.status_code == 422
    assert exc.value.detail["max_output_tokens"] == 64000
    model.max_output_tokens = None
    validate_output_tokens(model, 128000)
    assert model.context_window == 128000
