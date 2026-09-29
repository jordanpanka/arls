from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from app.models.models import Ids,ChatRequest
from app.services.chat_service import send_message_async, send_message_async_langgraph

router = APIRouter(prefix="/api/chat/files", tags=["api", "chat", "files"])

@router.post("/send")
async def sendMessage(prompt:ChatRequest):
    
    result=await send_message_async_langgraph(prompt)
    
    if not result.is_success:
        raise HTTPException(status_code=400, detail=result.message)

    return result