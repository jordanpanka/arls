from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.tools.base import ToolContext, ToolFailure, ToolResult, ToolSpec, safe_relative_path

HISTORY_UNAVAILABLE = (
    "git history is not ingested: repositories are imported as GitHub zipball snapshots without commit history"
)


class FileHistoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=400)
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        return safe_relative_path(value)


class ChurnArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str | None = Field(default=None, max_length=400)
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("path")
    @classmethod
    def _path(cls, value: str | None) -> str | None:
        return safe_relative_path(value) if value else None


async def _unavailable(ctx: ToolContext, args: BaseModel) -> ToolResult:
    raise ToolFailure("unavailable", HISTORY_UNAVAILABLE)


HISTORY_TOOLS = [
    ToolSpec(
        name="get_file_history",
        description="Commits that changed a file (requires ingested git history).",
        args_schema=FileHistoryArgs,
        handler=_unavailable,
        category="history",
        cacheable=False,
    ),
    ToolSpec(
        name="get_code_churn",
        description="Lines added/removed per file over time (requires ingested git history).",
        args_schema=ChurnArgs,
        handler=_unavailable,
        category="history",
        cacheable=False,
    ),
    ToolSpec(
        name="find_cochanged_files",
        description="Files that are frequently changed together with a file (requires ingested git history).",
        args_schema=FileHistoryArgs,
        handler=_unavailable,
        category="history",
        cacheable=False,
    ),
]
