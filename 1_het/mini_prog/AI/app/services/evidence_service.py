import os
import re

from app.models.models import CodeEvidence, GraphEdge, GraphEvidence, GraphNode, Highlight

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
