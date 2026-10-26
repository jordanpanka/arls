from unittest.mock import MagicMock, patch

import pytest

from app.agents.planner import fallback_calls
from app.agents.requirements import analyze_question
from app.evidence.sufficiency import RequirementStatus
from app.patterns.structure import parse_source, type_relations
from app.services.neo4j_service import Neo4jService
from app.tests.agent_fakes import GraphLoader, tool_context
from app.tools.base import RESULT_CACHE, execute_tool
from app.tools.code_graph import GRAPH_CACHE, CodeGraph, CodeGraphData
from app.tools.graph_tools import GRAPH_TOOLS

TOOLS = {spec.name: spec for spec in GRAPH_TOOLS}

PYTHON_SOURCE = '''
from abc import ABC, abstractmethod


class Notifier(ABC):
    @abstractmethod
    def send(self, message: str) -> None: ...


class EmailNotifier(Notifier):
    def send(self, message: str) -> None:
        pass


class OrderService:
    def __init__(self, notifier: Notifier):
        self.notifier = notifier
        self.orders: list[Order] = []

    def place(self, order: Order) -> Receipt:
        receipt = Receipt(order)
        self.notifier.send("ok")
        return receipt


def build() -> OrderService:
    return OrderService(EmailNotifier())
'''

CSHARP_SOURCE = '''
public interface IPaymentGateway { Receipt Charge(Order order); }

public class StripeGateway : IPaymentGateway
{
    public event EventHandler Charged;

    public Receipt Charge(Order order)
    {
        Charged?.Invoke(this, EventArgs.Empty);
        return new Receipt();
    }
}
'''


def by_name(items, name, owner=None):
    return next(i for i in items if i["name"] == name and (owner is None or i.get("class") == owner))


def test_python_type_relations_are_extracted():
    relations = type_relations(parse_source("shop/service.py", PYTHON_SOURCE))
    types, functions = relations["types"], relations["functions"]

    assert by_name(types, "Notifier")["kind"] == "abstract"
    assert by_name(types, "EmailNotifier")["bases"] == ["Notifier"]
    fields = {f["name"]: f for f in by_name(types, "OrderService")["fields"]}
    assert fields["notifier"]["type"] == "Notifier" and fields["notifier"]["injected"]
    assert fields["orders"]["type"] == "Order" and fields["orders"]["collection"]

    constructor = by_name(functions, "__init__", "OrderService")
    assert constructor["constructor"] and constructor["params"] == [{"name": "notifier", "type": "Notifier"}]
    place = by_name(functions, "place", "OrderService")
    assert place["params"] == [{"name": "order", "type": "Order"}]
    assert place["returns"] == "Receipt"
    assert [c["type"] for c in place["creations"]] == ["Receipt"]
    build = by_name(functions, "build")
    assert build["class"] is None and build["returns"] == "OrderService"
    assert {c["type"] for c in build["creations"]} == {"OrderService", "EmailNotifier"}
    assert by_name(functions, "send", "Notifier")["params"] == []


def test_csharp_interfaces_and_events_are_extracted():
    relations = type_relations(parse_source("Pay/Stripe.cs", CSHARP_SOURCE))
    types, functions = relations["types"], relations["functions"]

    assert by_name(types, "IPaymentGateway")["kind"] == "interface"
    stripe = by_name(types, "StripeGateway")
    assert stripe["bases"] == ["IPaymentGateway"] and stripe["events"] == ["Charged"]
    charge = by_name(functions, "Charge", "StripeGateway")
    assert charge["raises"] == ["Charged"]
    assert charge["returns"] == "Receipt" and charge["params"] == [{"name": "order", "type": "Order"}]


def test_unparsable_files_yield_no_relations():
    assert type_relations(parse_source("notes.txt", "hello")) == {"types": [], "functions": []}


