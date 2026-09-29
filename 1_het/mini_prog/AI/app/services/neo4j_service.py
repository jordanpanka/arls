from neo4j import GraphDatabase
from app.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

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
    
    def save_function(self,user_id:int, investigation_id:int, project_id: int, file_path: str, function_name: str, start_line: int, end_line: int):
        query = """
        MERGE (f:File {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id, path: $file_path})
        MERGE (fn:Function {
            user_id: $user_id,
            investigation_id: $investigation_id,
            projectId: $project_id,
            name: $function_name,
            filePath: $file_path
        })
        SET fn.startLine = $start_line,
            fn.endLine = $end_line
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
            m.endLine = $end_line
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
        called_name: str
    ):
        query = """
        MERGE (caller:Function {
            user_id: $user_id,
            investigation_id: $investigation_id,
            projectId: $project_id,
            name: $caller_name,
            filePath: $caller_file_path
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
                "called_name": called_name
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