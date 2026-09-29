from typing import TypedDict, List
import httpx
import json
import time
from langgraph.graph import StateGraph, END

from app.config import GEN_MODEL_CLOUD, OLLAMA_API_KEY, OLLAMA_BASE_URL, QDRANT_URL, QDRANT_COLLECTION, GEN_MODEL, OLLAMA_URL
from app.services.file_service import FileService
from app.services.ollama_call import call_llm
from app.services.neo4j_service import Neo4jService


class RagState(TypedDict, total=False):
    user_id:int
    investigation_id: int
    project_id: int
    question: str
    rephrased_question: str

    # Angol pivot-nyelv. Az index (kulonosen a summary-vektorok) angolul keszul,
    # ezert a keresesig minden angolul folyik: question_en a lefordtott kerdes,
    # answer_en a modell angol valasza. A language/language_name csak arra kell,
    # hogy a vegen visszaforditsuk a valaszt a kerdezo nyelvere.
    language: str
    language_name: str
    question_en: str
    answer_en: str

    question_type: str
    search_vectors: List[str]

    vector: List[float]

    results: List[dict]
    top_results: List[dict]
    graph_context: List[str]

    context: str
    answer: str
    
    use_graph: bool
    needs_rerank: bool
    #for testing
    ground_truth: str

    retrieved_contexts: List[str]

    retrieval_time_ms: float
    generation_time_ms: float
    total_time_ms: float

    retrieved_count: int

    ragas_run_id: str

def extract_json(raw: str) -> dict:
    """A modell valaszabol kiszedi a JSON objektumot.

    A kisebb modellek hajlamosak ```json keretbe tenni a valaszt vagy egy
    bevezeto mondatot irni ele; a nyers json.loads ezeken elhasal.
    """
    text = raw.strip()

    if "```" in text:
        parts = text.split("```")
        if len(parts) > 1:
            text = parts[1]
            if text.lstrip().lower().startswith("json"):
                text = text.lstrip()[4:]

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end < start:
        raise ValueError(f"Nincs JSON a valaszban: {raw[:200]}")

    return json.loads(text[start:end + 1])


async def classify_question(state: RagState) -> RagState:
    question = state["question"]

    # A nyelvfelismeres es a forditas szandekosan ugyanebben a hivasban tortenik.
    # Kulon node-kent minden kerdes egy plusz LLM-kort jelentene, ami CPU-n futo
    # modellnel percekben merheto; a klasszifikacio ugyis strukturalt JSON-t ad
    # vissza, ket mezot elbir meg.
    classifier_prompt = f"""
    Task:
    Analyse a user's question about a source code repository.

    Categories:

    1. code
    The question asks about concrete code: a function, class, method, error,
    import, API, router, service, variable or implementation detail.

    2. summary
    The question asks you to explain what a component, file, class, method or
    process does.

    3. text
    The question asks about documentation, a README, installation, configuration,
    a description or a usage guide.

    4. general
    It is not clear, or several kinds of search are justified.

    Your answer must be ONLY valid JSON, nothing else.

    Format:
    {{
    "language": "ISO 639-1 code of the language the question is written in, e.g. en, hu, de",
    "language_name": "English name of that language, e.g. English, Hungarian, German",
    "question_en": "the question translated into English",
    "question_type": "code | summary | text | general",
    "search_vectors": ["code", "summary", "text"]
    }}

    Search vector rules:
    - for code: ["code", "summary"]
    - for summary: ["summary", "code", "text"]
    - for text: ["text", "summary"]
    - for general: ["summary", "code", "text"]

    Translation rules:
    - If the question is already in English, copy it into question_en unchanged.
    - Keep identifiers, class names, function names, file paths, file extensions
      and code fragments EXACTLY as they are written. Never translate them.
      "Mit csinal a validate_proxy?" becomes "What does validate_proxy do?",
      never "What does validate the proxy do?".
    - Translate only the natural language part of the question.
    - Keep the meaning; do not answer the question and do not explain it.

    Question:
    {question}
    """

    try:
        # call_llm-en keresztul, nem sajat httpx-hivassal: a helyi Ollama nem ker
        # auth-ot, es a httpx elutasitja az ures "Bearer " fejlecet. Ez a node
        # korabban sajat kezuleg allitotta ossze a kerest, es emiatt MINDEN
        # kerdesnel elhasalt ("Illegal header value b'Bearer '"), csondben a
        # fallback againra esve. A call_llm mar kezeli ezt az esetet.
        raw_answer = (await call_llm(classifier_prompt)).strip()

        parsed = extract_json(raw_answer)

        question_type = parsed.get("question_type", "general")
        search_vectors = parsed.get("search_vectors", ["summary", "code", "text"])

        allowed_types = {"code", "summary", "text", "general"}
        allowed_vectors = {"code", "summary", "text"}

        if question_type not in allowed_types:
            question_type = "general"

        search_vectors = [
            vector for vector in search_vectors
            if vector in allowed_vectors
        ]

        if not search_vectors:
            search_vectors = ["summary", "code", "text"]

        language = str(parsed.get("language") or "en").strip().lower()[:5]
        language_name = str(parsed.get("language_name") or "English").strip()

        # Ures forditas eseten az eredeti kerdessel megyunk tovabb: egy rossz
        # kereses is tobbet er, mint egy ures.
        question_en = str(parsed.get("question_en") or "").strip() or question

        print(f"Nyelv: {language} ({language_name}) | Angol kerdes: {question_en}")

        return {
            **state,
            "question_type": question_type,
            "search_vectors": search_vectors,
            "language": language,
            "language_name": language_name,
            "question_en": question_en
        }

    except Exception as e:
        # A forditas is itt bukik el, ezert a fallback angolnak veszi a kerdest:
        # igy a valasz a kerdes eredeti nyelven szuletik, mint a pivot elott.
        # Rosszabb, mint a forditott ut, de hasznalhato valaszt ad.
        print("classify_question hiba:", e)
        return {
            **state,
            "question_type": "general",
            "search_vectors": ["summary", "code", "text"],
            "language": "en",
            "language_name": "English",
            "question_en": question
        }

