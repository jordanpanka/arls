import io
from pypdf import PdfReader
from fastapi import UploadFile
import httpx
import os
import uuid
import httpx

from fastapi import UploadFile

from app.config import EMBED_MODEL_CLOUD, OLLAMA_API_KEY, OLLAMA_BASE_URL, QDRANT_URL, QDRANT_COLLECTION, EMBED_MODEL, OLLAMA_URL
from app.models.models import Ids, ServiceResult
from app.services.parse_service import CodeParser
from app.services.node_creator import NodeCreator
from llama_index.core.schema import TextNode

from typing import List
from fastapi import UploadFile, Form, File

from app.services.neo4j_service import Neo4jService

class FileService:

    ignore_directories = [
        "node_modules", "bin", "obj", "dist", "build", "out",
        ".git", ".github", ".venv", "venv", "__pycache__", "site-packages",
        ".next", ".nuxt", "target", "vendor", "ragas_env",
        ".pytest_cache", ".mypy_cache", ".idea", ".vs", "coverage", "packages",
    ]

    ignore_extensions = [
        ".exe", ".dll", ".so", ".dylib", ".obj", ".class", ".pyc", ".pyd",
        ".bin", ".dat", ".lock", ".png", ".jpg", ".jpeg", ".gif", ".svg",
        ".ico", ".zip", ".gz", ".tar", ".woff", ".woff2", ".ttf",
    ]

    ignore_filenames = [".env", "id_rsa", "id_ed25519", ".npmrc", ".pypirc"]

    code_sources=[".cs", ".py" , ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".php", ".cpp", ".c", ".h", ".hpp"]
    structured_data=[".json",".yaml", ".yml" , ".xml", ".toml", ".ini", ".cfg", ".conf", ".properties", ".gradle", ".sql"]
    documentation=[".md", ".txt", ".rst", ".pdf"]

    known_filenames = {
        "dockerfile": "structured",
        "containerfile": "structured",
        "makefile": "structured",
        "jenkinsfile": "structured",
        "vagrantfile": "structured",
        "procfile": "structured",
        "codeowners": "structured",
        "gemfile": "structured",
        "rakefile": "structured",
        "readme": "documentation",
        "license": "documentation",
        "licence": "documentation",
        "changelog": "documentation",
        "contributing": "documentation",
        "authors": "documentation",
        "notice": "documentation",
        "todo": "documentation",
    }
    
    async def extract_text_from_pdf(self,file: UploadFile) -> str:
        # file beolvasása memóriába
        content = file.file.read()

        reader = PdfReader(io.BytesIO(content))

        text_parts = []

        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

        return "\n".join(text_parts)

    def chunk_text(self,text: str, chunk_length: int, redundance: int) -> list[str]:
        chunks=[]
        i=0
        while i<len(text):
            length=min(chunk_length, len(text)-1)
            chunk=text[i:i+length]
            chunks.append(chunk)
            
            i+=chunk_length-redundance
            if(chunk_length-redundance <=0):
                break
        
        return chunks

    async def embed(self, http: httpx.AsyncClient, text: str) -> list[float]:
       
        if not text or not text.strip():
            return []

        payload = {
            "model": EMBED_MODEL,
            "prompt": text
        }

        response = await http.post(
            f"{OLLAMA_URL}/api/embeddings",
            json=payload
        )

        response.raise_for_status()

        data = response.json()

        return [float(x) for x in data.get("embedding") or []]
    
    async def upload_qdrant_async(self,user_id: int ,
        inv_id: int,
        project_id: int,
        paths: List[str] ,
        files: List[UploadFile] ) -> ServiceResult:
        try:
            async with httpx.AsyncClient(timeout=5000) as http_client:
                points=[]
                skipped_nodes=0
                neo4j_service=Neo4jService()
                for i in range(len(files)):
                    text = ""
                    
                    if files[i] is None:
                        return ServiceResult.fail("File is empty")

                    content = await files[i].read()
                    if len(content) == 0:
                        return ServiceResult.fail("File is empty")

                    await files[i].seek(0)

                    doc_name = os.path.basename(files[i].filename or "")
                    ext = os.path.splitext(doc_name)[1].lower()
                    #depends on the filetype, what should i do
                    type=self.select_file_type(paths[i])
                    
                    match type:
                        case "ignore":
                            continue
                        case "code":
                            nodes, relations=await self.process_code_file(files[i], paths[i])
                            
                            neo4j_service.save_file(
                                user_id=user_id,
                                investigation_id=inv_id,
                                project_id=project_id,
                                file_path=paths[i],
                                file_name=files[i].filename
                            )
                            for node in nodes:
                                kind = node.metadata.get("kind")
                                name = node.metadata.get("name")
                                start_line = node.metadata.get("start_line")
                                end_line = node.metadata.get("end_line")
                                                    
                                if kind == "class":
                                    neo4j_service.save_class(
                                        user_id=user_id,
                                        investigation_id=inv_id,
                                        project_id=project_id,
                                        file_path=paths[i],
                                        class_name=name,
                                        start_line=start_line,
                                        end_line=end_line
                                    )

                                elif kind == "function":
                                    neo4j_service.save_function(
                                        user_id=user_id,
                                        investigation_id=inv_id,
                                        project_id=project_id,
                                        file_path=paths[i],
                                        function_name=name,
                                        start_line=start_line,
                                        end_line=end_line
                                    )
                                
                                
                                #embed code and summary text
                                code=await self.embed(http_client,node.text)
                                summary=await self.embed(http_client,node.metadata["summary"])

                                # Mindkét vektor kell: a kollekció "code" és
                                # "summary" néven is 768 dimenziót vár.
                                if not code or not summary:
                                    skipped_nodes += 1
                                    print(f"Kihagyva (üres embedding): {paths[i]} -> {node.metadata.get('name')}")
                                    continue

                                points.append({
                                    "id":str(uuid.uuid4()),
                                    "vector":{
                                        "code":code,
                                        "summary":summary
                                    },
                                    "payload":{
                                        "userId":user_id,
                                        "investigationId": inv_id,
                                        "projectId": project_id,
                                        "docName": files[i].filename,
                                        "path": node.metadata.get("path", paths[i]),
                                        "kind": node.metadata.get("kind", "code"),
                                        "name": node.metadata.get("name", ""),
                                        "code": node.text,
                                        "summary": node.metadata["summary"],
                                        "start_line": node.metadata.get("start_line"),
                                        "end_line": node.metadata.get("end_line"),
                                        "ts_type": node.metadata.get("ts_type")
                                    }
                                        
                                })
                            for imported_module in relations["imports"]:
                                neo4j_service.save_import_relation(
                                    user_id=user_id,
                                    investigation_id=inv_id,
                                    project_id=project_id,
                                    source_file_path=paths[i],
                                    imported_module=imported_module
                                )

                            for call in relations["calls"]:
                                neo4j_service.save_call_relation(
                                    user_id=user_id,
                                    investigation_id=inv_id,
                                    project_id=project_id,
                                    caller_name=call["caller"],
                                    caller_file_path=paths[i],
                                    called_name=call["called"]
                                )
                            
                            for method in relations["methods"]:
                                neo4j_service.save_method_in_class(
                                    user_id=user_id,
                                    investigation_id=inv_id,
                                    project_id=project_id,
                                    file_path=paths[i],
                                    class_name=method["class"],
                                    method_name=method["method"],
                                    start_line=method["start_line"],
                                    end_line=method["end_line"]
                                )
                                
                        # Config files (json/yaml/Dockerfile/...) and prose both
                        # embed as plain text; neither has a tree-sitter grammar
                        # configured, so there is nothing to parse into nodes.
                        case "structured" | "documentation":
                            nodes=await self.process_doc_file(files[i],paths[i])
                            for node in nodes:
                                text_vec=await self.embed(http_client,node.text)
                                if not text_vec:
                                    skipped_nodes += 1
                                    print(f"Kihagyva (üres embedding): {paths[i]}")
                                    continue
                                points.append({
                                    "id":str(uuid.uuid4()),
                                    "vector":{
                                        "text":text_vec
                                    },
                                    "payload":{
                                        "userId":user_id,
                                        "investigationId": inv_id,
                                        "projectId": project_id,
                                        "docName": files[i].filename,
                                        "path": node.metadata.get("path", paths[i]),
                                        "kind": type,
                                        "text": node.text

                                    }
                                })
                
                     
                    
                
                # Text -> chunks
                # chunk = chunk_text(text, 800, 170)
                if not points:
                    
                    print(f"Nincs feltöltendő pont ({skipped_nodes} node kihagyva)")
                    return ServiceResult.success({"indexed": 0, "skipped": skipped_nodes})


                upsert_payload = {
                    "points": points
                }

                upsert_res = await http_client.put(
                        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points?wait=true",
                        json=upsert_payload
                )
                upsert_res.raise_for_status()

                return ServiceResult.success({"indexed": len(points), "skipped": skipped_nodes})
        finally:
            neo4j_service.close()  
        
        
    def select_file_type(self, file_path: str) -> str:
        normalized = file_path.replace("\\", "/").lower()
        segments = [s for s in normalized.split("/") if s]

        if not segments:
            return "unknown"

        filename = segments[-1]
        directories = segments[:-1]

        # Whole-segment comparison, not a substring test over the full path.
        if any(directory in self.ignore_directories for directory in directories):
            return "ignore"

        if filename in self.ignore_filenames:
            return "ignore"

        extension = os.path.splitext(filename)[1]

        if extension:
            if extension in self.ignore_extensions:
                return "ignore"
            if extension in self.code_sources:
                return "code"
            if extension in self.structured_data:
                return "structured"
            if extension in self.documentation:
                return "documentation"
            return "unknown"

        # Dockerfile, Makefile, README, LICENSE and friends.
        return self.known_filenames.get(filename, "unknown")
            
    #process code files
    async def process_code_file(self,file: UploadFile, path:str)->List[TextNode]:
            c_parser=CodeParser()
            tree, source_code=await c_parser.parse_code_to_tree(file,path)
            print("AST SYNTAX TREE")
            c_parser.print_tree(tree.root_node)
            classnodes, functionnodes=c_parser.extract_class_function_nodes(tree.root_node)
            print("CLASS NODES:", len(classnodes))
            print("FUNCTION NODES:", len(functionnodes))   
            relations = c_parser.extract_graph_relations(tree, source_code)   
            nodecreator=NodeCreator()
            llamaindexnodes=[]
            for node in classnodes:
                llamaindexnodes.extend(nodecreator.ts_node_to_llamaindex_node_class(node,source_code,path))
            
            for node in functionnodes:
                llamaindexnodes.extend(nodecreator.ts_node_to_llamaindex_node_function(node, source_code, path))
                
            for node in llamaindexnodes:
                summary= await nodecreator.generate_summary_to_node(node)
                print("Az összefoglaló")
                print(summary)
                node.metadata["summary"] = summary
            return llamaindexnodes, relations
        
        
    async def extract_text_from_plain(self, file: UploadFile) -> str:
        content = await file.read()
        # Repository files are whatever encoding the author used; never fail on one.
        return content.decode("utf-8", errors="replace")

    async def process_doc_file(self,file: UploadFile, path:str)->List[TextNode]:
           
            if path.lower().endswith(".pdf"):
                text=await self.extract_text_from_pdf(file)
            else:
                text=await self.extract_text_from_plain(file)

            chunks=self.chunk_text(text, 800, 120)
            tsnodes=[]
            for chunk in chunks:
                node=TextNode(
                    text=chunk,
                    metadata={
                        "path":path
                        
                    }
                )
                tsnodes.append(node)
            return tsnodes