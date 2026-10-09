import os
import re

from app.models.models import (
    CodeEvidence,
    GraphEdge,
    GraphEvidence,
    GraphNode,
    Highlight,
    MetricEvidence,
    MetricItem,
)

LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".cs": "csharp",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".c": "c",
    ".h": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".xml": "xml",
    ".toml": "ini",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".properties": "ini",
    ".sql": "sql",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
}

LANGUAGE_BY_FILENAME = {
    "dockerfile": "dockerfile",
    "containerfile": "dockerfile",
    "makefile": "shell",
}

GRAPH_NODE_TYPES = ["Function", "Method", "Class", "File", "Module"]
MAX_GRAPH_NODES = 40


def normalize_path(path: str | None) -> str:
    return (path or "").replace("\\", "/").strip().lstrip("/")


def language_for_path(path: str | None) -> str:
    filename = os.path.basename(normalize_path(path)).lower()
    if filename in LANGUAGE_BY_FILENAME:
        return LANGUAGE_BY_FILENAME[filename]
    return LANGUAGE_BY_EXTENSION.get(os.path.splitext(filename)[1], "plaintext")


def short_symbol_name(name: str | None) -> str:
    return re.split(r"\.|->|::", name or "")[-1].strip()


def _line(value) -> int | None:
    try:
        line = int(value)
    except (TypeError, ValueError):
        return None
    return line if line > 0 else None


def result_location(result: dict) -> dict:
    payload = result.get("payload", {}) or {}
    file_path = normalize_path(payload.get("filePath") or payload.get("path"))
    return {
        "filePath": file_path,
        "fileName": payload.get("fileName") or payload.get("docName") or os.path.basename(file_path),
        "language": payload.get("language") or language_for_path(file_path),
        "symbolName": payload.get("symbolName") or payload.get("name") or "",
        "symbolType": payload.get("symbolType") or payload.get("kind") or "",
        "startLine": _line(payload.get("startLine", payload.get("start_line"))),
        "endLine": _line(payload.get("endLine", payload.get("end_line"))),
    }


def merge_highlights(ranges: list[tuple[int | None, int | None]]) -> list[Highlight]:
    """Drops duplicates and joins overlapping/adjacent ranges.

    A range nested inside another is kept on its own, so a method stays
    navigable even when its whole class was retrieved too.
    """
    cleaned = sorted({
        (start, end if end and end >= start else start)
        for start, end in ranges
        if start
    })

    merged: list[tuple[int, int]] = []
    for start, end in cleaned:
        if merged:
            prev_start, prev_end = merged[-1]
            nested = start >= prev_start and end <= prev_end
            if not nested and start <= prev_end + 1:
                merged[-1] = (prev_start, max(prev_end, end))
                continue
        merged.append((start, end))

    return [Highlight(startLine=s, endLine=e) for s, e in merged]


def build_code_evidence(results: list[dict]) -> tuple[list[CodeEvidence], dict[str, str]]:
    groups: dict[str, dict] = {}

    for result in results:
        location = result_location(result)
        path = location["filePath"]
        if not path:
            continue

        group = groups.setdefault(path, {
            "location": location,
            "ranges": [],
            "symbols": [],
            "vectors": [],
            "score": None,
        })

        group["ranges"].append((location["startLine"], location["endLine"]))

        symbol = location["symbolName"]
        if symbol and symbol not in group["symbols"]:
            group["symbols"].append(symbol)

        vector = result.get("matched_vector") or result.get("retrieval_type")
        if vector and vector not in group["vectors"]:
            group["vectors"].append(vector)

        score = result.get("score")
        if isinstance(score, (int, float)) and (group["score"] is None or score > group["score"]):
            group["score"] = float(score)

    ordered = sorted(groups.items(), key=lambda item: item[1]["score"] or 0, reverse=True)

    evidence: list[CodeEvidence] = []
    source_ids: dict[str, str] = {}

    for index, (path, group) in enumerate(ordered, start=1):
        source_id = f"SOURCE_{index}"
        source_ids[path] = source_id
        location = group["location"]
        evidence.append(CodeEvidence(
            id=source_id,
            fileName=location["fileName"],
            filePath=path,
            language=location["language"],
            highlights=merge_highlights(group["ranges"]),
            symbols=group["symbols"],
            retrievalType=", ".join(group["vectors"]) or None,
            score=group["score"],
        ))

    return evidence, source_ids


def _node_type(labels: list[str]) -> str:
    for candidate in GRAPH_NODE_TYPES:
        if candidate in labels:
            return candidate
    return labels[0] if labels else "Node"


def _node_label(node_type: str, props: dict) -> str:
    if node_type == "File":
        return props.get("name") or os.path.basename(props.get("path") or "") or "file"
    if node_type == "Method" and props.get("className"):
        return f"{props['className']}.{props.get('name', '')}"
    return props.get("name") or "?"


