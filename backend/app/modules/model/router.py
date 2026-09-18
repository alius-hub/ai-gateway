from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.demo_data import AGGREGATED_MODELS, PROVIDER_MODELS, build_page
from app.core.responses import success_response
from app.db.models import AggregatedModel, ProviderModel
from app.db.session import get_db

router = APIRouter(tags=["模型治理"])


@router.get("/access-models")
async def list_access_models(db: Session = Depends(get_db)) -> dict:
    try:
        models = db.scalars(select(ProviderModel).order_by(ProviderModel.id)).all()
        data = build_page(
            [
                {
                    "id": item.id,
                    "provider_id": item.provider_id,
                    "access_model_code": item.access_model_code,
                    "provider_model_name": item.provider_model_name,
                    "model_type": item.model_type,
                    "status": item.status,
                    "currency": item.currency,
                }
                for item in models
            ]
        )
    except SQLAlchemyError:
        data = build_page(PROVIDER_MODELS)

    return success_response(data).model_dump()


@router.get("/aggregate-models")
async def list_aggregate_models(db: Session = Depends(get_db)) -> dict:
    try:
        models = db.scalars(select(AggregatedModel).order_by(AggregatedModel.id)).all()
        data = build_page(
            [
                {
                    "id": item.id,
                    "aggregate_model_code": item.aggregate_model_code,
                    "public_model_name": item.public_model_name,
                    "model_type": item.model_type,
                    "default_routing_strategy": item.default_routing_strategy,
                    "status": item.status,
                    "description": item.description,
                }
                for item in models
            ]
        )
    except SQLAlchemyError:
        data = build_page(AGGREGATED_MODELS)

    return success_response(data).model_dump()
