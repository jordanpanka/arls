import json

from langchain_core.tools import StructuredTool

from app.agents.config import AgentConfig
from app.tools.base import ToolContext, ToolSpec, execute_tool
from app.tools.change_tools import CHANGE_TOOLS
from app.tools.code_tools import CODE_TOOLS
from app.tools.graph_tools import GRAPH_TOOLS
from app.tools.history_tools import HISTORY_TOOLS
from app.tools.metrics_tools import METRICS_TOOLS
from app.tools.pattern_tools import PATTERN_TOOLS
from app.tools.vector_tools import VECTOR_TOOLS

ALL_TOOLS: list[ToolSpec] = [*CODE_TOOLS, *VECTOR_TOOLS, *CHANGE_TOOLS, *GRAPH_TOOLS, *METRICS_TOOLS, *PATTERN_TOOLS, *HISTORY_TOOLS]


def build_registry(config: AgentConfig) -> dict[str, ToolSpec]:
    enabled = {}
    for spec in ALL_TOOLS:
        if spec.category == "graph" and not config.enable_graph_tools:
            continue
        if spec.category == "metrics" and not config.enable_metrics_tools:
            continue
        if spec.category == "history" and not config.enable_history_tools:
            continue
        if spec.category == "patterns" and not config.enable_pattern_analysis:
            continue
        enabled[spec.name] = spec
    return enabled


def _compact_schema(spec: ToolSpec) -> dict:
    schema = spec.args_schema.model_json_schema()
    properties = {}
    for name, prop in (schema.get("properties") or {}).items():
        entry = {}
        if "anyOf" in prop:
            types = [p.get("type") for p in prop["anyOf"] if p.get("type") and p.get("type") != "null"]
            entry["type"] = types[0] if len(types) == 1 else types
            enums = [p.get("enum") for p in prop["anyOf"] if p.get("enum")]
            if enums:
                entry["enum"] = enums[0]
        else:
            entry["type"] = prop.get("type")
        if "enum" in prop:
            entry["enum"] = prop["enum"]
        items = prop.get("items") or {}
        if items.get("enum"):
            entry["items"] = items["enum"]
        for bound in ("minimum", "maximum", "maxItems"):
            if bound in prop:
                entry[bound] = prop[bound]
        if "default" in prop and prop["default"] not in (None, [], ""):
            entry["default"] = prop["default"]
        if prop.get("description"):
            entry["description"] = prop["description"]
        properties[name] = entry
    return {"required": schema.get("required", []), "properties": properties}


def catalogue_text(registry: dict[str, ToolSpec]) -> str:
    blocks = []
    for spec in registry.values():
        blocks.append(
            f"- {spec.name}: {spec.description}\n  args: {json.dumps(_compact_schema(spec), ensure_ascii=False)}"
        )
    return "\n".join(blocks)


def as_langchain_tools(registry: dict[str, ToolSpec], ctx: ToolContext) -> list[StructuredTool]:
    tools = []
    for spec in registry.values():
        async def run(_spec=spec, **kwargs):
            result, _ = await execute_tool(_spec, ctx, kwargs)
            return result.model_dump()

        tools.append(StructuredTool.from_function(
            coroutine=run,
            name=spec.name,
            description=spec.description,
            args_schema=spec.args_schema,
        ))
    return tools
