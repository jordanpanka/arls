import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.metrics.analyzer import SourceFile
from app.metrics.graph_metrics import Neo4jGraphMetricsAnalyzer
from app.metrics.lizard_analyzer import LizardAnalyzer
from app.metrics.models import GraphMetricsRequest
from app.models.models import ServiceResult

router = APIRouter(prefix="/api/metrics", tags=["api", "metrics"])

# Stateless: the backend persists the results, nothing is kept here between calls.
static_analyzer = LizardAnalyzer()
graph_analyzer = Neo4jGraphMetricsAnalyzer()


@router.post("/static")
async def analyze_static(
    files: list[UploadFile] = File(...),
    paths: list[str] = Form(...),
):
    if len(files) != len(paths):
        raise HTTPException(status_code=400, detail="files and paths must have the same length")

    sources = [SourceFile(path=path, content=await file.read()) for file, path in zip(files, paths)]
    # Lizard is CPU bound; keep the event loop free for chat requests.
    result = await asyncio.to_thread(static_analyzer.analyze, sources)
    print(f"Lizard: {len(result.files)} fajl elemezve, {len(result.skipped)} kihagyva, {result.durationMs:.0f} ms")
    return ServiceResult.success(result.model_dump())


@router.post("/graph")
async def analyze_graph(request: GraphMetricsRequest):
    try:
        result = await asyncio.to_thread(
            graph_analyzer.analyze, request.userId, request.investigationId, request.projectId
        )
    except Exception as e:
        # Reported, not raised: the backend keeps the static metrics and marks the run partial.
        print("Graph metrics hiba:", e)
        return ServiceResult.fail(f"Graph metrics failed: {e}")

    print(f"Graf metrikak: {len(result.files)} fajl, {result.dependencyCount} fuggoseg, {result.durationMs:.0f} ms")
    return ServiceResult.success(result.model_dump())