async def rephrase_question(state: RagState) ->RagState:
    # Mar a lefordtott kerdesbol dolgozunk: a keresesi lekerdezesnek angolul
    # kell lennie, mert az index is angol.
    start_question = state.get("question_en") or state["question"]

    rewrite_prompt = f"""
    Task:
    Turn the user's question into a search query that gives the best possible
    vector database search in a RAG system containing source code and documentation.

    Goal:
    - Improve semantic search
    - Bring out the important technical concepts
    - Add relevant synonyms
    - Use developer terminology
    - Keep the original meaning
    - Do not answer the question
    - Do not explain
    - Return only the search query

    Rules:
    - Keep it short and dense
    - It may contain keywords
    - It may contain technical concepts
    - It may contain related component names
    - It may contain framework names
    - It may contain programming concepts
    - Write the query in English
    - Do not use markdown formatting
    - Do not write full sentences unless necessary
    - Your answer must be ONLY the search query
    - Do not write an introduction
    - Do not write an explanation
    - Do not use quotation marks
    - If the question contains a class, function or file name, always keep it
    in the search query, spelled exactly as given

    Behaviour per question type:
    - code:
    focus on:
    - functions
    - classes
    - implementation
    - APIs
    - variable names
    - source code concepts

    - summary:
    focus on:
    - architecture
    - components
    - behaviour
    - responsibilities
    - processes

    - text:
    focus on:
    - documentation
    - configuration
    - installation
    - usage
    - README-like concepts

    - general:
    use a mix of technical and documentation keywords

    Examples:

    Question:
    "where is the auth?"

    Search query:
    authentication auth login jwt token authorization middleware AuthService
    ---
    Question:
    "what does the file upload do?"

    Search query:
    file upload UploadFile multipart form-data file_service upload_qdrant_async FastAPI endpoint
    ---
    Question:
    "how does the router work?"

    Search query:
    FastAPI router APIRouter endpoint route request handler controller API routing
    ---
    User question:
    {start_question}

    Question type:
    {state['question_type']}
    """
    '''
    payload = {
        "model": GEN_MODEL_CLOUD,
        "prompt": rewrite_prompt,
        "stream": False
    }

    try:
        async with httpx.AsyncClient(timeout=10000) as http_client:
            response = await http_client.post(
                f"{OLLAMA_URL}/api/generate",
                json=payload
            )
            response.raise_for_status()
            
            data = response.json()'''

    rewritten_query = await call_llm(rewrite_prompt)
            
    return{
        **state,
        "rephrased_question":rewritten_query
    }
    '''except Exception as e:
        print("rephrase_question hiba:", e)
        return {
            **state,
            "rephrased_question": start_question
        }'''
    
