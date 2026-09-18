from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.demo_data import MODEL_NODES, build_page
from app.core.responses import success_response
from app.db.models import ModelNode
from app.db.session import get_db

router = APIRouter(prefix="/nodes", tags=["节点管理"])


@router.get("")
async def list_nodes(db: Session = Depends(get_db)) -> dict:
    try:
        nodes = db.scalars(select(ModelNode).order_by(ModelNode.id)).all()
        data = build_page(
            [
                {
                    "id": item.id,
                    "node_code": item.node_code,
                    "node_name": item.node_name,
                    "provider_id": item.provider_id,
                    "provider_model_id": item.provider_model_id,
                    "model_type": item.model_type,
                    "status": item.status,
                    "health_status": item.health_status,
                    "weight": item.weight,
                    "priority": item.priority,
                    "region": item.region,
                }
                for item in nodes
            ]
        )
    except SQLAlchemyError:
        data = build_page(MODEL_NODES)

    return success_response(data).model_dump()
