from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from app.models.models import Ids, ServiceResult
from app.services.file_service import FileService

router = APIRouter(prefix="/api/chat/files", tags=["api", "chat", "files"])


@router.post("/upload")
async def upload(
    user_id: int = Form(...),
    inv_id: int = Form(...),
    project_id: int = Form(...),
    files: list[UploadFile] = File(...),
    paths: list[str]=Form()
):
    #JAVITAS
    file_service=FileService()
    result = await file_service.upload_qdrant_async(
        user_id=user_id,
        files=files,
        inv_id=inv_id, 
        project_id=project_id,
        paths=paths
    )

    if not result.is_success:
        raise HTTPException(status_code=400, detail=result.message)

    return result