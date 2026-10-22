from fastapi import HTTPException

from app.db.models import ProviderModel


def validate_output_tokens(model: ProviderModel, value: int) -> None:
    limit = model.max_output_tokens
    if limit is not None and value > limit:
        raise HTTPException(422, {
            "code": "max_tokens_exceeded",
            "message": (f"max_tokens 超过接入模型 {model.access_model_code} "
                        f"的最大输出 Token 上限 {limit}"),
            "max_output_tokens": limit,
        })