async def search_plan(state: RagState) -> RagState:
    question_type = state.get("question_type", "general")

    if question_type == "text":
        return {
            **state,
            "use_graph": False,
            "needs_rerank": False
        }

    if question_type in ["code", "summary", "general"]:
        return {
            **state,
            "use_graph": True,
            "needs_rerank": True
        }

    return {
        **state,
        "use_graph": True,
        "needs_rerank": False
    }
def route_after_filter(state: RagState) -> str:
    if not state.get("top_results"):
        return "build_context"
    if state.get("use_graph", False):
        return "search_knowledge_graph"

    if state.get("needs_rerank", False):
        return "rerank_results"

    return "build_context"

def route_after_graph(state: RagState) -> str:
    if state.get("needs_rerank", False):
        return "rerank_results"

    return "build_context"
    
async def embed_question(state: RagState) -> RagState:
    text_for_embedding = (
        state.get("rephrased_question")
        or state.get("question_en")
        or state.get("question")
        or ""
    )

    print("Embedding keresési szöveg:", text_for_embedding)

    async with httpx.AsyncClient(timeout=10000) as http_client:
        file_service = FileService()
        vector = await file_service.embed(http_client, text_for_embedding)

    return {
        **state,
        "vector": vector
    }


async def search_vector(
    vector_name: str,
    vector: List[float],
    http_client: httpx.AsyncClient,
    state:RagState
) -> List[dict]:
    '''search_payload = {
        "vector": {
            "name": vector_name,
            "vector": vector
        },
        "limit": 3,
        "with_payload": True
    }'''
    search_payload = {
    "vector": {
        "name": vector_name,
        "vector": vector
    },
    "limit": 5,
    "with_payload": True,
    "filter": {
        "must": [
            {
                "key": "userId",
                "match": {
                    "value": state.get("user_id")
                }
            },
            {
                "key": "investigationId",
                "match": {
                    "value":  state.get("investigation_id")
                }
            },
            {
                "key": "projectId",
                "match": {
                    "value":  state.get("project_id")
                }
            }
        ]
    }
    }

    response = await http_client.post(
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/search",
        json=search_payload
    )
    response.raise_for_status()

    data = response.json()
    return data.get("result", [])


async def search_qdrant(state: RagState) -> RagState:
    #teszt
    start_time = time.perf_counter()
    vector = state["vector"]
    search_vectors = state.get("search_vectors", ["summary", "code", "text"])

    results = []

    async with httpx.AsyncClient(timeout=10000) as http_client:
        for vector_name in search_vectors:
            vector_results = await search_vector(
                vector_name=vector_name,
                vector=vector,
                http_client=http_client,
                state=state
            )

            for result in vector_results:
                result["matched_vector"] = vector_name
                results.append(result)
    print("RESULTS:", len(results))
    return {
        **state,
        "results": results,
        #test
        "retrieval_time_ms":(time.perf_counter()-start_time)*1000
    }


async def filter_results(state: RagState) -> RagState:
    results = state.get("results", [])

    top_results = sorted(
        [r for r in results if r.get("score", 0) >= 0.35],
        key=lambda r: r.get("score", 0),
        reverse=True
    )[:5]
    print("TOP_RESULTS: ",len(top_results))
    return {
        **state,
        "top_results": top_results,
        #test
        "retrieved_count": len(top_results)
    }