def to_graph_node(raw: dict, used_as_evidence: bool) -> GraphNode:
    props = raw.get("props", {}) or {}
    node_type = _node_type(list(raw.get("labels", [])))
    file_path = props.get("filePath") or (props.get("path") if node_type == "File" else None)
    return GraphNode(
        id=str(raw["id"]),
        label=_node_label(node_type, props),
        type=node_type,
        filePath=normalize_path(file_path) or None,
        startLine=_line(props.get("startLine")),
        endLine=_line(props.get("endLine")),
        usedAsEvidence=used_as_evidence,
    )


def build_graph_evidence(subgraphs: list[dict], evidence_id: str = "GRAPH_1") -> GraphEvidence | None:
    """Merges per-result subgraphs into one fragment.

    Retrieved roots come first so the node cap never drops them; edges are kept
    only between nodes that made it into the fragment.
    """
    nodes: dict[str, GraphNode] = {}

    for subgraph in subgraphs:
        for raw in subgraph.get("nodes", []):
            if str(raw["id"]) == str(subgraph.get("root")):
                node = to_graph_node(raw, used_as_evidence=True)
                if node.id in nodes:
                    nodes[node.id].usedAsEvidence = True
                elif len(nodes) < MAX_GRAPH_NODES:
                    nodes[node.id] = node

    for subgraph in subgraphs:
        for raw in subgraph.get("nodes", []):
            node_id = str(raw["id"])
            if node_id not in nodes and len(nodes) < MAX_GRAPH_NODES:
                nodes[node_id] = to_graph_node(raw, used_as_evidence=False)

    if not nodes:
        return None

    edges: list[GraphEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for subgraph in subgraphs:
        for raw in subgraph.get("edges", []):
            key = (str(raw["source"]), str(raw["target"]), raw["type"])
            if key in seen or key[0] not in nodes or key[1] not in nodes:
                continue
            seen.add(key)
            edges.append(GraphEdge(source=key[0], target=key[1], type=key[2]))

    return GraphEvidence(id=evidence_id, nodes=list(nodes.values()), edges=edges)


def subgraph_to_text(subgraph: dict) -> str:
    labels = {
        str(raw["id"]): to_graph_node(raw, used_as_evidence=False)
        for raw in subgraph.get("nodes", [])
    }
    root = labels.get(str(subgraph.get("root")))
    if root is None:
        return ""

    lines = [f"Knowledge graph around {root.label} ({root.filePath or 'unknown path'}):"]
    for edge in subgraph.get("edges", []):
        source = labels.get(str(edge["source"]))
        target = labels.get(str(edge["target"]))
        if source and target:
            lines.append(f"- {source.label} -[{edge['type']}]-> {target.label}")

    return "\n".join(lines) if len(lines) > 1 else ""


# (key, label, unit, category key) - the order is the order shown to the LLM and the UI.
REPOSITORY_METRIC_ITEMS = [
    ("totalFiles", "Files analyzed", None, None),
    ("totalNloc", "Lines of code (NLOC)", "lines", None),
    ("totalFunctions", "Functions", None, None),
    ("totalClasses", "Class-like declarations", None, None),
    ("averageComplexity", "Average cyclomatic complexity", None, None),
    ("maxComplexity", "Maximum cyclomatic complexity", None, "maxComplexityCategory"),
    ("highComplexityFunctionCount", "High-complexity functions", None, None),
    ("longFunctionCount", "Long functions", None, None),
    ("manyParameterFunctionCount", "Functions with many parameters", None, None),
    ("dependencyCount", "File dependencies", None, None),
    ("cycleCount", "Dependency cycles", None, None),
    ("averageFanIn", "Average file fan-in", None, None),
    ("averageFanOut", "Average file fan-out", None, None),
    ("maxFanIn", "Maximum file fan-in", None, None),
    ("maxFanOut", "Maximum file fan-out", None, None),
    ("maxDependencyDepth", "Maximum dependency depth", None, None),
]

FILE_METRIC_ITEMS = [
    ("nloc", "Lines of code (NLOC)", "lines", None),
    ("functionCount", "Functions", None, None),
    ("classCount", "Class-like declarations", None, None),
    ("averageComplexity", "Average cyclomatic complexity", None, None),
    ("maxComplexity", "Maximum cyclomatic complexity", None, "complexityCategory"),
    ("highComplexityFunctionCount", "High-complexity functions", None, None),
    ("maxFunctionNloc", "Longest function (NLOC)", "lines", None),
    ("longFunctionCount", "Long functions", None, None),
    ("manyParameterFunctionCount", "Functions with many parameters", None, None),
    ("fanIn", "Fan-in (files depending on it)", None, None),
    ("fanOut", "Fan-out (files it depends on)", None, None),
    ("importCount", "Import statements", None, None),
]

FUNCTION_METRIC_ITEMS = [
    ("cyclomaticComplexity", "Cyclomatic complexity", None, "complexityCategory"),
    ("nloc", "Lines of code (NLOC)", "lines", None),
    ("parameterCount", "Parameters", None, None),
    ("tokenCount", "Tokens", None, None),
    ("length", "Length", "lines", None),
    ("fanIn", "Fan-in (calling functions)", None, None),
    ("fanOut", "Fan-out (called functions)", None, None),
]

def _metric_items(source: dict, spec: list[tuple]) -> list[MetricItem]:
    items = []
    for key, label, unit, category_key in spec:
        value = source.get(key)
        if value is None:
            continue
        if isinstance(value, float):
            value = round(value, 2)
        items.append(MetricItem(
            key=key,
            label=label,
            value=value,
            unit=unit,
            category=source.get(category_key) if category_key else None,
        ))
    return items


def _dedupe(rows: list[dict], key) -> list[dict]:
    seen, unique = set(), []
    for row in rows:
        k = key(row)
        if k not in seen:
            seen.add(k)
            unique.append(row)
    return unique


def build_metric_evidence(metrics: dict | None, max_files: int = 5, max_functions: int = 5) -> list[MetricEvidence]:
    """Turns the backend's metrics payload into METRIC_n evidence.

    Repository summary first, then files, then functions; directly requested
    entities come before hotspot rankings.
    """
    if not metrics:
        return []

    analysis = metrics.get("analysis") or {}
    common = {
        "analysisId": analysis.get("analysisId"),
        "analyzedAt": analysis.get("completedAt"),
        "commitSha": analysis.get("commitSha") or None,
    }

    evidence: list[MetricEvidence] = []

    def next_id() -> str:
        return f"METRIC_{len(evidence) + 1}"

    repository = metrics.get("repository")
    if repository:
        evidence.append(MetricEvidence(
            id=next_id(), scope="repository", title="Repository summary",
            items=_metric_items(repository, REPOSITORY_METRIC_ITEMS), **common,
        ))

    files = _dedupe(
        (metrics.get("files") or []) + (metrics.get("hotspotFiles") or []),
        key=lambda f: normalize_path(f.get("path")),
    )[:max_files]
    for f in files:
        path = normalize_path(f.get("path"))
        evidence.append(MetricEvidence(
            id=next_id(), scope="file", title=os.path.basename(path) or path,
            fileId=str(f["fileId"]) if f.get("fileId") is not None else None,
            fileName=os.path.basename(path), filePath=path,
            items=_metric_items(f, FILE_METRIC_ITEMS), **common,
        ))

    functions = _dedupe(
        (metrics.get("functions") or []) + (metrics.get("hotspotFunctions") or []),
        key=lambda fn: (normalize_path(fn.get("filePath")), fn.get("name"), fn.get("startLine")),
    )[:max_functions]
    for fn in functions:
        path = normalize_path(fn.get("filePath"))
        symbol = f"{fn['className']}.{fn.get('name')}" if fn.get("className") else fn.get("name")
        evidence.append(MetricEvidence(
            id=next_id(), scope="function", title=f"{symbol}()",
            fileId=str(fn["fileId"]) if fn.get("fileId") is not None else None,
            fileName=os.path.basename(path), filePath=path, symbol=symbol,
            startLine=_line(fn.get("startLine")), endLine=_line(fn.get("endLine")),
            items=_metric_items(fn, FUNCTION_METRIC_ITEMS), **common,
        ))

    return evidence


def _format_value(item: MetricItem) -> str:
    if item.value is None:
        return "unavailable (not measured by the current analyzers)"
    value = f"{item.value:,}" if isinstance(item.value, int) else f"{item.value:g}"
    if item.unit:
        value += f" {item.unit}"
    if item.category:
        value += f" (category: {item.category})"
    return value


def metric_evidence_to_text(evidence: list[MetricEvidence], thresholds: dict | None = None) -> str:
    if not evidence:
        return ""

    first = evidence[0]
    source = "Measured by static analysis (Lizard) and the knowledge graph"
    if first.analysisId:
        source += f", analysis #{first.analysisId}"
    if first.analyzedAt:
        source += f", completed {first.analyzedAt}"
    if first.commitSha:
        source += f", commit {first.commitSha[:12]}"
    header = [
        source + ".",
        "Complexity categories are indicators derived from configured thresholds, not verdicts.",
    ]

    if thresholds:
        bands = ", ".join(
            f"{b['category']} " + (f"<= {b['max']}" if b.get("max") is not None else "above")
            for b in thresholds.get("complexityBands", [])
        )
        if bands:
            header.append(f"Complexity bands: {bands}.")
        if thresholds.get("longFunctionNloc"):
            header.append(f"A long function has more than {thresholds['longFunctionNloc']} NLOC.")
        if thresholds.get("manyParameters"):
            header.append(f"Many parameters means more than {thresholds['manyParameters']}.")

    blocks = ["\n".join(header)]
    for item in evidence:
        location = ""
        if item.scope == "function" and item.filePath:
            span = f":{item.startLine}-{item.endLine}" if item.startLine else ""
            location = f" in {item.filePath}{span}"
        elif item.scope == "file":
            location = f" ({item.filePath})"
        lines = [f"[{item.id}] {item.scope.capitalize()}: {item.title}{location}"]
        lines += [f"- {m.label}: {_format_value(m)}" for m in item.items]
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)