@patch("app.services.neo4j_service.GraphDatabase.driver")
def test_save_type_relations_writes_types_fields_functions_and_edges(mock_driver):
    session = MagicMock()
    mock_driver.return_value.session.return_value.__enter__.return_value = session
    relations = type_relations(parse_source("shop/service.py", PYTHON_SOURCE))

    Neo4jService().save_type_relations(1, 2, 3, "shop/service.py", relations)

    params = {call.args[0].split("\n")[1].strip(): call.args[1] for call in session.run.call_args_list}
    assert len(session.run.call_args_list) == 4
    fields = next(p["fields"] for p in params.values() if "fields" in p)
    assert {(f["owner"], f["name"], f["type"]) for f in fields} == {("OrderService", "notifier", "Notifier"), ("OrderService", "orders", "Order")}
    edges = next(p["edges"] for p in params.values() if "edges" in p)
    assert ("build", "INSTANTIATES", "OrderService") in {(e["function"], e["rel"], e["type"]) for e in edges}
    assert ("place", "RETURNS", "Receipt") in {(e["function"], e["rel"], e["type"]) for e in edges}
    assert all(p["project_id"] == 3 and p["file_path"] == "shop/service.py" for p in params.values())


def type_graph_data(with_types=True) -> CodeGraphData:
    return CodeGraphData(
        classes=[
            {"id": "c1", "name": "Notifier", "path": "shop/notify.py", "startLine": 1, "endLine": 3, "typeKind": "abstract"},
            {"id": "c2", "name": "EmailNotifier", "path": "shop/notify.py", "startLine": 5, "endLine": 8, "typeKind": "class"},
            {"id": "c3", "name": "OrderService", "path": "shop/service.py", "startLine": 1, "endLine": 20, "typeKind": "class"},
            {"id": "c4", "name": "IPaymentGateway", "path": "pay/Gateway.cs", "startLine": 1, "endLine": 3, "typeKind": "interface"},
            {"id": "c5", "name": "StripeGateway", "path": "pay/Gateway.cs", "startLine": 5, "endLine": 12, "typeKind": "class",
             "events": ["Charged"]},
            {"id": "c6", "name": "Order", "path": "shop/models.py", "startLine": 1, "endLine": 5},
            {"id": "c7", "name": "Config", "path": "shop/config.py", "startLine": 1, "endLine": 5},
            {"id": "c8", "name": "Config", "path": "admin/config.py", "startLine": 1, "endLine": 5},
        ],
        functions=[
            {"id": "f1", "name": "send", "path": "shop/notify.py", "startLine": 2, "endLine": 2},
            {"id": "f2", "name": "send", "path": "shop/notify.py", "startLine": 6, "endLine": 7},
            {"id": "f3", "name": "place", "path": "shop/service.py", "startLine": 10, "endLine": 15},
            {"id": "f4", "name": "build", "path": "shop/main.py", "startLine": 1, "endLine": 5},
            {"id": "f5", "name": "Charge", "path": "pay/Gateway.cs", "startLine": 2, "endLine": 2},
            {"id": "f6", "name": "Charge", "path": "pay/Gateway.cs", "startLine": 8, "endLine": 11, "raises": ["Charged"]},
            {"id": "f7", "name": "checkout", "path": "api/checkout.py", "startLine": 1, "endLine": 9},
        ],
        calls=[
            {"callerId": "f7", "calleeId": "f3", "calleeName": "place", "calleePath": "shop/service.py"},
            {"callerId": "f3", "calleeId": "x1", "calleeName": "self.notifier.send", "calleePath": None},
        ],
        type_relations=[
            {"sourceId": "c2", "type": "INHERITS", "target": "Notifier"},
            {"sourceId": "c5", "type": "INHERITS", "target": "IPaymentGateway"},
            {"sourceId": "c3", "type": "HAS_FIELD", "target": "Notifier", "name": "notifier", "line": 3, "injected": True},
            {"sourceId": "f3", "type": "TAKES", "target": "Order", "name": "order", "line": 10},
            {"sourceId": "f3", "type": "RETURNS", "target": "Receipt", "line": 10},
            {"sourceId": "f4", "type": "INSTANTIATES", "target": "OrderService", "line": 2},
            {"sourceId": "f4", "type": "INSTANTIATES", "target": "EmailNotifier", "line": 2},
            {"sourceId": "f4", "type": "TAKES", "target": "Config", "name": "config", "line": 1},
        ] if with_types else [],
    )


async def run(name, args, data=None):
    ctx = tool_context(graph=GraphLoader(data or type_graph_data()))
    result, _ = await execute_tool(TOOLS[name], ctx, args)
    return result


