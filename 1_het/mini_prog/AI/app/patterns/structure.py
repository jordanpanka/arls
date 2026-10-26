import os
import re
from dataclasses import dataclass, field

LANGUAGES = {
    ".py": "python",
    ".cs": "c_sharp",
    ".java": "java",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
}

COLLECTIONS = {
    "list", "ilist", "icollection", "ienumerable", "ireadonlylist", "ireadonlycollection", "collection",
    "arraylist", "linkedlist", "set", "hashset", "iset", "frozenset", "sequence", "iterable", "mutablesequence",
    "array", "readonlyarray", "tuple", "queue", "deque", "concurrentbag", "observablecollection", "copyonwritearraylist",
}
WRAPPERS = {"optional", "nullable", "readonly", "final"}
NOT_PRODUCTS = {
    "list", "dict", "set", "tuple", "object", "str", "int", "float", "bool", "bytes", "frozenset", "type", "super",
    "List", "Dictionary", "HashSet", "ArrayList", "HashMap", "LinkedList", "Map", "Set", "Array", "Object",
    "StringBuilder", "Date", "DateTime", "TimeSpan", "Guid", "Promise", "Error", "Exception", "Uri", "Random",
    "Path", "Decimal", "Counter", "OrderedDict", "Lock", "Thread", "Task", "CancellationTokenSource",
    "JsonSerializerOptions", "HttpClient", "Regex", "Stopwatch", "Event", "EventArgs", "TypeError", "ValueError",
}
REGISTRATION_METHODS = {"append", "add", "insert", "push", "Add", "Insert", "Push", "Enqueue", "addLast", "offer", "register", "Register"}
EVENT_RAISERS = {"emit", "dispatchEvent", "Invoke", "fire", "notify_all"}


@dataclass
class TypeRef:
    name: str
    element: str | None = None

    @property
    def is_collection(self) -> bool:
        return self.element is not None or self.name.lower() in COLLECTIONS


@dataclass
class Member:
    name: str
    type: TypeRef | None
    line: int
    from_constructor: bool = False
    promoted: bool = False


@dataclass
class Call:
    receiver: str
    method: str
    line: int
    args: list[str] = field(default_factory=list)
    receiver_is_field: bool = False
    receiver_is_self: bool = False


@dataclass
class Loop:
    collection: str
    variable: str
    line: int
    calls: list[Call] = field(default_factory=list)
    collection_is_field: bool = False


@dataclass
class Branch:
    label: str
    start_line: int
    end_line: int
    creations: list[str] = field(default_factory=list)


@dataclass
class Dispatch:
    kind: str
    discriminator: str
    start_line: int
    end_line: int
    branches: list[Branch] = field(default_factory=list)
    has_default: bool = False

    @property
    def created_types(self) -> list[str]:
        types: list[str] = []
        for branch in self.branches:
            for name in branch.creations:
                if name not in types:
                    types.append(name)
        return types


