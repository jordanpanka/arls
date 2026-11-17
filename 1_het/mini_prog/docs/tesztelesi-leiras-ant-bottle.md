# Kiértékelés futtatása az Apache Ant és a Bottle benchmarkon

Ez a leírás a JUnit 4-es kiértékeléssel azonos módszertannal futtatja le a 40 kérdéses Ant és Bottle
benchmarkot, így a három repó eredményei összehasonlíthatók.

| | Apache Ant | Bottle |
|---|---|---|
| Benchmark | `AI/eval/benchmarks/ant/benchmark.json` | `AI/eval/benchmarks/bottle/benchmark.json` |
| Nyelv | Java | Python |
| Rögzített verzió | `master` (2026-10-07, a `rel/1.10.15` utáni 1.10.x ág) | `master` (0.14-dev) |
| Commit SHA | `dbb01a2d528568b1d7ba0c2d84e533577f7f0876` | `aba0c1a7ee59ed851db001d100b6a792b54a94a3` |
| Indexelhető fájlok | 1937 (a 2000-es importkorlát alatt) | 57 |
| CodeMind projekt | `ApacheAnt`, `projectId` 1005 | `Bottle`, `projectId` 1003 |
| Kérdések | 40 (8 kategória × 5) | 40 (8 kategória × 5) |
| Referencia válasz nélkül | ant-36 … ant-39 | bottle-36 … bottle-39 |

A gold bizonyítékokat a `validate-gold` mindkét benchmarknál ellenőrizte a rögzített commiton
(Ant: 147, Bottle: 191 bizonyíték, hiba nélkül). A referencia válaszok továbbra is vázlatok
(`draft`), a dolgozatban ezt jelezni kell.

## 0. Előfeltételek

- Minden konténer fut (`docker compose ps`).
- Van Ollama-felhőkeret (Pro előfizetés). Egy teljes kísérlet kb. annyi tokent használ, mint a JUnit 4-es.
- Az AI-konténer a legfrissebb kóddal fut. Kódváltozás után:
  ```powershell
  docker compose up -d --build ai
  ```

## 1. Repók importálása (kész)

Mindkét repó be van importálva a `Kiértékelés` investigationbe (`investigationId` 1003, `userId` 2), és a
kódmetrika-elemzés is lefutott rajtuk. Az importált commitok nem a kiadási tagek, hanem a `master` akkori
állapota; a benchmarkok erre a két commitra vannak rögzítve, a gold bizonyítékok ezeken ellenőrizve.

Az Ant importja 16 sikertelen kísérlet után sikerült. A félbemaradt kísérletek 1784 duplikált kódrészletet
hagytak a vektoradatbázisban (egy függvény akár 16 példányban), ezek törölve lettek; minden kódrészletből
az a példány maradt meg, amelyik egyezik a commit forráskódjával. A Neo4j-gráfot és a metrikákat ez nem
érintette.

Ha újra kellene importálni: a referencia mezőbe a teljes commit SHA-t kell írni (üresen hagyva a `HEAD`
kerül be), és utána újra le kell futtatni a kódmetrika-elemzést.

## 2. Azonosítók

| | `--user-id` | `--investigation-id` | `--project-id` |
|---|---|---|---|
| Apache Ant | 2 | 1003 | 1005 |
| Bottle | 2 | 1003 | 1003 |
| (JUnit 4) | 2 | 1003 | 1004 |

## 3. Futtatás

A parancsokat PowerShellben, a `mini_prog` mappából futtasd, **egy ablakban**, hogy a `$sha` és a `$dirty`
változó mindegyik parancsnál be legyen állítva. A két repót **egymás után** futtasd, ne párhuzamosan:
a párhuzamos futás torzítja a válaszidőket, és az Ollama-keret egyszerre csak 3 kérést szolgál ki.

```powershell
$sha = git rev-parse HEAD
$dirty = if (git status --porcelain) { "true" } else { "false" }
```

### 3.1 Fő kísérlet (5 stratégia × metrikával/nélküle × 3 ismétlés = 1080 futás repónként)


```powershell
docker compose exec -e CODEMIND_COMMIT=$sha -e CODEMIND_DIRTY=$dirty ai python -m codemind_eval run --benchmark eval/benchmarks/ant/benchmark.json --experiment-id ant-main --user-id 2 --investigation-id 1003 --project-id 1005 --repetitions 3 --metrics-variants default,off --shuffle-seed 42
```

```powershell
docker compose exec -e CODEMIND_COMMIT=$sha -e CODEMIND_DIRTY=$dirty ai python -m codemind_eval run --benchmark eval/benchmarks/bottle/benchmark.json --experiment-id bottle-main --user-id 2 --investigation-id 1003 --project-id 1003 --repetitions 3 --metrics-variants default,off --shuffle-seed 42
```

