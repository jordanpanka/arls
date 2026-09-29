from pydantic import BaseModel
from dataclasses import dataclass
from typing import Any


@dataclass
class ServiceResult:
    is_success: bool
    message: str | None = None
    data: Any = None

    @staticmethod
    def success(data: Any = None) -> "ServiceResult":
        return ServiceResult(is_success=True, data=data)

    @staticmethod
    def fail(message: str) -> "ServiceResult":
        return ServiceResult(is_success=False, message=message)


class Ids(BaseModel):
    inv_id: int
    project_id: int
    
class ChatRequest(BaseModel):
    prompt: str
    userId:int
    investigationId:int
    projectId:int