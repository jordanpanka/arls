import os
import re

from app.evidence.schemas import Evidence
from app.evidence.store import EvidenceStore
from app.models.models import (
    Citation,
    CodeEvidence,
    GraphEdge,
    GraphEvidence,
    GraphNode,
    MetricEvidence,
    MetricItem,
)
from app.services.evidence_service import language_for_path, merge_highlights

ALIAS_ORDER = {"SOURCE": 0, "GRAPH": 1, "METRIC": 2, "HISTORY": 3}
NODE_TYPES = {"function": "Function", "method": "Method", "class": "Class", "file": "File", "module": "Module"}


def _alias_sort_key(alias: str) -> tuple[int, int]:
    prefix, _, number = alias.partition("_")
    return ALIAS_ORDER.get(prefix, 9), int(number) if number.isdigit() else 0


def _union(lists: list[list[str]]) -> list[str]:
    merged: list[str] = []
    for values in lists:
        for value in values:
            if value not in merged:
                merged.append(value)
    return merged


def _code(alias: str, items: list[Evidence]) -> CodeEvidence | None:
    located = [e for e in items if e.file_path]
    if not located:
        return None
    first = located[0]
    scores = [e.retrieval_score for e in located if e.retrieval_score is not None]
    produced = _union([e.produced_by for e in located])
    return CodeEvidence(
        id=alias,
        fileName=os.path.basename(first.file_path),
        filePath=first.file_path,
        language=first.language or language_for_path(first.file_path),
        highlights=merge_highlights([(e.start_line, e.end_line) for e in located]),
        symbols=_union([[e.symbol_name] for e in located if e.symbol_name]),
        retrievalType=", ".join(produced) or None,
        score=max(scores) if scores else None,
        evidenceIds=[e.evidence_id for e in located],
        producedBy=produced,
        certainty=first.certainty,
    )


def _kind_from_symbol_id(symbol_id: str) -> str:
    if symbol_id.startswith("module::"):
        return "Module"
    if symbol_id.endswith("::file"):
        return "File"
    parts = symbol_id.split("::")
    return NODE_TYPES.get(parts[1], "Function") if len(parts) >= 3 else "Function"


def _line_of(symbol_id: str) -> int | None:
    match = re.search(r"@(\d+)$", symbol_id)
    return int(match.group(1)) or None if match else None


def _graph(alias: str, items: list[Evidence]) -> GraphEvidence | None:
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    def add_node(node_id: str, label: str, path: str | None, start: int | None, end: int | None, used: bool, kind: str | None = None):
        existing = nodes.get(node_id)
        if existing is not None:
            existing.usedAsEvidence = existing.usedAsEvidence or used
            return
        nodes[node_id] = GraphNode(
            id=node_id,
            label=label,
            type=NODE_TYPES.get(kind or "", None) or _kind_from_symbol_id(node_id),
            filePath=path,
            startLine=start,
            endLine=end,
            usedAsEvidence=used,
        )

    for e in items:
        if e.source_type == "graph_node" and e.symbol_id:
            add_node(e.symbol_id, e.symbol_name or e.symbol_id, e.file_path, e.start_line, e.end_line, True, e.symbol_kind)
        if e.relation is not None:
            r = e.relation
            add_node(r.source, r.source_label, r.source_path, r.source_line, None, False)
            add_node(r.target, r.target_label, r.target_path, r.target_line or _line_of(r.target), None, False)
            edges.append(GraphEdge(source=r.source, target=r.target, type=r.type, certainty=e.certainty))

    if not nodes:
        return None
    return GraphEvidence(
        id=alias,
        nodes=list(nodes.values()),
        edges=edges,
        evidenceIds=[e.evidence_id for e in items],
        producedBy=_union([e.produced_by for e in items]),
    )


def _metric(alias: str, items: list[Evidence]) -> MetricEvidence | None:
    e = next((i for i in items if i.metric is not None), None)
    if e is None:
        return None
    m = e.metric
    return MetricEvidence(
        id=alias,
        scope=m.scope,
        title=m.title,
        fileName=os.path.basename(e.file_path) if e.file_path else None,
        filePath=e.file_path,
        symbol=m.symbol,
        startLine=e.start_line,
        endLine=e.end_line,
        analysisId=m.analysis_id,
        analyzedAt=m.analyzed_at,
        commitSha=m.commit_sha,
        items=[
            MetricItem(key=v.key, label=f"{v.label} [{v.analyzer}]", value=v.value, unit=v.unit, category=v.category)
            for v in m.items
        ],
        evidenceIds=[i.evidence_id for i in items],
        producedBy=_union([i.produced_by for i in items]),
    )


def selected_aliases(store: EvidenceStore, cited: list[str], limit: int) -> list[str]:
    chosen = [a for a in cited if a in store.by_alias]
    for alias in store.by_alias:
        if len(chosen) >= limit:
            break
        if alias not in chosen:
            chosen.append(alias)
    return sorted(chosen, key=_alias_sort_key)


def project_evidence(store: EvidenceStore, cited: list[str], limit: int) -> list:
    projected = []
    for alias in selected_aliases(store, cited, limit):
        items = store.evidence_for(alias)
        prefix = alias.split("_")[0]
        builder = {"SOURCE": _code, "GRAPH": _graph, "METRIC": _metric}.get(prefix)
        if builder is None:
            continue
        item = builder(alias, items)
        if item is not None:
            projected.append(item)
    return projected


def build_citations(store: EvidenceStore, cited: list[str]) -> list[Citation]:
    citations = []
    for alias in cited:
        ids = store.ids_for(alias)
        if not ids:
            continue
        citations.append(Citation(alias=alias, type=alias.split("_")[0].lower(), evidenceIds=ids))
    return citations


def raw_evidence(store: EvidenceStore, cited: list[str], limit: int, content_chars: int = 1200) -> list[dict]:
    rows = []
    for alias in selected_aliases(store, cited, limit):
        for e in store.evidence_for(alias):
            data = e.model_dump(exclude={"group"})
            if data.get("content") and len(data["content"]) > content_chars:
                data["content"] = data["content"][:content_chars] + "\n[... truncated]"
            data["alias"] = alias
            rows.append(data)
    return rows