def relations(result):
    return {(e.relation.source_label, e.relation.type, e.relation.target_label) for e in result.evidence if e.relation}


def test_code_graph_resolves_types_and_derives_implements_and_overrides():
    graph = CodeGraph(type_graph_data())

    assert [(e.source, e.type) for e in graph.type_usages("c4")] == [("c5", "IMPLEMENTS")]
    assert [(e.source, e.type) for e in graph.type_usages("c1")] == [("c2", "INHERITS"), ("c3", "HAS_FIELD")]
    assert [e.target for e in graph.overrides("f2")] == ["f1"]
    assert [e.target for e in graph.overrides("f6")] == ["f5"]
    assert [e.source for e in graph.overridden_by("f1")] == ["f2"]
    assert graph.unresolved_types["f3"] == ["Receipt"]
    assert graph.unresolved_types["f4"] == ["Config"]
    assert graph.file_graph()["shop/main.py"]["shop/service.py"]["types"] == 1


async def test_find_type_usages_lists_structural_users_and_method_callers():
    result = await run("find_type_usages", {"symbol": "OrderService"})
    assert relations(result) == {
        ("build", "INSTANTIATES", "OrderService"),
        ("checkout", "CALLS", "OrderService.place"),
    }
    assert "1 instantiations" in result.summary and "1 calls to its methods" in result.summary

    notifier = await run("find_type_usages", {"symbol": "Notifier"})
    assert relations(notifier) == {("EmailNotifier", "INHERITS", "Notifier"), ("OrderService", "HAS_FIELD", "Notifier")}
    field = next(e for e in notifier.evidence if e.relation and e.relation.type == "HAS_FIELD")
    assert field.metadata["member"] == "notifier" and field.metadata["injected"] is True


async def test_find_type_usages_rejects_functions_and_flags_missing_type_data():
    function = await run("find_type_usages", {"symbol": "build"})
    assert function.error.kind == "not_found" and "get_callers" in function.error.message

    GRAPH_CACHE.entries.clear()
    RESULT_CACHE.entries.clear()
    legacy = await run("find_type_usages", {"symbol": "OrderService"}, type_graph_data(with_types=False))
    assert "not indexed" in legacy.summary
    assert relations(legacy) == {("checkout", "CALLS", "OrderService.place")}


async def test_related_symbols_show_hierarchy_fields_events_and_overrides():
    stripe = await run("get_related_symbols", {"symbol": "StripeGateway"})
    assert ("StripeGateway", "IMPLEMENTS", "IPaymentGateway") in relations(stripe)
    assert "events: Charged" in stripe.summary

    notifier = await run("get_related_symbols", {"symbol": "Notifier"})
    assert "(abstract)" in notifier.summary and "extended/implemented by: EmailNotifier" in notifier.summary

    service = await run("get_related_symbols", {"symbol": "OrderService"})
    assert "fields: notifier: Notifier" in service.summary

    send = await run("get_related_symbols", {"symbol": "EmailNotifier.send"})
    assert ("EmailNotifier.send", "OVERRIDES", "Notifier.send") in relations(send)
    assert "overrides: Notifier.send" in send.summary


async def test_trace_dependencies_counts_type_usage_between_files():
    result = await run("trace_dependencies", {"target": "shop/main.py", "direction": "outgoing"})
    edge = next(e for e in result.evidence if e.relation and e.relation.type == "DEPENDS_ON" and e.relation.target == "shop/service.py::file")
    assert edge.metadata == {"viaCalls": 0, "viaTypes": 1}


@pytest.mark.parametrize("question,expected", [
    ("Ki használja a FileService osztályt?", True),
    ("Who calls process_payment?", False),
])
def test_planner_asks_for_type_usages_of_classes(question, expected):
    analysis = analyze_question(question)
    statuses = [RequirementStatus(kind=r.kind, target=r.target, description=r.description, status="missing")
                for r in analysis.requirements if r.kind in ("dependency_relations", "impact_relations")]
    calls = fallback_calls(analysis, statuses, [], [], question, 120)
    assert any(c["tool"] == "find_type_usages" for c in calls) is expected
