import httpx

from app.models.models import ServiceResult, ChatRequest, ChatResponse
from app.services.file_service import FileService
from app.config import QDRANT_URL, QDRANT_COLLECTION, GEN_MODEL, OLLAMA_URL
from app.services.rag_graph import rag_graph

#langgraph nélküli válaszgenerálás
async def send_message_async(prompt: ChatRequest) -> ServiceResult:
    async with httpx.AsyncClient(timeout=10000) as http_client:
        # text -> embedding
        #JAVITAS
        file_service=FileService()
        vec = await file_service.embed(http_client, prompt.prompt)
        
        results_sum=await search_vector("summary",vec,http_client)
        results_code=await search_vector("code",vec,http_client)
        results_text=await search_vector("text",vec,http_client)
        print(f"code: {len(results_code)}")
        print(f"sum: {len(results_sum)}")
        print(f"text: {len(results_text)}")
        #print("még jóóóó 1")

        if len(results_sum)+len(results_code)+len(results_text) == 0:
            return ServiceResult.success({
                "answer": "Nem találom a dokumentumokban."
            })

        # context összeállítása
        all_results = results_sum + results_code + results_text
        
        for r in all_results:
            print(r.get("score", 0))

        # score alapján csökkenő sorrend, bizonyos score felett rakom cak bele JAVITAS
        top_results = sorted(
            [r for r in all_results if r.get("score", 0) >= 0.35],
            #all_results,
            key=lambda r: r.get("score", 0),
            reverse=True
        )[:5]
        print("TOP EREDMÉNYEK SZÁMA:")
        print(len(top_results))
        if not top_results:
            return ServiceResult.success({
                "answer": "Nem találom a dokumentumokban."
            })
        context_parts = []
        create_context(top_results,context_parts)
        #create_context(results_code,context_parts)
        
        #create_context(results_sum,context_parts)
        #create_context(results_text,context_parts)

        context = "\n\n---\n\n".join(context_parts)
        print("CONTEXT")
        print(context)
        print("context vége")
        #print("még jóóóó 2")

        # prompt
        final_prompt = f"""Te egy asszisztens vagy, aki KIZÁRÓLAG az alábbi KONTEKSZTUS alapján válaszol.
        Mindig azon a nyelven válaszolj, amilyen nyelven a kérdés elhangzott.
        A szavak közé tegyél szóközöket, ha kell, úgy hogy értelmesen legyenek elválasztva.
        Ha a válasz nem található a kontextusban, mondd: "Nem találom a dokumentumokban."

        KONTEKSZTUS:
        {context}

        KÉRDÉS:
        {prompt}
        """

        # Ollama generate
        gen_payload = {
            "model": GEN_MODEL,
            "prompt": final_prompt,
            "stream": False
        }

        gen_response = await http_client.post(
            f"{OLLAMA_URL}/api/generate",
            json=gen_payload
        )
        gen_response.raise_for_status()

        gen_data = gen_response.json()
        answer = gen_data.get("response") or " "

        print("A válasz:", answer)

        return ServiceResult.success({
            "answer": answer
        })
async def send_message_async_langgraph(prompt: ChatRequest) -> ServiceResult:
    result = await rag_graph.ainvoke({
        "question": prompt.prompt,
        "user_id": prompt.userId,
        "investigation_id": prompt.investigationId,
        "project_id": prompt.projectId
    })

    response = ChatResponse(
        answer=result.get("answer", "Nem találom a dokumentumokban."),
        evidence=result.get("evidence") or []
    )
    return ServiceResult.success(response.model_dump())