async def build_context(state: RagState) -> RagState:
    top_results = state.get("top_results", [])

    context_parts = []
    #test
    retrieved_contexts = []
    

    for index, result in enumerate(top_results, start=1):
        payload = result.get("payload", {})

        doc_name = payload.get("docName") or "unknown document"
        path = payload.get("path") or ""
        kind = payload.get("kind") or ""
        name = payload.get("name") or ""
        matched_vector = result.get("matched_vector") or ""

        text = (
            payload.get("content")
            or payload.get("chunk")
            or payload.get("page_content")
            or payload.get("text")
            or payload.get("summary")
            or payload.get("code")
            or payload.get("description")
            or ""
        )

        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)

        if not text.strip():
            print("Üres payload szöveg. Elérhető payload kulcsok:", list(payload.keys()))
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            continue

        # A cimkek is angolul: a kontextus nyelve erosen befolyasolja, milyen
        # nyelven valaszol a modell, es itt angol valaszt akarunk.
        context_parts.append(
            f"[Source {index}: {doc_name}]\n"
            f"Path: {path}\n"
            f"Kind: {kind}\n"
            f"Name: {name}\n"
            f"Matched vector: {matched_vector}\n"
            f"Score: {result.get('score', 0)}\n\n"
            f"{text}"
        )
        
        #test
        retrieved_contexts.append(text)

    context = "\n\n---\n\n".join(context_parts)

    graph_context = state.get("graph_context", [])

    if graph_context:
        context += "\n\n===== KNOWLEDGE GRAPH RELATIONS =====\n\n"
        context += "\n\n".join(graph_context)

    print("Keresési kontextus:", context)

    return {
        **state,
        "context": context,
        #test
        "retrieved_contexts": retrieved_contexts,
        "retrieved_count": len(retrieved_contexts)
    }


# A "nincs talalat" valasz angolul szuletik, mint minden mas; a
# translate_answer forditja vissza a kerdezo nyelvere.
NOT_FOUND_EN = "I could not find this in the documents."


async def generate_answer(state: RagState) -> RagState:
    start_time = time.perf_counter()
    # A modell az angol kerdest kapja, es angolul is valaszol: a kontextus
    # (kod es angol osszefoglalok) igy vegig egy nyelven van vele.
    question = state.get("question_en") or state["question"]
    context = state.get("context", "")

    if not context.strip():
        return {
            **state,
            "answer_en": NOT_FOUND_EN,
            #test
            "generation_time_ms": (time.perf_counter() - start_time) * 1000,
            "total_time_ms": state.get("retrieval_time_ms", 0) + ((time.perf_counter() - start_time) * 1000)
        }


    final_prompt = f"""
    You are an assistant that answers ONLY from the CONTEXT below.

    Rules:
    - Always answer in English, whatever language anything else is written in.
    - If the answer is not in the context, say exactly: "{NOT_FOUND_EN}"
    - Do not invent anything outside the context.
    - If asked about code, explain clearly what it is for and how it works.
    - If there are several sources, combine the information.
    - Phrase the answer naturally, do not just copy the context back.
    - Never translate code fragments, identifiers or file paths.

    QUESTION TYPE:
    {state.get("question_type", "unknown")}

    CONTEXT:
    {context}

    QUESTION:
    {question}
    """

    '''gen_payload = {
        "model": GEN_MODEL_CLOUD,
        "prompt": final_prompt,
        "stream": False
    }

    async with httpx.AsyncClient(timeout=10000) as http_client:
        response = await http_client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=gen_payload
        )
        response.raise_for_status()

    data = response.json()
    answer = data.get("response") or " "'''
    answer=await call_llm(final_prompt)
    print("AZ ANGOL VÁLASZ: ",answer)
    generation_time_ms = (time.perf_counter() - start_time) * 1000
    return {
        **state,
        "answer_en": answer,
        #test
        "generation_time_ms": generation_time_ms,
        "total_time_ms": state.get("retrieval_time_ms", 0) + generation_time_ms
    }


