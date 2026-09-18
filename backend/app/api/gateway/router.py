from fastapi import APIRouter

from app.core.responses import success_response

gateway_router = APIRouter(tags=["Gateway API"])


@gateway_router.get("/models")
async def list_models() -> dict:
    return {
        "data": [
            {
                "id": "chat-pro",
                "object": "model",
                "owned_by": "ai-gateway",
                "model_type": "llm",
                "capabilities": ["chat", "stream"],
            },
            {
                "id": "embedding-unified",
                "object": "model",
                "owned_by": "ai-gateway",
                "model_type": "embedding",
                "capabilities": ["embedding"],
            },
        ]
    }


@gateway_router.post("/chat/completions")
async def chat_completions() -> dict:
    return success_response(
        {
            "id": "chatcmpl-dev",
            "object": "chat.completion",
            "model": "chat-pro",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "AI Gateway 骨架已经就绪，可以继续接入真实供应商。",
                    },
                    "finish_reason": "stop",
                }
            ],
        }
    ).model_dump()


@gateway_router.post("/embeddings")
async def embeddings() -> dict:
    return success_response(
        {
            "object": "list",
            "data": [
                {
                    "object": "embedding",
                    "index": 0,
                    "embedding": [0.01, 0.02, 0.03],
                }
            ],
            "model": "embedding-unified",
        }
    ).model_dump()
