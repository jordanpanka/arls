import asyncio
import csv
import json

from app.services.rag_graph import rag_graph


TEST_QUESTIONS = [
{
"question": "Mit tartalmaz az ollama_call.py fájl?",
"ground_truth": "Az ollama_call.py a call_llm függvényt tartalmazza, amely HTTP kéréssel kommunikál a konfigurált nyelvi modellel."
},
{
"question": "Milyen függvényeket tartalmaz az ollama_call.py fájl?",
"ground_truth": "Az ollama_call.py egy call_llm nevű aszinkron függvényt tartalmaz."
},
{
"question": "Mi a FileService osztály felelőssége?",
"ground_truth": "A FileService a fájlok feldolgozásáért, embedding generálásáért, chunkolásáért és adattárolásáért felel."
},
{
"question": "Mire használható a Neo4j a projektben?",
"ground_truth": "A Neo4j a fájlok, osztályok, függvények és kapcsolataik gráfos tárolására szolgál."
},
{
"question": "Milyen függvényeket tartalmaz a FileService osztály?",
"ground_truth": "A FileService PDF feldolgozó, chunkoló, embedding generáló, fájltípus felismerő és feltöltő függvényeket tartalmaz."
},
{
"question": "Mire jó a process_code_file függvény?",
"ground_truth": "A process_code_file AST-t épít, kinyeri a kódelemeket és összefoglalókat generál hozzájuk."
},
{
"question": "Mire jó a process_doc_file függvény?",
"ground_truth": "A process_doc_file dokumentumokat chunkokra bont és TextNode objektumokat hoz létre."
},
{
"question": "Hogyan történik az embedding generálás a rendszerben?",
"ground_truth": "Az embeddingeket a FileService embed függvénye generálja az embedding modell segítségével."
},
{
"question": "Milyen fájltípusokat kezel a rendszer?",
"ground_truth": "A rendszer kódfájlokat, dokumentációs fájlokat és strukturált adatfájlokat különböztet meg."
},
{
"question": "Mire szolgál a CodeParser osztály?",
"ground_truth": "A CodeParser a forráskód AST alapú elemzését végzi."
},
{
"question": "Milyen programozási nyelveket támogat a CodeParser?",
"ground_truth": "A rendszer többek között Python, C#, JavaScript, TypeScript, TSX, JSX és Java fájlokat támogat."
},
{
"question": "Mit csinál a parse_code_to_tree függvény?",
"ground_truth": "A parse_code_to_tree Tree-sitter segítségével AST-t épít a forráskódból."
},
{
"question": "Mit csinál az extract_class_function_nodes függvény?",
"ground_truth": "Kinyeri az AST-ből az osztály és függvény definíciókat."
},
{
"question": "Mit csinál az extract_graph_relations függvény?",
"ground_truth": "Kinyeri az importokat, függvényhívásokat és osztály-metódus kapcsolatokat."
},
{
"question": "Mire szolgál a NodeCreator osztály?",
"ground_truth": "A NodeCreator LlamaIndex TextNode objektumokat hoz létre a kódrészletekből."
},
{
"question": "Hogyan kezeli a NodeCreator a hosszú kódrészleteket?",
"ground_truth": "A hosszú kódrészleteket szemantikus chunkokra bontja."
},
{
"question": "Mit csinál a generate_summary_to_node függvény?",
"ground_truth": "A függvény LLM segítségével rövid összefoglalót készít egy kódrészletről."
},
{
"question": "Mi a rag_graph szerepe a rendszerben?",
"ground_truth": "A rag_graph a kérdésfeldolgozási és válaszgenerálási folyamatot vezérli."
},
{
"question": "Milyen lépésekből áll a rag_graph feldolgozási folyamata?",
"ground_truth": "A folyamat kérdésosztályozásból, átírásból, embedding generálásból, keresésből, kontextusépítésből és válaszgenerálásból áll."
},
{
"question": "Mit csinál a classify_question node?",
"ground_truth": "A kérdést különböző keresési kategóriákba sorolja."
},
{
"question": "Mi a rephrase_question feladata?",
"ground_truth": "A kérdést optimalizált keresési lekérdezéssé alakítja."
},
{
"question": "Mit csinál a search_qdrant node?",
"ground_truth": "A Qdrant adatbázisban keres a kérdés embeddingje alapján."
},
{
"question": "Mit csinál a build_context node?",
"ground_truth": "A keresési találatokból összeállítja a válaszadáshoz szükséges kontextust."
},
{
"question": "Mit csinál a generate_answer node?",
"ground_truth": "A kontextus alapján végleges választ generál."
},
{
"question": "Milyen kapcsolat van a FileService és a Neo4jService között?",
"ground_truth": "A FileService a Neo4jService metódusait használja a gráf adatainak eltárolására."
},
{
"question": "Milyen kapcsolat van a FileService és a CodeParser között?",
"ground_truth": "A FileService a CodeParser segítségével elemzi a forráskódot."
},
{
"question": "Milyen kapcsolat van a FileService és a NodeCreator között?",
"ground_truth": "A FileService a NodeCreator segítségével hoz létre node-okat és összefoglalókat."
},
{
"question": "Mely komponensek vesznek részt egy kódfájl feldolgozásában?",
"ground_truth": "A folyamatban a FileService, CodeParser, NodeCreator és Neo4jService vesz részt."
},
{
"question": "Hogyan kerülnek az osztályok a Neo4j adatbázisba?",
"ground_truth": "A CodeParser kinyeri az osztályokat, majd a FileService a Neo4jService segítségével eltárolja őket."
},
{
"question": "Hogyan épülnek fel a függvényhívási kapcsolatok a Neo4j-ben?",
"ground_truth": "A rendszer a kódból kinyert függvényhívások alapján CALLS kapcsolatokat hoz létre a gráfban."
}
]



def initial_state(question: str, ground_truth: str):
    return {
        "user_id": 1,
        "investigation_id": 1002,
        "project_id": 2002,

        "question": question,
        "rephrased_question": "",
        "ground_truth": ground_truth,

        "question_type": "",
        "search_vectors": [],

        "vector": [],

        "results": [],
        "top_results": [],
        "graph_context": [],
        "retrieved_contexts": [],

        "context": "",
        "answer": "",

        "use_graph": False,
        "needs_rerank": False,

        "retrieved_count": 0,
        "retrieval_time_ms": 0,
        "generation_time_ms": 0,
        "total_time_ms": 0,

        "ragas_run_id": "langgraph_v1"
    }


async def main():
    rows = []

    for item in TEST_QUESTIONS:
        print("Futtatás:", item["question"])

        result = await rag_graph.ainvoke(
            initial_state(item["question"], item["ground_truth"])
        )

        rows.append({
            "question": result.get("question", ""),
            "ground_truth": result.get("ground_truth", ""),
            "answer": result.get("answer", ""),
            "contexts": json.dumps(result.get("retrieved_contexts", []), ensure_ascii=False),
            "retrieved_count": result.get("retrieved_count", 0),
            "retrieval_time_ms": result.get("retrieval_time_ms", 0),
            "generation_time_ms": result.get("generation_time_ms", 0),
            "total_time_ms": result.get("total_time_ms", 0),
        })

    with open("rag_eval_export.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "question",
                "ground_truth",
                "answer",
                "contexts",
                "retrieved_count",
                "retrieval_time_ms",
                "generation_time_ms",
                "total_time_ms",
            ]
        )
        writer.writeheader()
        writer.writerows(rows)

    print("Kész: rag_eval_export.csv")


if __name__ == "__main__":
    asyncio.run(main())