from neo4j import GraphDatabase
from app.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
from app.services.evidence_service import short_symbol_name

class Neo4jService:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD)
        )
    def close(self):
        self.driver.close()
        
    def save_file(self, user_id:int, investigation_id:int,project_id: int, file_path: str, file_name: str):
        query = """
        MERGE (f:File {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id, path: $file_path})
        SET f.name = $file_name
        RETURN f
        """

        with self.driver.session() as session:
            session.run(query, {
                "user_id":user_id,
                "investigation_id":investigation_id,
                "project_id": project_id,
                "file_path": file_path,
                "file_name": file_name
            })

    def save_class(self,user_id:int, investigation_id:int, project_id: int, file_path: str, class_name: str, start_line: int, end_line: int):
        query = """
        MERGE (f:File {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id, path: $file_path})
        MERGE (c:Class {
            user_id: $user_id,
            investigation_id: $investigation_id,
            projectId: $project_id,
            name: $class_name,
            filePath: $file_path
        })
        SET c.startLine = $start_line,
            c.endLine = $end_line
        MERGE (f)-[:CONTAINS]->(c)
        """

        with self.driver.session() as session:
            session.run(query, {
                "user_id":user_id,
                "investigation_id":investigation_id,
                "project_id": project_id,
                "file_path": file_path,
                "class_name": class_name,
                "start_line": start_line,
                "end_line": end_line
            })
    
    SAVE_TYPES = """
    UNWIND $types AS t
    MERGE (f:File {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id, path: $file_path})
    MERGE (c:Class {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id, name: t.name, filePath: $file_path})
    SET c.startLine = coalesce(c.startLine, t.start_line),
        c.endLine = coalesce(c.endLine, t.end_line),
        c.typeKind = t.kind,
        c.bases = t.bases,
        c.events = t.events
    MERGE (f)-[:CONTAINS]->(c)
    WITH c, t
    UNWIND t.bases AS base
    MERGE (r:TypeRef {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id, name: base})
    MERGE (c)-[:INHERITS]->(r)
    """

    SAVE_FIELDS = """
    UNWIND $fields AS fld
    MATCH (c:Class {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id, name: fld.owner, filePath: $file_path})
    MERGE (r:TypeRef {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id, name: fld.type})
    MERGE (c)-[e:HAS_FIELD {name: fld.name}]->(r)
    SET e.line = fld.line, e.injected = fld.injected, e.collection = fld.collection
    """

    SAVE_TYPED_FUNCTIONS = """
    UNWIND $functions AS fn
    MERGE (f:File {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id, path: $file_path})
    MERGE (n:Function {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id, name: fn.name, filePath: $file_path, startLine: fn.start_line})
    SET n.endLine = coalesce(n.endLine, fn.end_line),
        n.raises = fn.raises
    MERGE (f)-[:CONTAINS]->(n)
    """

    SAVE_FUNCTION_TYPES = """
    UNWIND $edges AS e
    MATCH (n:Function {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id, name: e.function, filePath: $file_path, startLine: e.start_line})
    MERGE (r:TypeRef {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id, name: e.type})
    FOREACH (_ IN CASE WHEN e.rel = 'INSTANTIATES' THEN [1] ELSE [] END |
        MERGE (n)-[x:INSTANTIATES]->(r) SET x.line = e.line)
    FOREACH (_ IN CASE WHEN e.rel = 'TAKES' THEN [1] ELSE [] END |
        MERGE (n)-[x:TAKES {name: e.name}]->(r) SET x.line = e.line)
    FOREACH (_ IN CASE WHEN e.rel = 'RETURNS' THEN [1] ELSE [] END |
        MERGE (n)-[x:RETURNS]->(r) SET x.line = e.line)
    """

    def save_type_relations(self, user_id: int, investigation_id: int, project_id: int, file_path: str, relations: dict):
        types = relations.get("types") or []
        functions = relations.get("functions") or []
        fields = [{**fld, "owner": t["name"]} for t in types for fld in t["fields"]]
        edges = []
        for fn in functions:
            key = {"function": fn["name"], "start_line": fn["start_line"]}
            edges += [{**key, "rel": "INSTANTIATES", "type": c["type"], "name": None, "line": c["line"]} for c in fn["creations"]]
            edges += [{**key, "rel": "TAKES", "type": p["type"], "name": p["name"], "line": fn["start_line"]} for p in fn["params"]]
            if fn["returns"]:
                edges.append({**key, "rel": "RETURNS", "type": fn["returns"], "name": None, "line": fn["start_line"]})

        scope = {"user_id": user_id, "investigation_id": investigation_id, "project_id": project_id, "file_path": file_path}
        with self.driver.session() as session:
            if types:
                session.run(self.SAVE_TYPES, {**scope, "types": types})
            if fields:
                session.run(self.SAVE_FIELDS, {**scope, "fields": fields})
            if functions:
                session.run(self.SAVE_TYPED_FUNCTIONS, {**scope, "functions": functions})
            if edges:
                session.run(self.SAVE_FUNCTION_TYPES, {**scope, "edges": edges})

    def save_function(self,user_id:int, investigation_id:int, project_id: int, file_path: str, function_name: str, start_line: int, end_line: int):
        query = """
        MERGE (f:File {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id, path: $file_path})
        MERGE (fn:Function {
            user_id: $user_id,
            investigation_id: $investigation_id,
            projectId: $project_id,
            name: $function_name,
            filePath: $file_path,
            startLine: $start_line
        })
        SET fn.endLine = $end_line
        MERGE (f)-[:CONTAINS]->(fn)
        """

        with self.driver.session() as session:
            session.run(query, {
                "user_id":user_id,
                "investigation_id":investigation_id,
                "project_id": project_id,
                "file_path": file_path,
                "function_name": function_name,
                "start_line": start_line,
                "end_line": end_line
            })
    def save_method_in_class(self,user_id:int, investigation_id:int,project_id: int,file_path: str,class_name: str,method_name: str,start_line: int,end_line: int):
        query = """
        MERGE (c:Class {
            user_id: $user_id,
            investigation_id: $investigation_id,
            projectId: $project_id,
            name: $class_name,
            filePath: $file_path
        })
        MERGE (m:Method {
            projectId: $project_id,
            name: $method_name,
            className: $class_name,
            filePath: $file_path
        })
        SET m.startLine = $start_line,
            m.endLine = $end_line,
            m.user_id = $user_id,
            m.investigation_id = $investigation_id
        MERGE (c)-[:CONTAINS]->(m)
        """
        with self.driver.session() as session:
            session.run(query, {
               "user_id":user_id,
                "investigation_id":investigation_id,  
                "project_id": project_id,
                "file_path": file_path,
                "class_name": class_name,
                "method_name": method_name,
                "start_line": start_line,
                "end_line": end_line
            })
    
    def save_call_relation(
        self,user_id:int, investigation_id:int,
        project_id: int,
        caller_name: str,
        caller_file_path: str,
        called_name: str,
        caller_start_line: int | None = None
    ):
        caller_key = ", startLine: $caller_start_line" if caller_start_line is not None else ""
        query = """
        MERGE (caller:Function {
            user_id: $user_id,
            investigation_id: $investigation_id,
            projectId: $project_id,
            name: $caller_name,
            filePath: $caller_file_path""" + caller_key + """
        })
        MERGE (called:Function {
            user_id: $user_id,
            investigation_id: $investigation_id,
            projectId: $project_id,
            name: $called_name
        })
        MERGE (caller)-[:CALLS]->(called)
        """

        with self.driver.session() as session:
            session.run(query, {
                "user_id":user_id,
                "investigation_id":investigation_id, 
                "project_id": project_id,
                "caller_name": caller_name,
                "caller_file_path": caller_file_path,
                "called_name": called_name,
                "caller_start_line": caller_start_line
            })
            
    def save_import_relation(
        self,
        user_id:int, investigation_id:int,
        project_id: int,
        source_file_path: str,
        imported_module: str
    ):
        query = """
        MERGE (source:File {
            user_id: $user_id,
            investigation_id: $investigation_id,
            projectId: $project_id,
            path: $source_file_path
        })
        MERGE (module:Module {
            user_id: $user_id,
            investigation_id: $investigation_id,
            projectId: $project_id,
            name: $imported_module
        })
        MERGE (source)-[:IMPORTS]->(module)
        """

        with self.driver.session() as session:
            session.run(query, {
                "user_id":user_id,
                "investigation_id":investigation_id, 
                "project_id": project_id,
                "source_file_path": source_file_path,
                "imported_module": imported_module
            })
    
    def get_function_context(self,user_id:int, investigation_id:int, project_id: int, function_name: str, file_path: str):
        query = """
        MATCH (fn:Function {
            user_id:$user_id,
            investigation_id: $investigation_id,
            projectId: $project_id,
            name: $function_name,
            filePath: $file_path
        })
        OPTIONAL MATCH (fn)-[:CALLS]->(called)
        OPTIONAL MATCH (caller)-[:CALLS]->(fn)
        OPTIONAL MATCH (file:File)-[:CONTAINS]->(fn)
        RETURN fn, file, collect(DISTINCT called) AS calledFunctions, collect(DISTINCT caller) AS callers
        """

        with self.driver.session() as session:
            result = session.run(query, {
                "user_id":user_id,
                "investigation_id":investigation_id, 
                "project_id": project_id,
                "function_name": function_name,
                "file_path": file_path
            })

            return [record.data() for record in result]

    @staticmethod
    def _node_dict(node) -> dict:
        return {"id": node.element_id, "labels": list(node.labels), "props": dict(node)}

    def get_function_subgraph(self, user_id: int, investigation_id: int, project_id: int, function_name: str, file_path: str, limit: int = 8):
        query = """
        MATCH (fn:Function {
            user_id: $user_id,
            investigation_id: $investigation_id,
            projectId: $project_id,
            name: $function_name,
            filePath: $file_path
        })
        OPTIONAL MATCH (fn)-[:CALLS]->(callee)
        WITH fn, collect(DISTINCT callee)[..$limit] AS callees
        OPTIONAL MATCH (caller)-[:CALLS]->(fn)
        WITH fn, callees, collect(DISTINCT caller)[..$limit] AS callers
        OPTIONAL MATCH (file:File)-[:CONTAINS]->(fn)
        OPTIONAL MATCH (cls:Class {
            user_id: $user_id,
            investigation_id: $investigation_id,
            projectId: $project_id,
            filePath: $file_path
        })
        WHERE cls.startLine <= fn.startLine AND cls.endLine >= fn.endLine
        RETURN fn, callees, callers,
               collect(DISTINCT file)[0] AS file,
               collect(DISTINCT cls)[0] AS cls
        LIMIT 1
        """

        with self.driver.session() as session:
            record = session.run(query, {
                "user_id": user_id,
                "investigation_id": investigation_id,
                "project_id": project_id,
                "function_name": function_name,
                "file_path": file_path,
                "limit": limit
            }).single()

        if record is None or record["fn"] is None:
            return None

        root = self._node_dict(record["fn"])
        nodes = [root]
        edges = []

        for callee in record["callees"]:
            nodes.append(self._node_dict(callee))
            edges.append({"source": root["id"], "target": callee.element_id, "type": "CALLS"})

        for caller in record["callers"]:
            nodes.append(self._node_dict(caller))
            edges.append({"source": caller.element_id, "target": root["id"], "type": "CALLS"})

        if record["cls"] is not None:
            nodes.append(self._node_dict(record["cls"]))
            edges.append({"source": record["cls"].element_id, "target": root["id"], "type": "CONTAINS"})
        elif record["file"] is not None:
            nodes.append(self._node_dict(record["file"]))
            edges.append({"source": record["file"].element_id, "target": root["id"], "type": "CONTAINS"})

        self._resolve_call_targets(user_id, investigation_id, project_id, nodes)
        return {"root": root["id"], "nodes": nodes, "edges": edges}

    def get_class_subgraph(self, user_id: int, investigation_id: int, project_id: int, class_name: str, file_path: str, limit: int = 12):
        query = """
        MATCH (c:Class {
            user_id: $user_id,
            investigation_id: $investigation_id,
            projectId: $project_id,
            name: $class_name,
            filePath: $file_path
        })
        OPTIONAL MATCH (c)-[:CONTAINS]->(member)
        WITH c, collect(DISTINCT member)[..$limit] AS members
        OPTIONAL MATCH (file:File)-[:CONTAINS]->(c)
        RETURN c, members, collect(DISTINCT file)[0] AS file
        LIMIT 1
        """

        with self.driver.session() as session:
            record = session.run(query, {
                "user_id": user_id,
                "investigation_id": investigation_id,
                "project_id": project_id,
                "class_name": class_name,
                "file_path": file_path,
                "limit": limit
            }).single()

        if record is None or record["c"] is None:
            return None

        root = self._node_dict(record["c"])
        nodes = [root]
        edges = []

        for member in record["members"]:
            nodes.append(self._node_dict(member))
            edges.append({"source": root["id"], "target": member.element_id, "type": "CONTAINS"})

        if record["file"] is not None:
            nodes.append(self._node_dict(record["file"]))
            edges.append({"source": record["file"].element_id, "target": root["id"], "type": "CONTAINS"})

        return {"root": root["id"], "nodes": nodes, "edges": edges}

    def _resolve_call_targets(self, user_id: int, investigation_id: int, project_id: int, nodes: list[dict]):
        # save_call_relation creates callees by raw call text ("self.helper"),
        # without a location; borrow it from the single matching definition.
        unresolved = [n for n in nodes if not n["props"].get("filePath") and "Function" in n["labels"]]
        names = sorted({short_symbol_name(n["props"].get("name")) for n in unresolved} - {""})
        if not names:
            return

        query = """
        UNWIND $names AS short
        MATCH (def:Function {
            user_id: $user_id,
            investigation_id: $investigation_id,
            projectId: $project_id,
            name: short
        })
        WHERE def.filePath IS NOT NULL
        WITH short, collect(def) AS defs
        WHERE size(defs) = 1
        RETURN short, defs[0] AS def
        """

        with self.driver.session() as session:
            definitions = {
                record["short"]: dict(record["def"])
                for record in session.run(query, {
                    "user_id": user_id,
                    "investigation_id": investigation_id,
                    "project_id": project_id,
                    "names": names
                })
            }

        for node in unresolved:
            definition = definitions.get(short_symbol_name(node["props"].get("name")))
            if definition:
                node["props"] = {
                    **node["props"],
                    "filePath": definition.get("filePath"),
                    "startLine": definition.get("startLine"),
                    "endLine": definition.get("endLine")
                }

    CODE_GRAPH_FUNCTIONS = """
    MATCH (fn:Function {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id})
    WHERE fn.filePath IS NOT NULL
    RETURN elementId(fn) AS id, fn.name AS name, fn.filePath AS path, fn.startLine AS startLine, fn.endLine AS endLine,
           fn.raises AS raises
    LIMIT $limit
    """

    CODE_GRAPH_CALLS = """
    MATCH (caller:Function {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id})
          -[:CALLS]->(callee:Function {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id})
    WHERE caller.filePath IS NOT NULL
    RETURN elementId(caller) AS callerId, elementId(callee) AS calleeId,
           callee.name AS calleeName, callee.filePath AS calleePath
    LIMIT $limit
    """

    CODE_GRAPH_CLASSES = """
    MATCH (c:Class {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id})
    RETURN elementId(c) AS id, c.name AS name, c.filePath AS path, c.startLine AS startLine, c.endLine AS endLine,
           c.bases AS bases, c.typeKind AS typeKind, c.events AS events
    LIMIT $limit
    """

    CODE_GRAPH_TYPE_RELATIONS = """
    MATCH (s {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id})
          -[r:INHERITS|HAS_FIELD|INSTANTIATES|TAKES|RETURNS]->
          (t:TypeRef {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id})
    WHERE (s:Class OR s:Function) AND s.filePath IS NOT NULL
    RETURN elementId(s) AS sourceId, type(r) AS type, t.name AS target, r.name AS name, r.line AS line,
           coalesce(r.injected, false) AS injected, coalesce(r.collection, false) AS collection
    LIMIT $limit
    """

    CODE_GRAPH_FILES = """
    MATCH (f:File {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id})
    OPTIONAL MATCH (f)-[:IMPORTS]->(m:Module {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id})
    RETURN f.path AS path, collect(DISTINCT m.name) AS imports
    LIMIT $limit
    """

    def load_code_graph(self, user_id: int, investigation_id: int, project_id: int, limit: int = 20000) -> dict:
        params = {
            "user_id": user_id,
            "investigation_id": investigation_id,
            "project_id": project_id,
            "limit": limit,
        }
        with self.driver.session() as session:
            functions = [r.data() for r in session.run(self.CODE_GRAPH_FUNCTIONS, params)]
            calls = [r.data() for r in session.run(self.CODE_GRAPH_CALLS, params)]
            classes = [r.data() for r in session.run(self.CODE_GRAPH_CLASSES, params)]
            files = [r.data() for r in session.run(self.CODE_GRAPH_FILES, params)]
            type_relations = [r.data() for r in session.run(self.CODE_GRAPH_TYPE_RELATIONS, params)]

        truncated = any(len(rows) >= limit for rows in (functions, calls, classes, files, type_relations))
        return {"functions": functions, "calls": calls, "classes": classes, "files": files,
                "type_relations": type_relations, "truncated": truncated}
