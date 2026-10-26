from app.tests.agent_fakes import METRICS_ANALYSIS, FakeSource, GraphLoader, tool_context
from app.tools.code_graph import CodeGraphData


def lines(text: str) -> list[str]:
    return text.strip("\n").split("\n")


STRATEGY = {
    "src/shipping/calculator.py": lines('''
class ShippingCalculator:
    def __init__(self, rates):
        self.rates = rates

    def cost(self, order):
        if order.method == "standard":
            return order.weight * 1.0
        elif order.method == "express":
            return order.weight * 2.5
        elif order.method == "overnight":
            return order.weight * 4.0 + 10
        elif order.method == "pickup":
            return 0
        raise ValueError(order.method)
'''),
}

FEW_VARIANTS = {
    "src/shipping/labels.py": lines('''
def label(order):
    if order.kind == "gift":
        return "Gift"
    elif order.kind == "normal":
        return "Standard"
    return ""
'''),
}

FACTORY = {
    "src/Export/ExportService.cs": lines('''
public class ExportService
{
    public byte[] Run(Report report, string format)
    {
        IExporter exporter;
        switch (format)
        {
            case "csv": exporter = new CsvExporter(); break;
            case "pdf": exporter = new PdfExporter(); break;
            case "xml": exporter = new XmlExporter(); break;
            default: throw new NotSupportedException(format);
        }
        return exporter.Export(report);
    }
}
'''),
    "src/Export/Exporters.cs": lines('''
public interface IExporter { byte[] Export(Report report); }
public class CsvExporter : IExporter { public byte[] Export(Report report) { return null; } }
public class PdfExporter : IExporter { public byte[] Export(Report report) { return null; } }
public class XmlExporter : IExporter { public byte[] Export(Report report) { return null; } }
'''),
}

ADAPTER = {
    "src/payments/gateway.py": lines('''
from abc import ABC, abstractmethod


class PaymentGateway(ABC):
    @abstractmethod
    def charge(self, amount):
        ...


class CardGateway(PaymentGateway):
    def charge(self, amount):
        return True


class BankGateway(PaymentGateway):
    def charge(self, amount):
        return True


class LegacyBillingAdapter(PaymentGateway):
    def __init__(self, client: LegacyBillingClient):
        self.client = client

    def charge(self, amount):
        return self.client.submit_invoice(amount * 100)
'''),
}

SERVICE_AND_REPOSITORY = {
    "src/Orders/OrderService.cs": lines('''
public interface IOrderService { void Place(Order o); void Cancel(int id); }
public class OrderService : IOrderService
{
    private readonly OrderRepository _repo;
    public OrderService(OrderRepository repo) { _repo = repo; }
    public void Place(Order o) { _repo.Save(o); }
    public void Cancel(int id) { var o = _repo.Find(id); _repo.Delete(o); }
}
'''),
    "src/Orders/OrderRepository.cs": lines('''
public class OrderRepository
{
    private readonly AppDbContext _db;
    public OrderRepository(AppDbContext db) { _db = db; }
    public Order Find(int id) { return _db.Orders.Find(id); }
    public void Save(Order o) { _db.SaveChanges(); }
    public void Delete(Order o) { _db.Orders.Remove(o); }
}
'''),
}

FACADE = {
    "src/orders/checkout.py": lines('''
def place_order(cart):
    reserve(cart)
    charge_card(cart)
    send_confirmation(cart)
    record(cart)
'''),
    "src/orders/reorder.py": lines('''
def reorder(order):
    reserve(order)
    charge_card(order)
    send_confirmation(order)
'''),
    "src/inventory/stock.py": lines("def reserve(cart):\n    return True"),
    "src/payments/cards.py": lines("def charge_card(cart):\n    return True"),
    "src/mail/mailer.py": lines("def send_confirmation(cart):\n    return True"),
    "src/audit/log.py": lines("def record(cart):\n    return True"),
}