async def translate_answer(state: RagState) -> RagState:
    """Az angol valaszt visszaforditja a kerdes nyelvere.

    Ez az egyetlen plusz LLM-hivas a pivot miatt, es csak akkor fut le, ha a
    kerdes nem angol volt. Angol kerdesnel csak atmasolja a valaszt.
    """
    answer_en = (state.get("answer_en") or "").strip()
    language = (state.get("language") or "en").lower()
    language_name = state.get("language_name") or "English"

    if not answer_en:
        return {**state, "answer": NOT_FOUND_EN}

    if language.startswith("en"):
        return {**state, "answer": answer_en}

    start_time = time.perf_counter()

    translate_prompt = f"""
    Translate the text below into {language_name}.

    Rules:
    - Return ONLY the translation, nothing else.
    - Do not write an introduction, a note or an explanation.
    - Do NOT translate code fragments, identifiers, function names, class names,
      file paths or file extensions - copy them exactly as they are.
    - Keep the structure of the text: line breaks, lists and code blocks stay.
    - Use natural, fluent {language_name}, not a word by word translation.

    Text:
    {answer_en}
    """

    try:
        translated = (await call_llm(translate_prompt)).strip()
    except Exception as e:
        # Egy angol valasz tobbet er, mint egy hibauzenet.
        print("translate_answer hiba:", e)
        return {**state, "answer": answer_en}

    if not translated:
        return {**state, "answer": answer_en}

    print(f"A LEFORDÍTOTT VÁLASZ ({language}): ", translated)

    translation_time_ms = (time.perf_counter() - start_time) * 1000

    return {
        **state,
        "answer": translated,
        #test
        "total_time_ms": state.get("total_time_ms", 0) + translation_time_ms
    }



async def search_knowledge_graph(state: RagState) -> RagState:
    top_results = state.get("top_results", [])
    graph_context = []

    neo4j = Neo4jService()

    try:
        for result in top_results:
            payload = result.get("payload", {})

            kind = payload.get("kind")
            name = payload.get("name")
            path = payload.get("path")

            user_id = payload.get("userId")
            investigation_id = payload.get("investigationId")
            project_id = payload.get("projectId")

            if kind not in ["function", "method", "class"]:
                continue

            if not name or not path:
                continue

            context_items = neo4j.get_function_context(
                user_id=user_id,
                investigation_id=investigation_id,
                project_id=project_id,
                function_name=name,
                file_path=path
            )

            if context_items:
                graph_context.append(
                    f"Knowledge graph match for: {name}\n"
                    f"Path: {path}\n"
                    f"Relations:\n{json.dumps(context_items, ensure_ascii=False, indent=2, default=str)}"
                )

    finally:
        neo4j.close()

    return {
        **state,
        "graph_context": graph_context
    }
async def rerank_results(state: RagState) -> RagState:
    top_results = state.get("top_results", [])

    reranked = sorted(
        top_results,
        key=lambda r: (
            1 if r.get("payload", {}).get("kind") in ["function", "class", "method"] else 0,
            r.get("score", 0)
        ),
        reverse=True
    )

    return {
        **state,
        "top_results": reranked
    }
    
builder = StateGraph(RagState)

builder.add_node("classify_question", classify_question)
builder.add_node("search_plan", search_plan)
builder.add_node("rephrase_question", rephrase_question)
builder.add_node("embed_question", embed_question)
builder.add_node("search_qdrant", search_qdrant)
builder.add_node("filter_results", filter_results)
builder.add_node("search_knowledge_graph", search_knowledge_graph)
builder.add_node("rerank_results", rerank_results)
builder.add_node("build_context", build_context)
builder.add_node("generate_answer", generate_answer)
builder.add_node("translate_answer", translate_answer)

builder.set_entry_point("classify_question")

builder.add_edge("classify_question", "search_plan")
builder.add_edge("search_plan", "rephrase_question")
builder.add_edge("rephrase_question", "embed_question")
builder.add_edge("embed_question", "search_qdrant")
builder.add_edge("search_qdrant", "filter_results")

builder.add_conditional_edges(
    "filter_results",
    route_after_filter,
    {
        "search_knowledge_graph": "search_knowledge_graph",
        "rerank_results": "rerank_results",
        "build_context": "build_context"
    }
)

builder.add_conditional_edges(
    "search_knowledge_graph",
    route_after_graph,
    {
        "rerank_results": "rerank_results",
        "build_context": "build_context"
    }
)

builder.add_edge("rerank_results", "build_context")
builder.add_edge("build_context", "generate_answer")
builder.add_edge("generate_answer", "translate_answer")
builder.add_edge("translate_answer", END)

rag_graph = builder.compile()

print(rag_graph.get_graph().draw_mermaid())
rag_graph.get_graph().draw_mermaid_png()