@dataclass
class Method:
    name: str
    start_line: int
    end_line: int
    params: list[Member] = field(default_factory=list)
    return_type: TypeRef | None = None
    abstract: bool = False
    virtual: bool = False
    overrides: bool = False
    is_constructor: bool = False
    calls_super: bool = False
    creations: list[tuple[str, int]] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    loops: list[Loop] = field(default_factory=list)
    dispatches: list[Dispatch] = field(default_factory=list)
    field_assignments: dict[str, str] = field(default_factory=dict)
    field_hints: dict[str, TypeRef] = field(default_factory=dict)

    @property
    def length(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass
class TypeDecl:
    name: str
    kind: str
    path: str
    start_line: int
    end_line: int
    language: str
    bases: list[str] = field(default_factory=list)
    fields: list[Member] = field(default_factory=list)
    methods: list[Method] = field(default_factory=list)
    events: list[str] = field(default_factory=list)

    @property
    def is_abstraction(self) -> bool:
        return self.kind in ("interface", "abstract")

    def field_types(self) -> dict[str, TypeRef]:
        return {f.name: f.type for f in self.fields if f.type is not None}

    def method(self, name: str) -> Method | None:
        return next((m for m in self.methods if m.name == name), None)


@dataclass
class FileStructure:
    path: str
    language: str
    types: list[TypeDecl] = field(default_factory=list)
    functions: list[Method] = field(default_factory=list)

    def all_methods(self) -> list[tuple[TypeDecl | None, Method]]:
        pairs: list[tuple[TypeDecl | None, Method]] = [(t, m) for t in self.types for m in t.methods]
        return pairs + [(None, f) for f in self.functions]


def language_for(path: str) -> str | None:
    return LANGUAGES.get(os.path.splitext(path or "")[1].lower())


def short_type(text: str) -> str:
    cleaned = re.sub(r"\s+", "", text or "").strip("?!").removesuffix("[]")
    cleaned = re.split(r"[<\[(]", cleaned, maxsplit=1)[0]
    return re.split(r"[.:]", cleaned)[-1] if cleaned else ""


def parse_type_text(text: str | None) -> TypeRef | None:
    raw = re.sub(r"\s+", "", (text or "").lstrip(":")).strip("?")
    if not raw or raw in ("None", "void", "var", "any", "unknown", "object"):
        return None
    if "|" in raw:
        parts = [p for p in raw.split("|") if p not in ("None", "null", "undefined")]
        return parse_type_text(parts[0]) if parts else None
    if raw.endswith("[]"):
        return TypeRef(name="Array", element=short_type(raw[:-2]))
    match = re.match(r"^([\w.]+)\s*[<\[](.*)[>\]]$", raw)
    if match:
        outer = short_type(match.group(1))
        inner = match.group(2)
        first = _split_args(inner)[0] if inner else ""
        if outer.lower() in WRAPPERS:
            return parse_type_text(first)
        if outer.lower() in COLLECTIONS:
            return TypeRef(name=outer, element=short_type(first) or None)
        return TypeRef(name=outer)
    name = short_type(raw)
    return TypeRef(name=name) if name else None


def _split_args(text: str) -> list[str]:
    parts, depth, current = [], 0, ""
    for char in text:
        if char in "<[(":
            depth += 1
        elif char in ">])":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return [p.strip() for p in parts]


def _text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace") if node is not None else ""


def _line(node) -> int:
    return node.start_point[0] + 1


def _end(node) -> int:
    return node.end_point[0] + 1


def _named(node, *types: str) -> list:
    return [c for c in node.named_children if c.type in types] if node is not None else []


def _walk(node, stop: set[str] = frozenset()):
    stack = list(reversed(node.named_children)) if node is not None else []
    while stack:
        current = stack.pop()
        yield current
        if current.type not in stop:
            stack.extend(reversed(current.named_children))


def _is_product_name(name: str) -> bool:
    return (
        bool(name) and name[0].isupper() and not name.isupper() and name not in NOT_PRODUCTS
        and not name.endswith(("Error", "Exception", "Warning", "Args"))
    )


NESTED_SCOPES = {
    "class_definition", "function_definition", "lambda", "class_declaration", "interface_declaration",
    "method_declaration", "constructor_declaration", "local_function_statement", "lambda_expression",
    "arrow_function", "function_expression", "function_declaration", "method_definition",
    "abstract_class_declaration", "class_body", "anonymous_class_body",
}


class _Extractor:
    def __init__(self, language: str, path: str, source: bytes):
        self.language = language
        self.path = path
        self.source = source
        self.ts = language in ("typescript", "tsx", "javascript")

    def text(self, node) -> str:
        return _text(node, self.source)

    def run(self, root) -> FileStructure:
        structure = FileStructure(path=self.path, language=self.language)
        for node in _walk(root, stop={"function_definition", "method_declaration", "method_definition", "function_declaration"}):
            if node.type in self.type_nodes():
                decl = self.type_decl(node)
                if decl is not None:
                    structure.types.append(decl)
            elif node.type in ("function_definition", "function_declaration") and not self._inside_type(node):
                method = self.method(node, None)
                if method is not None:
                    structure.functions.append(method)
        return structure

    def type_nodes(self) -> set[str]:
        return {
            "python": {"class_definition"},
            "c_sharp": {"class_declaration", "interface_declaration", "record_declaration", "struct_declaration"},
            "java": {"class_declaration", "interface_declaration", "record_declaration"},
        }.get(self.language, {"class_declaration", "abstract_class_declaration", "interface_declaration"})

    def _inside_type(self, node) -> bool:
        parent = node.parent
        while parent is not None:
            if parent.type in self.type_nodes():
                return True
            parent = parent.parent
        return False

    def type_decl(self, node) -> TypeDecl | None:
        name_node = node.child_by_field_name("name")
        name = self.text(name_node)
        if not name:
            return None
        decl = TypeDecl(name=short_type(name), kind="class", path=self.path, start_line=_line(node),
                        end_line=_end(node), language=self.language)
        getattr(self, f"_bases_{self._family()}")(node, decl)
        body = node.child_by_field_name("body") or next(iter(_named(node, "class_body", "declaration_list", "interface_body", "object_type", "block")), None)
        if body is not None:
            getattr(self, f"_members_{self._family()}")(body, decl)
        self._resolve_fields(decl)
        if decl.kind == "class" and any(m.abstract for m in decl.methods) and self.language != "javascript":
            decl.kind = "abstract"
        return decl

    def _family(self) -> str:
        return "ts" if self.ts else self.language

    def _bases_python(self, node, decl: TypeDecl):
        args = node.child_by_field_name("superclasses")
        for child in args.named_children if args is not None else []:
            if child.type == "keyword_argument":
                if self.text(child.child_by_field_name("value")).endswith("ABCMeta"):
                    decl.kind = "abstract"
                continue
            base = short_type(self.text(child.child_by_field_name("value") if child.type == "subscript" else child))
            if base in ("ABC", "ABCMeta"):
                decl.kind = "abstract"
            elif base == "Protocol":
                decl.kind = "interface"
            elif base and base not in ("object", "Generic"):
                decl.bases.append(base)

    def _bases_c_sharp(self, node, decl: TypeDecl):
        if node.type == "interface_declaration":
            decl.kind = "interface"
        modifiers = {self.text(m) for m in _named(node, "modifier")}
        if "abstract" in modifiers:
            decl.kind = "abstract"
        for base_list in _named(node, "base_list"):
            for child in base_list.named_children:
                if child.type == "argument_list":
                    continue
                base = short_type(self.text(child))
                if base:
                    decl.bases.append(base)

    def _bases_java(self, node, decl: TypeDecl):
        if node.type == "interface_declaration":
            decl.kind = "interface"
        modifiers = next(iter(_named(node, "modifiers")), None)
        if modifiers is not None and "abstract" in self.text(modifiers).split():
            decl.kind = "abstract"
        superclass = node.child_by_field_name("superclass")
        if superclass is not None:
            decl.bases += [short_type(self.text(c)) for c in superclass.named_children]
        for clause in [node.child_by_field_name("interfaces"), *_named(node, "extends_interfaces")]:
            for type_list in _named(clause, "type_list"):
                decl.bases += [short_type(self.text(c)) for c in type_list.named_children]

    def _bases_ts(self, node, decl: TypeDecl):
        if node.type == "interface_declaration":
            decl.kind = "interface"
            for clause in _named(node, "extends_type_clause", "extends_clause"):
                decl.bases += [short_type(self.text(c)) for c in clause.named_children]
            return
        if node.type == "abstract_class_declaration":
            decl.kind = "abstract"
        for heritage in _named(node, "class_heritage"):
            clauses = _named(heritage, "extends_clause", "implements_clause")
            if not clauses:
                decl.bases += [short_type(self.text(c)) for c in heritage.named_children]
            for clause in clauses:
                decl.bases += [short_type(self.text(c)) for c in clause.named_children if c.type != "type_arguments"]
        decl.bases = [b for b in decl.bases if b]

    def _members_python(self, body, decl: TypeDecl):
        for child in body.named_children:
            target, decorators = child, []
            if child.type == "decorated_definition":
                decorators = [self.text(d).lstrip("@").split("(")[0] for d in _named(child, "decorator")]
                target = child.child_by_field_name("definition")
            if target is not None and target.type == "function_definition":
                method = self.method(target, decl)
                if method is None:
                    continue
                if any(d.endswith("abstractmethod") for d in decorators) or (decl.kind == "interface" and self._stub_body(target)):
                    method.abstract = True
                decl.methods.append(method)
            elif child.type == "expression_statement":
                for assignment in _named(child, "assignment"):
                    type_node = assignment.child_by_field_name("type")
                    left = assignment.child_by_field_name("left")
                    if type_node is not None and left is not None and left.type == "identifier":
                        decl.fields.append(Member(self.text(left), parse_type_text(self.text(type_node)), _line(assignment)))

    def _stub_body(self, function) -> bool:
        body = function.child_by_field_name("body")
        statements = body.named_children if body is not None else []
        return all(
            s.type in ("pass_statement", "comment") or self.text(s).strip() in ("...", "pass")
            or (s.type == "raise_statement" and "NotImplementedError" in self.text(s))
            or (s.type == "expression_statement" and s.named_children and s.named_children[0].type == "string")
            for s in statements
        )

    def _members_c_sharp(self, body, decl: TypeDecl):
        for child in body.named_children:
            if child.type in ("method_declaration", "constructor_declaration"):
                method = self.method(child, decl)
                if method is not None:
                    decl.methods.append(method)
            elif child.type == "field_declaration":
                decl.fields += self._variable_members(child)
            elif child.type == "property_declaration":
                type_node = child.child_by_field_name("type")
                name = self.text(child.child_by_field_name("name"))
                if name:
                    decl.fields.append(Member(name, parse_type_text(self.text(type_node)), _line(child)))
            elif child.type in ("event_field_declaration", "event_declaration"):
                names = [m.name for m in self._variable_members(child)] or [self.text(child.child_by_field_name("name"))]
                decl.events += [n for n in names if n]

    def _variable_members(self, node) -> list[Member]:
        members = []
        for declaration in _named(node, "variable_declaration"):
            type_ref = parse_type_text(self.text(declaration.child_by_field_name("type")))
            for declarator in _named(declaration, "variable_declarator"):
                name = self.text(declarator.child_by_field_name("name") or next(iter(_named(declarator, "identifier")), None))
                if name:
                    members.append(Member(name, type_ref, _line(declarator)))
        return members

    def _members_java(self, body, decl: TypeDecl):
        for child in body.named_children:
            if child.type in ("method_declaration", "constructor_declaration"):
                method = self.method(child, decl)
                if method is not None:
                    decl.methods.append(method)
            elif child.type == "field_declaration":
                type_ref = parse_type_text(self.text(child.child_by_field_name("type")))
                for declarator in _named(child, "variable_declarator"):
                    name = self.text(declarator.child_by_field_name("name"))
                    if name:
                        decl.fields.append(Member(name, type_ref, _line(declarator)))

    def _members_ts(self, body, decl: TypeDecl):
        for child in body.named_children:
            if child.type in ("method_definition", "abstract_method_signature", "method_signature"):
                method = self.method(child, decl)
                if method is not None:
                    decl.methods.append(method)
            elif child.type in ("public_field_definition", "field_definition", "property_signature"):
                name = self.text(child.child_by_field_name("name") or child.child_by_field_name("property"))
                type_node = child.child_by_field_name("type") or next(iter(_named(child, "type_annotation")), None)
                if name:
                    decl.fields.append(Member(name, parse_type_text(self.text(type_node)), _line(child)))

    def method(self, node, decl: TypeDecl | None) -> Method | None:
        name = self.text(node.child_by_field_name("name"))
        if not name:
            return None
        method = Method(name=name, start_line=_line(node), end_line=_end(node))
        method.is_constructor = node.type == "constructor_declaration" or name in ("__init__", "constructor")
        params_node = node.child_by_field_name("parameters") or next(iter(_named(node, "parameter_list", "formal_parameters", "parameters")), None)
        method.params = self._params(params_node, method.is_constructor)
        method.return_type = self._return_type(node)
        modifiers = self._modifiers(node)
        body = node.child_by_field_name("body")
        if body is None and self.language in ("c_sharp", "java"):
            body = next(iter(_named(node, "block", "arrow_expression_clause", "constructor_body")), None)
        if self.ts and body is None:
            body = next(iter(_named(node, "statement_block")), None)
        method.abstract = "abstract" in modifiers or node.type in ("abstract_method_signature", "method_signature") or (
            body is None and decl is not None and decl.kind == "interface")
        method.virtual = bool({"virtual", "abstract"} & modifiers)
        method.overrides = "override" in modifiers
        if body is not None:
            self._body(body, method)
        if method.is_constructor and decl is not None:
            for param in method.params:
                if param.promoted and param.type is not None and param.name not in {f.name for f in decl.fields}:
                    decl.fields.append(Member(param.name, param.type, param.line, from_constructor=True))
        return method

    def _modifiers(self, node) -> set[str]:
        words: set[str] = set()
        for child in node.children:
            if child.type in ("modifier", "modifiers", "accessibility_modifier", "abstract", "override_modifier"):
                words |= set(self.text(child).split())
        return words

    def _return_type(self, node) -> TypeRef | None:
        if self.language == "python":
            return parse_type_text(self.text(node.child_by_field_name("return_type")))
        if self.language in ("c_sharp", "java"):
            type_node = node.child_by_field_name("type") or node.child_by_field_name("returns")
            return parse_type_text(self.text(type_node))
        type_node = node.child_by_field_name("return_type") or next(iter(_named(node, "type_annotation")), None)
        return parse_type_text(self.text(type_node))

    def _params(self, node, constructor: bool) -> list[Member]:
        params: list[Member] = []
        for child in node.named_children if node is not None else []:
            name, type_text, promoted = "", "", False
            if self.language == "python":
                if child.type in ("typed_parameter", "typed_default_parameter"):
                    name = self.text(next(iter(_named(child, "identifier")), None) or child.child_by_field_name("name"))
                    type_text = self.text(child.child_by_field_name("type"))
                elif child.type in ("identifier", "default_parameter"):
                    name = self.text(child if child.type == "identifier" else child.child_by_field_name("name"))
                if name in ("self", "cls"):
                    continue
            elif self.language in ("c_sharp", "java"):
                if child.type not in ("parameter", "formal_parameter"):
                    continue
                name = self.text(child.child_by_field_name("name"))
                type_text = self.text(child.child_by_field_name("type"))
            else:
                if child.type not in ("required_parameter", "optional_parameter", "identifier"):
                    continue
                pattern = child.child_by_field_name("pattern") or (child if child.type == "identifier" else next(iter(_named(child, "identifier")), None))
                name = self.text(pattern)
                type_text = self.text(child.child_by_field_name("type") or next(iter(_named(child, "type_annotation")), None))
                promoted = bool(_named(child, "accessibility_modifier")) or "readonly" in self.text(child).split()
            if name:
                params.append(Member(name, parse_type_text(type_text), _line(child),
                                     from_constructor=constructor and promoted, promoted=constructor and promoted))
        return params

    def _body(self, body, method: Method):
        params = {p.name: p for p in method.params}
        for node in _walk(body, stop=NESTED_SCOPES):
            kind = node.type
            creation = self._creation(node)
            if creation:
                method.creations.append((creation, _line(node)))
            call = self._call(node)
            if call is not None:
                if call.method in ("super", "base") or call.receiver in ("super", "base", "super()"):
                    method.calls_super = True
                method.calls.append(call)
            if kind in ("for_statement", "for_each_statement", "enhanced_for_statement", "for_in_statement"):
                loop = self._loop(node)
                if loop is not None:
                    method.loops.append(loop)
            if self._is_dispatch_root(node):
                dispatch = self._dispatch(node)
                if dispatch is not None and len(dispatch.branches) >= 2:
                    method.dispatches.append(dispatch)
            if method.is_constructor:
                assigned = self._field_assignment(node)
                if assigned is not None:
                    target, value = assigned
                    method.field_assignments[target] = value
                    if value in params and params[value].type is not None:
                        params[value].from_constructor = True
                hint = self._field_hint(node)
                if hint is not None:
                    method.field_hints.setdefault(hint[0], hint[1])

    def _field_hint(self, node) -> tuple[str, TypeRef] | None:
        if node.type != "assignment" or self.language != "python":
            return None
        left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
        target, is_field, _ = self._receiver(left)
        if not is_field:
            return None
        annotated = node.child_by_field_name("type")
        if annotated is not None:
            hinted = parse_type_text(self.text(annotated))
            return (target, hinted) if hinted is not None else None
        if right is not None and right.type in ("list", "list_comprehension"):
            return target, TypeRef(name="list")
        if right is not None and right.type in ("set", "set_comprehension"):
            return target, TypeRef(name="set")
        creation = self._creation(right) if right is not None else None
        return (target, TypeRef(name=creation)) if creation else None

    def _creation(self, node) -> str | None:
        if node.type == "object_creation_expression":
            type_node = node.child_by_field_name("type")
            if type_node is None:
                type_node = next((c for c in node.named_children if c.type in ("type_identifier", "identifier", "generic_type", "generic_name", "qualified_name", "scoped_type_identifier")), None)
            name = short_type(self.text(type_node))
        elif node.type == "new_expression":
            name = short_type(self.text(node.child_by_field_name("constructor")))
        elif node.type == "call" and self.language == "python":
            function = node.child_by_field_name("function")
            name = self.text(function) if function is not None and function.type == "identifier" else ""
        else:
            return None
        return name if _is_product_name(name) else None

    def _call(self, node) -> Call | None:
        receiver_node, method_name = None, ""
        if node.type == "call" and self.language == "python":
            function = node.child_by_field_name("function")
            if function is not None and function.type == "attribute":
                receiver_node = function.child_by_field_name("object")
                method_name = self.text(function.child_by_field_name("attribute"))
            elif function is not None and function.type == "identifier":
                method_name = self.text(function)
        elif node.type == "invocation_expression":
            function = node.child_by_field_name("function")
            if function is not None and function.type == "member_access_expression":
                receiver_node = function.child_by_field_name("expression")
                method_name = self.text(function.child_by_field_name("name"))
            elif function is not None and function.type == "conditional_access_expression":
                receiver_node = function.child_by_field_name("condition")
                binding = next(iter(_named(function, "member_binding_expression")), None)
                method_name = self.text(binding.child_by_field_name("name")) if binding is not None else ""
            elif function is not None:
                method_name = self.text(function)
        elif node.type == "method_invocation":
            receiver_node = node.child_by_field_name("object")
            method_name = self.text(node.child_by_field_name("name"))
        elif node.type == "call_expression" and self.ts:
            function = node.child_by_field_name("function")
            if function is not None and function.type == "member_expression":
                receiver_node = function.child_by_field_name("object")
                method_name = self.text(function.child_by_field_name("property"))
            elif function is not None:
                method_name = self.text(function)
        else:
            return None
        if not method_name:
            return None
        receiver, is_field, is_self = self._receiver(receiver_node)
        args_node = node.child_by_field_name("arguments") or next(iter(_named(node, "argument_list", "arguments")), None)
        args = []
        for arg in args_node.named_children if args_node is not None else []:
            inner = arg.named_children[0] if arg.type == "argument" and arg.named_children else arg
            if inner.type == "identifier":
                args.append(self.text(inner))
        return Call(receiver=receiver, method=method_name, line=_line(node), args=args, receiver_is_field=is_field, receiver_is_self=is_self)

    def _receiver(self, node) -> tuple[str, bool, bool]:
        if node is None:
            return "", False, False
        text = re.sub(r"\s+", "", self.text(node))
        if text in ("self", "this"):
            return text, False, True
        for prefix in ("self.", "this."):
            if text.startswith(prefix) and re.fullmatch(r"[A-Za-z_$][\w$]*", text[len(prefix):]):
                return text[len(prefix):], True, False
        return text, False, False

    def _loop(self, node) -> Loop | None:
        if node.type == "for_statement" and self.language != "python":
            return None
        if self.language == "java":
            variable, collection = node.child_by_field_name("name"), node.child_by_field_name("value")
        else:
            variable, collection = node.child_by_field_name("left"), node.child_by_field_name("right")
        if variable is None or collection is None:
            return None
        name = self.text(variable)
        target, is_field, _ = self._receiver(collection)
        loop = Loop(collection=target, variable=name, line=_line(node), collection_is_field=is_field)
        body = node.child_by_field_name("body")
        for inner in _walk(body, stop=NESTED_SCOPES):
            call = self._call(inner)
            if call is not None and call.receiver == name:
                loop.calls.append(call)
        return loop

    def _field_assignment(self, node) -> tuple[str, str] | None:
        if node.type not in ("assignment", "assignment_expression"):
            return None
        left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
        if left is None or right is None or right.type != "identifier":
            return None
        target, is_field, _ = self._receiver(left)
        if not is_field and left.type != "identifier":
            return None
        return target, self.text(right)

    def _is_dispatch_root(self, node) -> bool:
        if node.type in ("switch_statement", "switch_expression", "match_statement"):
            return True
        if node.type != "if_statement":
            return False
        parent = node.parent
        if parent is not None and parent.type == "else_clause":
            return False
        if parent is not None and parent.type == "if_statement" and parent.child_by_field_name("alternative") == node:
            return False
        return True

    def _dispatch(self, node) -> Dispatch | None:
        if node.type == "if_statement":
            return self._if_chain(node)
        return self._switch(node)

    def _if_chain(self, node) -> Dispatch | None:
        arms: list[tuple[str, str, str, object]] = []
        has_default = False
        current = node
        while current is not None:
            condition = current.child_by_field_name("condition")
            consequence = current.child_by_field_name("consequence")
            kind, discriminator, label = self._condition(condition)
            arms.append((kind, discriminator, label, consequence))
            next_node = None
            if self.language == "python":
                for clause in _named(current, "elif_clause", "else_clause"):
                    if clause.type == "elif_clause":
                        c_kind, c_disc, c_label = self._condition(clause.child_by_field_name("condition"))
                        arms.append((c_kind, c_disc, c_label, clause.child_by_field_name("consequence")))
                    else:
                        has_default = True
                break
            alternative = current.child_by_field_name("alternative")
            if alternative is not None and alternative.type == "else_clause":
                inner = next(iter(_named(alternative, "if_statement")), None)
                if inner is None:
                    has_default = True
                alternative = inner
            if alternative is not None and alternative.type == "if_statement":
                next_node = alternative
            elif alternative is not None:
                has_default = True
            current = next_node
        keyed = [a for a in arms if a[1]]
        if not keyed:
            return None
        discriminator = max({a[1] for a in keyed}, key=lambda d: sum(1 for a in keyed if a[1] == d))
        matching = [a for a in keyed if a[1] == discriminator]
        kind = "type" if all(a[0] == "type" for a in matching) else "value"
        dispatch = Dispatch(kind=kind, discriminator=discriminator, start_line=_line(node), end_line=_end(node), has_default=has_default)
        for _, _, label, body in matching:
            dispatch.branches.append(self._branch(label, body))
        return dispatch

    def _condition(self, node) -> tuple[str, str, str]:
        if node is None:
            return "", "", ""
        while node.type in ("parenthesized_expression", "condition") and node.named_children:
            node = node.named_children[0]
        text = lambda n: re.sub(r"\s+", "", self.text(n))
        if node.type == "comparison_operator" and len(node.named_children) == 2:
            operators = [self.text(c) for c in node.children if not c.is_named]
            if operators and operators[0] in ("==", "is", "in"):
                left, right = node.named_children
                return self._ordered("value", left, right)
        if node.type == "binary_expression":
            operator = self.text(node.child_by_field_name("operator"))
            left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
            if operator in ("==", "===") and left is not None and right is not None:
                return self._ordered("value", left, right)
            if operator == "instanceof" and left is not None:
                return "type", text(left), short_type(self.text(right))
        if node.type == "call" and self.language == "python":
            function = node.child_by_field_name("function")
            args = node.child_by_field_name("arguments")
            if self.text(function) == "isinstance" and args is not None and len(args.named_children) == 2:
                return "type", text(args.named_children[0]), short_type(self.text(args.named_children[1]))
        if node.type in ("is_pattern_expression", "is_expression"):
            subject = node.child_by_field_name("expression") or (node.named_children[0] if node.named_children else None)
            pattern = node.child_by_field_name("pattern") or node.child_by_field_name("type") or (node.named_children[-1] if node.named_children else None)
            type_node = pattern.child_by_field_name("type") if pattern is not None and pattern.child_by_field_name("type") is not None else pattern
            return "type", text(subject), short_type(self.text(type_node))
        if node.type == "instanceof_expression":
            return "type", text(node.child_by_field_name("left")), short_type(self.text(node.child_by_field_name("right")))
        if node.type == "method_invocation" and self.text(node.child_by_field_name("name")) == "equals":
            args = node.child_by_field_name("arguments")
            label = self.text(args.named_children[0]) if args is not None and args.named_children else ""
            return "value", text(node.child_by_field_name("object")), label
        return "", "", ""

    def _ordered(self, kind: str, left, right) -> tuple[str, str, str]:
        literals = {"string", "string_literal", "integer", "number", "decimal_integer_literal", "integer_literal", "real_literal"}
        left_text = re.sub(r"\s+", "", self.text(left))
        right_text = re.sub(r"\s+", "", self.text(right))
        if left.type in literals and right.type not in literals:
            return kind, right_text, left_text
        return kind, left_text, right_text

    def _switch(self, node) -> Dispatch | None:
        subject = node.child_by_field_name("value") or node.child_by_field_name("subject") or node.child_by_field_name("condition")
        if subject is None and node.named_children:
            subject = node.named_children[0]
        while subject is not None and subject.type == "parenthesized_expression" and subject.named_children:
            subject = subject.named_children[0]
        discriminator = re.sub(r"\s+", "", self.text(subject))
        dispatch = Dispatch(kind="value", discriminator=discriminator, start_line=_line(node), end_line=_end(node))
        sections = [n for n in _walk(node, stop=NESTED_SCOPES | {"switch_section", "case_clause", "switch_case", "switch_default",
                                                               "switch_block_statement_group", "switch_rule", "switch_expression_arm"})
                    if n.type in ("switch_section", "case_clause", "switch_case", "switch_default", "switch_block_statement_group",
                                  "switch_rule", "switch_expression_arm")]
        type_cases = 0
        for section in sections:
            label_text = self.text(section).split(":", 1)[0].split("=>", 1)[0].strip()
            if section.type == "switch_default" or label_text.startswith("default") or label_text in ("_", "case _") or re.match(r"^case\s+_\b", label_text):
                dispatch.has_default = True
                continue
            if any(c.type in ("declaration_pattern", "type_pattern", "recursive_pattern", "class_pattern") for c in _walk(section)):
                type_cases += 1
            dispatch.branches.append(self._branch(label_text.removeprefix("case").strip(), section))
        if dispatch.branches and type_cases == len(dispatch.branches):
            dispatch.kind = "type"
        return dispatch

    def _branch(self, label: str, body) -> Branch:
        branch = Branch(label=label[:80], start_line=_line(body) if body is not None else 0, end_line=_end(body) if body is not None else 0)
        for node in _walk(body, stop=NESTED_SCOPES) if body is not None else []:
            creation = self._creation(node)
            if creation and creation not in branch.creations:
                branch.creations.append(creation)
        return branch

    def _resolve_fields(self, decl: TypeDecl):
        names = {f.name for f in decl.fields}
        constructor_params = {p.name: p for m in decl.methods if m.is_constructor for p in m.params}
        for method in decl.methods:
            for target, hint in method.field_hints.items():
                if target not in names and not (target in method.field_assignments and method.field_assignments[target] in constructor_params):
                    decl.fields.append(Member(target, hint, method.start_line))
                    names.add(target)
            for target, value in method.field_assignments.items():
                if target not in names and value in constructor_params and constructor_params[value].type is not None:
                    decl.fields.append(Member(target, constructor_params[value].type, constructor_params[value].line, from_constructor=True))
                    names.add(target)
        if self.language == "python":
            for method in decl.methods:
                for call in method.calls:
                    if call.receiver_is_field and call.receiver not in names:
                        decl.fields.append(Member(call.receiver, None, call.line))
                        names.add(call.receiver)
                for loop in method.loops:
                    if loop.collection_is_field and loop.collection not in names:
                        decl.fields.append(Member(loop.collection, TypeRef(name="list"), loop.line))
                        names.add(loop.collection)
        for method in decl.methods:
            for call in method.calls:
                if not call.receiver_is_field and call.receiver in names:
                    call.receiver_is_field = True
            for loop in method.loops:
                if not loop.collection_is_field and loop.collection in names:
                    loop.collection_is_field = True


def parse_source(path: str, source: str | bytes) -> FileStructure | None:
    language = language_for(path)
    if language is None:
        return None
    from tree_sitter import Parser
    from tree_sitter_languages import get_language

    data = source.encode("utf-8") if isinstance(source, str) else source
    parser = Parser()
    parser.set_language(get_language(language))
    tree = parser.parse(data)
    return _Extractor(language, path, data).run(tree.root_node)


def referenced_type(ref: TypeRef | None) -> str | None:
    if ref is None:
        return None
    name = ref.element if ref.is_collection and ref.element else ref.name
    if not name or not name[0].isupper() or name in NOT_PRODUCTS or name.lower() in COLLECTIONS:
        return None
    return name


def _function_relations(method: Method, decl: TypeDecl | None) -> dict:
    events = set(decl.events) if decl is not None else set()
    params = []
    for param in method.params:
        target = referenced_type(param.type)
        if target:
            params.append({"name": param.name, "type": target})
    creations: dict[str, int] = {}
    for name, line in method.creations:
        creations.setdefault(name, line)
    return {
        "name": method.name,
        "class": decl.name if decl is not None else None,
        "start_line": method.start_line,
        "end_line": method.end_line,
        "constructor": method.is_constructor,
        "params": params,
        "returns": referenced_type(method.return_type),
        "creations": [{"type": name, "line": line} for name, line in creations.items()],
        "raises": sorted({c.receiver for c in method.calls if c.method in EVENT_RAISERS and c.receiver in events}),
    }


def type_relations(structure: FileStructure | None) -> dict:
    if structure is None:
        return {"types": [], "functions": []}
    types = []
    for decl in structure.types:
        fields = []
        for member in decl.fields:
            target = referenced_type(member.type)
            if target:
                fields.append({"name": member.name, "type": target, "line": member.line,
                               "injected": member.from_constructor, "collection": bool(member.type and member.type.is_collection)})
        types.append({
            "name": decl.name,
            "kind": decl.kind,
            "start_line": decl.start_line,
            "end_line": decl.end_line,
            "bases": list(dict.fromkeys(b for b in decl.bases if b)),
            "fields": fields,
            "events": decl.events,
        })
    functions = [_function_relations(method, decl) for decl, method in structure.all_methods()]
    return {"types": types, "functions": functions}