def facade_graph() -> CodeGraphData:
    functions = [
        {"id": "p", "name": "place_order", "path": "src/orders/checkout.py", "startLine": 1, "endLine": 5},
        {"id": "r", "name": "reorder", "path": "src/orders/reorder.py", "startLine": 1, "endLine": 4},
        {"id": "s", "name": "reserve", "path": "src/inventory/stock.py", "startLine": 1, "endLine": 2},
        {"id": "c", "name": "charge_card", "path": "src/payments/cards.py", "startLine": 1, "endLine": 2},
        {"id": "m", "name": "send_confirmation", "path": "src/mail/mailer.py", "startLine": 1, "endLine": 2},
        {"id": "a", "name": "record", "path": "src/audit/log.py", "startLine": 1, "endLine": 2},
    ]
    paths = {f["id"]: f["path"] for f in functions}
    names = {f["id"]: f["name"] for f in functions}
    calls = [
        {"callerId": caller, "calleeId": callee, "calleeName": names[callee], "calleePath": paths[callee]}
        for caller, callees in (("p", "scma"), ("r", "scm")) for callee in callees
    ]
    return CodeGraphData(functions=functions, calls=calls)


NO_PATTERN = {
    "src/users/names.py": lines('''
def full_name(user):
    return f"{user.first} {user.last}"
'''),
}

EXISTING_STRATEGY = {
    "src/cart/cart.ts": lines('''
import { DiscountRule } from "./discounts";

export class Cart {
    constructor(private readonly rule: DiscountRule) {}

    total(amount: number): number {
        return this.rule.apply(amount);
    }
}
'''),
    "src/cart/discounts.ts": lines('''
export interface DiscountRule { apply(total: number): number; }
export class SeasonalDiscount implements DiscountRule { apply(total: number): number { return total * 0.9; } }
export class LoyaltyDiscount implements DiscountRule { apply(total: number): number { return total - 5; } }
'''),
}

OBSERVER = {
    "src/Orders/Order.cs": lines('''
public class Order
{
    public string Status { get; private set; }
    public event EventHandler StatusChanged;

    public void Ship()
    {
        Status = "shipped";
        StatusChanged?.Invoke(this, EventArgs.Empty);
    }
}
'''),
    "src/stock/warehouse.py": lines('''
class Warehouse:
    def __init__(self):
        self._listeners = []

    def subscribe(self, listener):
        self._listeners.append(listener)

    def restock(self, item):
        for listener in self._listeners:
            listener.item_restocked(item)
'''),
    "src/stock/batch.py": lines('''
class BatchJob:
    def __init__(self, items: list[Item]):
        self.items = items

    def run(self):
        for item in self.items:
            item.process()
'''),
}

DECORATOR = {
    "src/pay/LoggingPaymentService.java": lines('''
public class LoggingPaymentService implements PaymentService {
    private final PaymentService inner;

    public LoggingPaymentService(PaymentService inner) { this.inner = inner; }

    public void pay(Order o) {
        System.out.println(o);
        inner.pay(o);
    }
}
'''),
    "src/pay/PaymentService.java": lines("public interface PaymentService { void pay(Order o); }"),
}


class PatternMetrics:
    def __init__(self, functions: dict | None = None, available: bool = True):
        self.functions = functions or {}
        self.available = available
        self.queries = []

    async def fetch(self, query):
        self.queries.append(query)
        if not self.available:
            return None
        requested = {(s.path, s.name) for s in query.symbols}
        functions = [f for (path, name), f in self.functions.items() if (path, name) in requested]
        return {"available": True, "analysis": METRICS_ANALYSIS, "repository": None, "files": [], "functions": functions,
                "hotspotFiles": [], "hotspotFunctions": []}


def complexity(path: str, name: str, start: int, end: int, value: int, category: str) -> dict:
    return {(path, name): {"filePath": path, "name": name, "startLine": start, "endLine": end, "nloc": end - start,
                           "cyclomaticComplexity": value, "complexityCategory": category, "parameterCount": 1}}


def pattern_context(sources: dict, graph: CodeGraphData | None = None, metrics=None, graph_fails: bool = False, config=None):
    loader = GraphLoader(data=graph or CodeGraphData(), fail=graph_fails)
    return tool_context(config=config, source=FakeSource(sources), graph=loader, metrics=metrics or PatternMetrics())