Egy kísérlet kb. 4–6 óra. Ha megszakad (hiba, kvóta, Ctrl+C), **ugyanazt a parancsot kell újra
elindítani**: a sikeres futásokat kihagyja, a hibásakat újra próbálja. Ha a felhőhívás közben hiba történik,
a futás `error` állapotú lesz, és nem kerül be hamis eredményként.

### 3.2 Opcionális: ágens alapkeresés nélkül (120 futás repónként)

Csak akkor kell, ha az alapkeresés hatását több repón is meg akarod mutatni.

```powershell
docker compose exec -e CODEMIND_COMMIT=$sha -e CODEMIND_DIRTY=$dirty ai python -m codemind_eval run --benchmark eval/benchmarks/ant/benchmark.json --experiment-id ant-noseed --user-id 2 --investigation-id 1003 --project-id 1005 --strategies evidence_aware_agentic_rag --ablation no_seed --repetitions 3 --shuffle-seed 42
```

A Bottle-nál ugyanez `bottle`-lel és `bottle-noseed` azonosítóval.

## 4. LLM-bíráló (judge)

**Ugyanazt a judge-modellt kell használni, mint a JUnit 4-nél**, különben a repók nem hasonlíthatók össze.

```powershell
docker compose exec -e JUDGE_MODEL=deepseek-v4-pro:0813 ai python -m codemind_eval judge --benchmark eval/benchmarks/ant/benchmark.json --experiment-id ant-main
docker compose exec -e JUDGE_MODEL=deepseek-v4-pro:0813 ai python -m codemind_eval judge --benchmark eval/benchmarks/bottle/benchmark.json --experiment-id bottle-main
```

Ha a kimenetben sorozatban `judge_error` jelenik meg, állítsd le (Ctrl+C), mert valószínűleg elfogyott a
keret. Újraindításkor csak a hiányzó értékeléseket pótolja.

## 5. Pontozás és ábrák

Ezek a gépen, az `AI` mappában, a helyi virtuális környezettel futnak (a konténerben nincs matplotlib):

```powershell
cd AI
.venv\Scripts\python.exe -m codemind_eval score --benchmark eval/benchmarks/ant/benchmark.json --experiment-id ant-main
.venv\Scripts\python.exe -m codemind_eval report --experiment-id ant-main
.venv\Scripts\python.exe -m codemind_eval score --benchmark eval/benchmarks/bottle/benchmark.json --experiment-id bottle-main
.venv\Scripts\python.exe -m codemind_eval report --experiment-id bottle-main
```

Az eredmények helye: `AI/eval/results/<kísérlet>/`
- `figures/`: az ábrák (magyar feliratokkal),
- `scores/summary_by_strategy.csv`: stratégiánkénti átlagok és konfidenciaintervallumok,
- `scores/summary_by_category.csv`: kategóriánkénti eredmények,
- `scores/routing_summary.json`: az adaptív választás és az oracle összevetése,
- `scores/ablation.csv`: a kódmetrikák hatása.

## 6. Ellenőrzés a futás után

- `scores/status_counts.csv`: minden futás `ok` legyen, és `snapshotMatches` igaz. Ha nem egyezik a
  snapshot, a projektbe más commit lett importálva, mint ami a benchmarkban szerepel.
- `judgements.jsonl`: 1080 sikeres értékelés kísérletenként.

## 7. Amire az értelmezésnél figyelni kell

- **Bottle:** a teljes keretrendszer egyetlen `bottle.py` fájl, ezért a fájlszintű recall szinte mindig 1.
  Itt a **szimbólumszintű** metrikák (`ctx_symbol_recall@5`, `ctx_symbol_mrr`) mondanak valamit.
- **Ant:** jóval nagyobb repó (926 éles Java-fájl), a fájlszintű metrikák itt különböztetnek a legjobban.
- **A `code_quality` kérdések** közül négyhez nincs referencia válasz, mert ezekhez mért rangsor kellene. Ezeknél
  nincs helyesség- és teljességpontszám, csak megalapozottság és visszakeresés.
- **bottle-39** a változtatási előzményekre kérdez, de a zipball-import nem tartalmaz commit-történetet.
  Ez a kérdés azt méri, hogy a rendszer jelzi-e a hiányzó bizonyítékot.
- A három repó eredményét az elemzés jelenleg kísérletenként, külön számolja. Összevont (három repóra
  közös) táblázathoz és ábrához külön lépés kell.
