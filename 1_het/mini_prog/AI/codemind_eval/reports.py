import json
from pathlib import Path

from codemind_eval.scoring import read_csv
from codemind_eval.stats import is_number

DPI = 300
STRATEGY_ORDER = ["vector_rag", "selective_rag", "hybrid_rag", "evidence_aware_agentic_rag", "adaptive_rag", "agentic_rag"]
STRATEGY_COLORS = {
    "vector_rag": "#2a78d6",
    "selective_rag": "#eb6834",
    "hybrid_rag": "#1baf7a",
    "evidence_aware_agentic_rag": "#eda100",
    "adaptive_rag": "#e87ba4",
    "agentic_rag": "#008300",
}
STRATEGY_LABELS = {
    "vector_rag": "Vektoros",
    "selective_rag": "Szelektív",
    "hybrid_rag": "Hibrid",
    "evidence_aware_agentic_rag": "Bizonyítékalapú ágens",
    "adaptive_rag": "Adaptív",
    "agentic_rag": "Ágens (egyszerű)",
}
CATEGORY_LABELS = {
    "architecture": "architektúra",
    "call_flow": "hívási lánc",
    "change_impact": "változáshatás",
    "code_quality": "kódminőség",
    "comprehension": "kódmegértés",
    "dependency": "függőség",
    "design_pattern": "tervezési minta",
    "multi_source": "több forrás",
}
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#fcfcfb"
NEUTRAL = "#898781"

RETRIEVAL_METRICS = [
    ("ctx_file_recall@5", "Recall@5"), ("ctx_file_recall@10", "Recall@10"),
    ("ctx_file_precision@5", "Precision@5"), ("ctx_file_precision@10", "Precision@10"),
    ("ctx_file_mrr", "MRR"), ("ctx_file_coverage", "Fájllefedettség"), ("ctx_symbol_coverage", "Szimbólumlefedettség"),
]
ANSWER_METRICS = [
    ("judge_correctness_norm", "Helyesség (0–3, skálázva)"), ("judge_completeness", "Teljesség"),
    ("judge_faithfulness", "Hűség a bizonyítékokhoz"), ("judge_citation_correctness", "Hivatkozások helyessége"),
]
COMPOSITE_METRICS = [
    ("composite_answer", "Válaszminőség"), ("composite_grounding", "Megalapozottság"),
    ("composite_retrieval", "Visszakeresés"), ("composite_score", "Összetett pontszám"),
]
IMPACT_METRICS = [("impact_cited_precision", "Precision"), ("impact_cited_recall", "Recall"), ("impact_cited_f1", "F1")]
REPOSITORY_METRICS = [("judge_correctness_norm", "Helyesség (skálázva)"), ("ctx_file_recall@5", "Recall@5 (fájl)"),
                      ("composite_score", "Összetett pontszám")]
REPOSITORY_LABELS = {"junit4": "JUnit 4", "ant": "Apache Ant", "bottle": "Bottle"}
ABLATION_METRICS = [("ctx_file_recall@5", "Recall@5 (fájl)"), ("judge_correctness_norm", "Helyesség (skálázva)"),
                    ("composite_score", "Összetett pontszám"), ("totalTokens", "Összes token"),
                    ("latencyTotalMs", "Válaszidő (ms)")]


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"],
        "font.size": 9,
        "axes.edgecolor": AXIS,
        "axes.labelcolor": INK_SECONDARY,
        "axes.titlecolor": INK,
        "axes.titlesize": 11,
        "axes.titleweight": "semibold",
        "axes.facecolor": SURFACE,
        "figure.facecolor": SURFACE,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelcolor": INK_SECONDARY,
        "ytick.labelcolor": INK_SECONDARY,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "legend.frameon": False,
        "legend.labelcolor": INK_SECONDARY,
        "savefig.dpi": DPI,
        "savefig.bbox": "tight",
    })
    return plt


def _ordered(strategies) -> list[str]:
    present = list(dict.fromkeys(strategies))
    return [s for s in STRATEGY_ORDER if s in present] + sorted(s for s in present if s not in STRATEGY_ORDER)


def _label(strategy: str) -> str:
    return STRATEGY_LABELS.get(strategy, strategy)


def _wrapped(label: str) -> str:
    if len(label) <= 12:
        return label
    if " " not in label and label.endswith("lefedettség"):
        return label.removesuffix("lefedettség") + "-\nlefedettség"
    return label.replace(" ", "\n", 1)


def _color(strategy: str) -> str:
    return STRATEGY_COLORS.get(strategy, NEUTRAL)


def _summary_lookup(summary: list[dict], metrics_variant: str = "default") -> dict[tuple[str, str], dict]:
    return {(r["strategy"], r["metric"]): r for r in summary
            if r.get("metrics") == metrics_variant and is_number(r.get("mean"))}


def _note(fig, text: str) -> None:
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    boxes = [ax.get_tightbbox(renderer).transformed(fig.transFigure.inverted()) for ax in fig.axes]
    left = min(b.x0 for b in boxes)
    bottom = min(b.y0 for b in boxes)
    fig.text(max(left, 0.0), bottom - 0.03, text, ha="left", va="top", fontsize=7.5, color=MUTED)


def _side_legend(ax) -> None:
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=8, borderaxespad=0)


def grouped_bars(path: Path, summary: list[dict], metrics: list[tuple[str, str]], ylabel: str,
                 note: str, ylim: tuple[float, float] | None = (0, 1.05)) -> Path | None:
    lookup = _summary_lookup(summary)
    metrics = [(key, label) for key, label in metrics if any(k == key for _, k in lookup)]
    strategies = _ordered(s for s, _ in lookup)
    if not metrics or not strategies:
        return None
    import textwrap
    plt = _plt()
    fig_width, fig_height = 0.98 * len(metrics) + 3.68, 3.6
    note = textwrap.fill(note, width=int(fig_width * 15.5))
    note_height = (note.count("\n") + 1) * 9.5 * 1.3 / 72 + 0.1
    fig, ax = plt.subplots(figsize=(fig_width, fig_height), layout="constrained")
    fig.get_layout_engine().set(rect=(0, note_height / fig_height, 1, 1 - note_height / fig_height))
    width = 0.8 / len(strategies)
    for i, strategy in enumerate(strategies):
        xs, ys, low, high = [], [], [], []
        for j, (key, _) in enumerate(metrics):
            row = lookup.get((strategy, key))
            if row is None:
                continue
            x = j - 0.4 + width * (i + 0.5)
            xs.append(x)
            ys.append(row["mean"])
            low.append(max(0.0, row["mean"] - row["ci_low"]) if is_number(row.get("ci_low")) else 0)
            high.append(max(0.0, row["ci_high"] - row["mean"]) if is_number(row.get("ci_high")) else 0)
        ax.bar(xs, ys, width=width * 0.86, color=_color(strategy), label=_label(strategy), zorder=2,
               edgecolor=SURFACE, linewidth=0.8)
        ax.errorbar(xs, ys, yerr=[low, high], fmt="none", ecolor=INK_SECONDARY, elinewidth=0.8, capsize=1.8, zorder=3)
        for x, y in zip(xs, ys):
            if y == 0:
                ax.text(x, 0, "0", ha="center", va="bottom", fontsize=9, color=INK_SECONDARY)
    ax.set_xticks(range(len(metrics)), [_wrapped(label) for _, label in metrics])
    ax.tick_params(labelsize=11)
    ax.set_ylabel(ylabel, fontsize=11.5)
    if ylim:
        ax.set_ylim(*ylim)
    fig.legend(loc="outside right upper", fontsize=10.5)
    fig.text(0.01, 0.01, note, ha="left", va="bottom", fontsize=9.5, color=MUTED)
    fig.savefig(path, bbox_inches=fig.bbox_inches)
    plt.close(fig)
    return path


def _repository_label(experiment: str) -> str:
    return REPOSITORY_LABELS.get(experiment.split("-", 1)[0], experiment)


def repository_bars(path: Path, rows: list[dict]) -> Path | None:
    from codemind_eval.stats import summarize
    rows = [r for r in rows if r.get("metrics") == "default" and r.get("experiment")]
    order = list(REPOSITORY_LABELS)
    experiments = sorted({r["experiment"] for r in rows},
                         key=lambda e: (order.index(e.split("-", 1)[0]) if e.split("-", 1)[0] in order else len(order), e))
    if len(experiments) < 2:
        return None
    summary = summarize(rows, [key for key, _ in REPOSITORY_METRICS], ("experiment", "strategy"))
    lookup = {(r["experiment"], r["strategy"], r["metric"]): r for r in summary if is_number(r.get("mean"))}
    strategies = _ordered(r["strategy"] for r in summary)
    plt = _plt()
    fig, axes = plt.subplots(1, len(REPOSITORY_METRICS), figsize=(3.6 * len(REPOSITORY_METRICS) + 1.6, 3.8),
                             squeeze=False, sharey=True)
    width = 0.8 / len(strategies)
    for ax, (metric, label) in zip(axes[0], REPOSITORY_METRICS):
        for i, strategy in enumerate(strategies):
            xs, ys, low, high = [], [], [], []
            for j, experiment in enumerate(experiments):
                row = lookup.get((experiment, strategy, metric))
                if row is None:
                    continue
                xs.append(j - 0.4 + width * (i + 0.5))
                ys.append(row["mean"])
                low.append(max(0.0, row["mean"] - row["ci_low"]) if is_number(row.get("ci_low")) else 0)
                high.append(max(0.0, row["ci_high"] - row["mean"]) if is_number(row.get("ci_high")) else 0)
            ax.bar(xs, ys, width=width * 0.86, color=_color(strategy), label=_label(strategy), zorder=2,
                   edgecolor=SURFACE, linewidth=0.8)
            ax.errorbar(xs, ys, yerr=[low, high], fmt="none", ecolor=INK_SECONDARY, elinewidth=0.8, capsize=1.5, zorder=3)
        ax.set_xticks(range(len(experiments)), [_repository_label(e) for e in experiments])
        ax.set_ylim(0, 1.05)
        ax.set_title(label, loc="left", fontsize=9.5)
    axes[0][0].set_ylabel("Pontszám (0–1)")
    fig.tight_layout()
    _side_legend(axes[0][-1])
    _note(fig, "Kérdésenkénti átlag (az ismétlések előbb átlagolva), kódmetrikákkal futtatott változat; "
               "hibasáv = 95%-os bootstrap CI a repository kérdései felett.")
    fig.savefig(path)
    plt.close(fig)
    return path


def category_heatmap(path: Path, by_category: list[dict], metric: str, metric_label: str) -> Path | None:
    rows = [r for r in by_category if r.get("metric") == metric and r.get("metrics") == "default" and is_number(r.get("mean"))]
    if not rows:
        return None
    strategies = _ordered(r["strategy"] for r in rows)
    categories = sorted({r["category"] for r in rows})
    values = {(r["strategy"], r["category"]): r for r in rows}
    plt = _plt()
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("seq", SEQUENTIAL)
    height = 0.8 * len(strategies) + 1.72
    fig, ax = plt.subplots(figsize=(1.3 * len(categories) + 2.1, height), layout="constrained")
    fig.get_layout_engine().set(rect=(0, 0.3 / height, 1, 1 - 0.3 / height))
    grid = [[values[(s, c)]["mean"] if (s, c) in values else float("nan") for c in categories] for s in strategies]
    image = ax.imshow(grid, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for i, s in enumerate(strategies):
        for j, c in enumerate(categories):
            cell = values.get((s, c))
            if cell is None:
                ax.text(j, i, "nincs adat", ha="center", va="center", fontsize=13, color=MUTED)
                continue
            ax.text(j, i - 0.12, f"{cell['mean']:.2f}", ha="center", va="center", fontsize=17, fontweight="bold", color="#000000")
            ax.text(j, i + 0.24, f"n={cell['n_questions']}", ha="center", va="center", fontsize=12, color="#000000")
    ax.set_xticks(range(len(categories)), [CATEGORY_LABELS.get(c, c) for c in categories], rotation=30, ha="right")
    ax.set_yticks(range(len(strategies)), [_label(s) for s in strategies])
    ax.tick_params(labelsize=11.5)
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    bar = fig.colorbar(image, ax=ax, fraction=0.03, pad=0.02)
    bar.outline.set_visible(False)
    bar.ax.tick_params(colors=MUTED, labelcolor=INK_SECONDARY, labelsize=11)
    bar.set_label(metric_label, fontsize=11.5)
    fig.text(0.01, 0.01, "Kérdésenkénti átlag (az ismétlések előbb átlagolva). n = a pontozott kérdések száma.",
             ha="left", va="bottom", fontsize=9.5, color=MUTED)
    fig.savefig(path, bbox_inches=fig.bbox_inches)
    plt.close(fig)
    return path


def latency_boxplot(path: Path, rows: list[dict]) -> Path | None:
    data = {}
    for row in rows:
        if row.get("status") == "ok" and row.get("metrics") == "default" and is_number(row.get("latencyTotalMs")):
            data.setdefault(row["strategy"], []).append(row["latencyTotalMs"] / 1000)
    strategies = _ordered(data)
    if not strategies:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    parts = ax.boxplot([data[s] for s in strategies], patch_artist=True, widths=0.55, showfliers=True,
                       medianprops={"color": INK, "linewidth": 1.2},
                       whiskerprops={"color": INK_SECONDARY, "linewidth": 0.8},
                       capprops={"color": INK_SECONDARY, "linewidth": 0.8},
                       flierprops={"marker": "o", "markersize": 3, "markerfacecolor": MUTED, "markeredgecolor": "none"})
    for patch, strategy in zip(parts["boxes"], strategies):
        patch.set_facecolor(_color(strategy))
        patch.set_alpha(0.85)
        patch.set_edgecolor(SURFACE)
    ax.set_xticks(range(1, len(strategies) + 1), [_wrapped(_label(s)) for s in strategies])
    ax.set_yscale("log")
    ax.set_ylabel("Teljes válaszidő (s, logaritmikus skála)")
    _note(fig, "A kiértékelő által mért futásonkénti idő; minden futás és ismétlés egy megfigyelés.")
    fig.savefig(path)
    plt.close(fig)
    return path


def tool_heatmap(path: Path, usage: list[dict]) -> Path | None:
    rows = [r for r in usage if r.get("metrics") == "default"]
    if not rows:
        return None
    strategies = _ordered(r["strategy"] for r in rows)
    totals: dict[str, float] = {}
    for r in rows:
        totals[r["tool"]] = totals.get(r["tool"], 0) + r["calls"]
    tools = sorted(totals, key=lambda t: -totals[t])
    values = {(r["strategy"], r["tool"]): r["calls_per_run"] for r in rows}
    peak = max(values.values())
    plt = _plt()
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("seq", SEQUENTIAL)
    fig, ax = plt.subplots(figsize=(0.75 * len(tools) + 2.8, 0.55 * len(strategies) + 2.2))
    grid = [[values.get((s, t), 0.0) for t in tools] for s in strategies]
    ax.imshow(grid, cmap=cmap, vmin=0, vmax=peak, aspect="auto")
    for i, s in enumerate(strategies):
        for j, t in enumerate(tools):
            v = values.get((s, t))
            if v:
                ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=7, color="#ffffff" if v > peak * 0.55 else INK)
    ax.set_xticks(range(len(tools)), tools, rotation=40, ha="right")
    ax.set_yticks(range(len(strategies)), [_label(s) for s in strategies])
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    _note(fig, "Az egyes ágenseszközök átlagos hívásszáma sikeres futásonként. A pipeline-stratégiák nem hívnak ágenseszközt.")
    fig.savefig(path)
    plt.close(fig)
    return path


def routing_chart(path: Path, routing_rows: list[dict], summary: dict) -> Path | None:
    if not routing_rows:
        return None
    strategies = _ordered([r["routerEffective"] for r in routing_rows if r.get("routerEffective")]
                          + [r["oracle"] for r in routing_rows if r.get("oracle")])
    router = {s: sum(1 for r in routing_rows if r.get("routerEffective") == s) for s in strategies}
    oracle = {s: sum(1 for r in routing_rows if r.get("oracle") == s) for s in strategies}
    plt = _plt()
    fig, ax = plt.subplots(figsize=(6.5, 0.5 * len(strategies) + 1.8))
    ys = range(len(strategies))
    height = 0.38
    ax.barh([y - height / 2 for y in ys], [router[s] for s in strategies], height=height * 0.9,
            color="#4a3aa7", label="Router döntése (eszkaláció után)", zorder=2)
    ax.barh([y + height / 2 for y in ys], [oracle[s] for s in strategies], height=height * 0.9,
            color="#e34948", label="Utólagos oracle", zorder=2)
    for y, s in zip(ys, strategies):
        ax.text(router[s], y - height / 2, f" {router[s]}", va="center", fontsize=7.5, color=INK_SECONDARY)
        ax.text(oracle[s], y + height / 2, f" {oracle[s]}", va="center", fontsize=7.5, color=INK_SECONDARY)
    ax.set_yticks(list(ys), [_label(s) for s in strategies])
    ax.invert_yaxis()
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Kérdések száma")
    from matplotlib.ticker import MaxNLocator
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    _side_legend(ax)

    def pct(value):
        return f"{value * 100:.0f}%".replace(".", ",") if is_number(value) else "n.a."

    def num(value, fmt="{:.3f}"):
        return fmt.format(value).replace(".", ",") if is_number(value) else "n.a."

    quality = summary.get("qualityKey")
    quality_label = dict(RETRIEVAL_METRICS + ANSWER_METRICS + COMPOSITE_METRICS).get(quality, quality)
    _note(fig, (
        f"Minőségmérték: {quality_label}. Egyezés az oracle-lel {pct(summary.get('oracleAgreement'))}, "
        f"a router két lehetőségére szűkítve {pct(summary.get('restrictedOracleAgreement'))} "
        f"(±{num(summary.get('tieTolerance'), '{:.2f}')} tűréssel {pct(summary.get('toleranceOracleAgreement'))} / "
        f"{pct(summary.get('restrictedToleranceOracleAgreement'))}), "
        f"átlagos veszteség {num(summary.get('meanRegret'))}, eszkalációs arány {pct(summary.get('escalationRate'))},\n"
        f"tokenmegtakarítás a mindig ágenshez képest {pct(summary.get('tokenSavingsRelative'))}."
    ))
    fig.savefig(path)
    plt.close(fig)
    return path


COST_PANELS = [("totalTokens", "Átlagos token / futás", 1.0), ("latencyTotalMs", "Átlagos válaszidő (s)", 0.001)]
ROUTE_PATHS = [
    ("pipeline", "Szelektív pipeline", STRATEGY_COLORS["selective_rag"]),
    ("escalated", "Pipeline → eszkaláció az ágenshez", "#4a3aa7"),
    ("agent", "Közvetlenül ágens", STRATEGY_COLORS["evidence_aware_agentic_rag"]),
]


def _decimal(value: float, fmt: str = "{:.2f}") -> str:
    return fmt.format(value).replace(".", ",")


def cost_quality_chart(path: Path, summary: list[dict], quality: str, quality_label: str) -> Path | None:
    lookup = _summary_lookup(summary)
    panels = [p for p in COST_PANELS if any(k == p[0] for _, k in lookup)]
    strategies = [s for s in _ordered(s for s, _ in lookup)
                  if (s, quality) in lookup and all((s, key) in lookup for key, _, _ in panels)]
    if not panels or not strategies:
        return None

    def bounds(row, scale):
        mean = row["mean"] * scale
        low = row["ci_low"] * scale if is_number(row.get("ci_low")) else mean
        high = row["ci_high"] * scale if is_number(row.get("ci_high")) else mean
        return mean, max(0.0, mean - low), max(0.0, high - mean)

    plt = _plt()
    fig, axes = plt.subplots(1, len(panels), figsize=(4.2 * len(panels) + 1.6, 3.8), squeeze=False, sharey=True)
    for ax, (key, label, scale) in zip(axes[0], panels):
        for strategy in strategies:
            x, x_low, x_high = bounds(lookup[(strategy, key)], scale)
            y, y_low, y_high = bounds(lookup[(strategy, quality)], 1.0)
            ax.errorbar([x], [y], xerr=[[x_low], [x_high]], yerr=[[y_low], [y_high]], fmt="none",
                        ecolor=_color(strategy), elinewidth=0.9, alpha=0.55, capsize=0, zorder=2)
            ax.scatter([x], [y], s=70 if strategy == "adaptive_rag" else 46, color=_color(strategy),
                       edgecolor=INK if strategy == "adaptive_rag" else SURFACE, linewidth=1.2, zorder=3,
                       label=_label(strategy))
        ax.grid(axis="x")
        ax.set_xlabel(label)
        ax.set_xlim(left=0)
        ax.xaxis.set_major_formatter(lambda v, _: f"{v:,.0f}".replace(",", " "))
    axes[0][0].set_ylabel(quality_label)
    fig.tight_layout()
    _side_legend(axes[0][-1])
    note = "Pont = kérdésenkénti átlag (az ismétlések előbb átlagolva); vonalak = 95%-os bootstrap CI mindkét tengelyen."
    adaptive, agent = "adaptive_rag", "evidence_aware_agentic_rag"
    if adaptive in strategies and agent in strategies:
        parts = []
        for key, label, _ in panels:
            saving = 1 - lookup[(adaptive, key)]["mean"] / lookup[(agent, key)]["mean"]
            parts.append(f"{'token' if key == 'totalTokens' else 'idő'} −{saving * 100:.0f}%")
        diff = lookup[(adaptive, quality)]["mean"] - lookup[(agent, quality)]["mean"]
        note += (f"\nAz adaptív stratégia a bizonyítékalapú ágenshez képest: {', '.join(parts)}, "
                 f"minőségkülönbség {'+' if diff >= 0 else '−'}{_decimal(abs(diff), '{:.3f}')}.")
    _note(fig, note)
    fig.savefig(path)
    plt.close(fig)
    return path


def _route_path(row: dict) -> str:
    if is_number(row.get("escalationRate")) and row["escalationRate"] > 0:
        return "escalated"
    return "agent" if row.get("routerSelected") == "evidence_aware_agentic_rag" else "pipeline"


def savings_tradeoff_chart(path: Path, rows: list[dict], routing_rows: list[dict], quality: str,
                           quality_label: str) -> Path | None:
    adaptive, agent = "adaptive_rag", "evidence_aware_agentic_rag"
    sums: dict[tuple[str, str], list[list[float]]] = {}
    for row in rows:
        if (row.get("status") != "ok" or row.get("metrics") != "default" or row.get("strategy") not in (adaptive, agent)
                or not is_number(row.get(quality)) or not is_number(row.get("totalTokens"))):
            continue
        sums.setdefault((row["questionId"], row["strategy"]), []).append([row[quality], row["totalTokens"]])
    means = {k: [sum(c) / len(v) for c in zip(*v)] for k, v in sums.items()}
    paths = {r["questionId"]: _route_path(r) for r in routing_rows}
    points = []
    for question in sorted({q for q, _ in means}):
        if (question, adaptive) not in means or (question, agent) not in means or means[(question, agent)][1] <= 0:
            continue
        a_quality, a_tokens = means[(question, adaptive)]
        b_quality, b_tokens = means[(question, agent)]
        points.append((100 * (1 - a_tokens / b_tokens), a_quality - b_quality, paths.get(question, "pipeline")))
    if not points:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(2588 / DPI, 1316 / DPI))
    fig.subplots_adjust(left=0.105, right=0.985, top=0.97, bottom=0.25)
    ax.axhline(0, color=AXIS, linewidth=1, zorder=1)
    ax.axvline(0, color=AXIS, linewidth=1, zorder=1)
    for key, label, color in ROUTE_PATHS:
        chosen = [p for p in points if p[2] == key]
        if chosen:
            ax.scatter([p[0] for p in chosen], [p[1] for p in chosen], s=40, color=color, alpha=0.8,
                       edgecolor=SURFACE, linewidth=0.8, zorder=3, label=f"{label} (n={len(chosen)})")
    ax.grid(axis="x")
    ax.tick_params(labelsize=11)
    ax.set_xlabel("Tokenmegtakarítás a bizonyítékalapú ágenshez képest (%)", fontsize=12)
    ax.set_ylabel(f"Minőségkülönbség: adaptív − ágens\n({quality_label})", fontsize=12)
    ax.legend(loc="upper left", fontsize=11, frameon=True, facecolor=SURFACE, edgecolor=GRID, framealpha=0.95)
    saved = [p for p in points if p[0] > 0]
    worse = [p for p in points if p[1] < 0]
    fig.text(0.01, 0.02, (
        f"Egy pont = egy kérdés (az ismétlések átlagolva). {len(points)} kérdésből {len(saved)} esetben kevesebb token, "
        f"{len(worse)} esetben rosszabb minőség,\n{sum(1 for p in saved if p[1] >= 0)} esetben megtakarítás "
        f"minőségvesztés nélkül. A szín a router útvonala (eszkaláció = legalább egy ismétlésben)."
    ), ha="left", va="bottom", fontsize=10, color=MUTED)
    fig.savefig(path, bbox_inches=fig.bbox_inches)
    plt.close(fig)
    return path


POLICY_STYLES = [
    ("selective", "Mindig szelektív", STRATEGY_COLORS["selective_rag"], "o"),
    ("agent", "Mindig ágens", STRATEGY_COLORS["evidence_aware_agentic_rag"], "o"),
    ("random", "Véletlen választás (50–50%)", NEUTRAL, "o"),
    ("adaptive", "Adaptív router", STRATEGY_COLORS["adaptive_rag"], "o"),
    ("restricted_oracle", "Oracle (szelektív vagy ágens)", INK, "D"),
    ("oracle", "Oracle (bármely rögzített stratégia)", INK, "s"),
]
DECISION_OUTCOMES = [
    ("good", "Jó döntés", "#0ca30c"),
    ("wasted", "Azonos minőség, felesleges ágens", "#fab219"),
    ("loss", "Minőségvesztés", "#d03b3b"),
]


def _router_table(rows: list[dict], quality: str) -> dict[str, dict[str, dict]]:
    from codemind_eval.routing import ADAPTIVE, ROUTER_CHOICES, per_question_strategy
    table = per_question_strategy(rows, quality)
    needed = (*ROUTER_CHOICES, ADAPTIVE)
    return {q: r for q, r in table.items()
            if all(s in r and r[s]["quality"] is not None and r[s]["tokens"] is not None for s in needed)}


def routing_policies_chart(path: Path, rows: list[dict], quality: str, quality_label: str) -> Path | None:
    from codemind_eval.routing import ADAPTIVE, FIXED, ROUTER_CHOICES, oracle
    table = _router_table(rows, quality)
    if not table:
        return None
    selective, agent = ROUTER_CHOICES
    points: dict[str, list[tuple[float, float]]] = {key: [] for key, *_ in POLICY_STYLES}
    for results in table.values():
        points["selective"].append((results[selective]["tokens"], results[selective]["quality"]))
        points["agent"].append((results[agent]["tokens"], results[agent]["quality"]))
        points["random"].append(((results[selective]["tokens"] + results[agent]["tokens"]) / 2,
                                 (results[selective]["quality"] + results[agent]["quality"]) / 2))
        points["adaptive"].append((results[ADAPTIVE]["tokens"], results[ADAPTIVE]["quality"]))
        r_pick, _, r_best = oracle(results, ROUTER_CHOICES)
        points["restricted_oracle"].append((results[r_pick]["tokens"], r_best))
        pick, _, best = oracle(results, tuple(s for s in FIXED if s in results))
        if results[pick]["tokens"] is not None:
            points["oracle"].append((results[pick]["tokens"], best))
    means = {key: (sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v)) for key, v in points.items() if v}

    plt = _plt()
    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    for key, label, color, marker in POLICY_STYLES:
        if key not in means:
            continue
        x, y = means[key]
        hollow = key.endswith("oracle")
        ax.scatter([x], [y], s=80 if key == "adaptive" else 60, marker=marker,
                   color=SURFACE if hollow else color, edgecolor=color if hollow else SURFACE,
                   linewidth=1.6 if hollow else 1.2, zorder=3, label=label)
        ax.annotate(_decimal(y, "{:.3f}"), (x, y), xytext=(7, -3), textcoords="offset points",
                    fontsize=7.5, color=INK_SECONDARY)
    ax.grid(axis="x")
    ax.set_xlim(left=0)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:,.0f}".replace(",", " "))
    ax.set_xlabel("Átlagos token / kérdés")
    ax.set_ylabel(quality_label)
    _side_legend(ax)
    note = (f"Pont = átlag {len(table)} kérdésen; a rögzített politikák és az oracle a fix stratégiák futásaiból számolva, "
            f"az adaptív a saját futásaiból.\nAz oracle utólag, a pontszámok ismeretében választ, ezért felső becslés.")
    if all(k in means for k in ("selective", "adaptive", "restricted_oracle")):
        gap = means["restricted_oracle"][1] - means["selective"][1]
        if gap > 0:
            closed = (means["adaptive"][1] - means["selective"][1]) / gap
            note += (f" Az adaptív router a mindig szelektív és a kétágú oracle közti minőségrés "
                     f"{closed * 100:.0f}%-át zárja be.")
    _note(fig, note)
    fig.savefig(path)
    plt.close(fig)
    return path


def _decision_outcome(results: dict[str, dict], tolerance: float) -> tuple[str, str, str] | None:
    from codemind_eval.routing import ADAPTIVE, ROUTER_CHOICES, better_choice
    choice = results[ADAPTIVE]["effective"]
    if choice not in ROUTER_CHOICES:
        return None
    better = better_choice(results, tolerance)
    return choice, better, _decision_outcome_for(choice, better)


def routing_decision_chart(path: Path, rows: list[dict], quality: str, quality_label: str) -> Path | None:
    from matplotlib.patches import Rectangle
    from codemind_eval.routing import ROUTER_CHOICES, TIE_TOLERANCE
    table = _router_table(rows, quality)
    categories = {r["questionId"]: r.get("category") for r in rows if r.get("category")}
    decisions = {q: d for q, results in table.items() if (d := _decision_outcome(results, TIE_TOLERANCE))}
    if not decisions:
        return None
    colors = {key: color for key, _, color in DECISION_OUTCOMES}
    labels = {key: label for key, label, _ in DECISION_OUTCOMES}
    columns = [("selective", "A szelektív\nvolt jobb"), ("tie", f"Holtverseny\n(±{_decimal(TIE_TOLERANCE)})"),
               ("agent", "Az ágens\nvolt jobb")]

    plt = _plt()
    fig, (left, right) = plt.subplots(1, 2, figsize=(3103 / DPI, 1185 / DPI),
                                      gridspec_kw={"width_ratios": [1.15, 1.35]})
    for row_index, choice in enumerate(ROUTER_CHOICES):
        for col_index, (better, _) in enumerate(columns):
            outcome = _decision_outcome_for(choice, better)
            count = sum(1 for c, b, _ in decisions.values() if c == choice and b == better)
            left.add_patch(Rectangle((col_index + 0.03, row_index + 0.03), 0.94, 0.94, facecolor=colors[outcome],
                                     alpha=0.22 if count else 0.07, edgecolor=SURFACE, linewidth=2))
            left.text(col_index + 0.5, row_index + 0.5, str(count), ha="center", va="center", fontsize=16,
                      fontweight="semibold", color=INK if count else MUTED)
    left.set_xlim(0, len(columns))
    left.set_ylim(len(ROUTER_CHOICES), 0)
    left.set_xticks([i + 0.5 for i in range(len(columns))], [label for _, label in columns])
    left.set_yticks([i + 0.5 for i in range(len(ROUTER_CHOICES))],
                    [f"A router:\n{_label(s).lower()}" for s in ROUTER_CHOICES])
    left.tick_params(length=0, labelsize=11)
    left.grid(False)
    for spine in left.spines.values():
        spine.set_visible(False)
    left.xaxis.tick_top()

    order = [c for c in CATEGORY_LABELS if any(categories.get(q) == c for q in decisions)]
    for y, category in enumerate(order):
        items = [d[2] for q, d in decisions.items() if categories.get(q) == category]
        start = 0.0
        for key, _, color in DECISION_OUTCOMES:
            share = sum(1 for o in items if o == key) / len(items)
            if share:
                right.barh(y, share, left=start, height=0.62, color=color, edgecolor=SURFACE, linewidth=2, zorder=2)
                start += share
        right.text(1.01, y, f"n={len(items)}", va="center", fontsize=10, color=INK_SECONDARY)
    right.set_yticks(range(len(order)), [CATEGORY_LABELS[c] for c in order])
    right.tick_params(labelsize=11)
    right.invert_yaxis()
    right.set_xlim(0, 1)
    right.xaxis.set_major_formatter(lambda v, _: f"{v * 100:.0f}%")
    right.grid(axis="x")
    right.grid(axis="y", visible=False)
    right.set_xlabel("A kérdések aránya", fontsize=11.5)
    handles = [Rectangle((0, 0), 1, 1, color=color) for _, _, color in DECISION_OUTCOMES]
    fig.legend(handles, [label for _, label, _ in DECISION_OUTCOMES], loc="lower center",
               bbox_to_anchor=(0.5, 0.14), ncol=len(DECISION_OUTCOMES), fontsize=10.5, borderaxespad=0,
               handlelength=1.5, columnspacing=1.8)
    left.set_position([0.16, 0.29, 0.27, 0.5])
    right.set_position([0.59, 0.36, 0.36, 0.61])
    totals = {key: sum(1 for d in decisions.values() if d[2] == key) for key, _, _ in DECISION_OUTCOMES}
    n = len(decisions)
    fig.text(0.01, 0.015, (
        f"Minőségmérték: {quality_label}; egy cella = kérdések száma ({n} kérdés). "
        f"Holtversenyben a szelektív választás a jó, mert ugyanazt a minőséget olcsóbban adja.\n"
        f"A döntést a szelektív és az ágens saját futásainak kérdésenkénti átlagához mérjük; "
        f"±{_decimal(TIE_TOLERANCE)}-n belül holtverseny.\n"
        + ", ".join(f"{labels[k]}: {totals[k]} ({totals[k] / n * 100:.0f}%)" for k, _, _ in DECISION_OUTCOMES) + "."
    ), ha="left", va="bottom", fontsize=9, color=MUTED)
    fig.savefig(path, bbox_inches=fig.bbox_inches)
    plt.close(fig)
    return path


def _decision_outcome_for(choice: str, better: str) -> str:
    if choice == "selective_rag":
        return "loss" if better == "agent" else "good"
    return "loss" if better == "selective" else "wasted" if better == "tie" else "good"


TDK_DARK = "#080E59"
TDK_MID = "#445591"
TDK_LIGHT = "#809BCB"
TDK_PALE = "#B2C5E7"
TDK_SURFACE = "#FFFFFF"
TDK_MIN_EVALUATED = 10
TDK_TOLERANCES = (0.0, 0.12, 0.34)
CATEGORY_ORDER = ["comprehension", "call_flow", "dependency", "design_pattern", "multi_source", "architecture",
                  "change_impact", "code_quality"]


def _tdk_plt():
    plt = _plt()
    plt.rcParams.update({
        "font.size": 14,
        "axes.facecolor": TDK_SURFACE,
        "figure.facecolor": TDK_SURFACE,
        "axes.edgecolor": TDK_PALE,
        "axes.labelcolor": TDK_DARK,
        "axes.titlecolor": TDK_DARK,
        "axes.titlesize": 20,
        "axes.titleweight": "bold",
        "xtick.labelcolor": TDK_DARK,
        "ytick.labelcolor": TDK_DARK,
        "xtick.color": TDK_PALE,
        "ytick.color": TDK_PALE,
        "grid.color": "#E6ECF6",
        "legend.labelcolor": TDK_DARK,
    })
    return plt


def _tdk_save(fig, path: Path) -> Path:
    fig.savefig(path.with_suffix(".png"), dpi=DPI, facecolor=TDK_SURFACE)
    fig.savefig(path.with_suffix(".svg"), facecolor=TDK_SURFACE)
    return path.with_suffix(".png")


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _category_order(categories) -> list[str]:
    present = set(categories)
    return [c for c in CATEGORY_ORDER if c in present] + sorted(present - set(CATEGORY_ORDER))


def routing_accuracy_donut(path: Path, overall: dict) -> Path | None:
    n = overall["evaluated"]
    if not n:
        return None
    correct = overall["effectiveCorrect"]
    plt = _tdk_plt()
    fig, ax = plt.subplots(figsize=(7.5, 7.0))
    ax.pie([correct, n - correct], colors=[TDK_DARK, TDK_LIGHT], startangle=90, counterclock=False,
           wedgeprops={"width": 0.32, "edgecolor": TDK_SURFACE, "linewidth": 3})
    ax.text(0, 0.1, _pct(correct / n), ha="center", va="center", fontsize=54, fontweight="bold", color=TDK_DARK)
    ax.text(0, -0.2, "helyes döntés", ha="center", va="center", fontsize=17, color=TDK_MID)
    ax.set_title("Az adaptív stratégiaválasztás helyessége", pad=18)
    ax.legend([f"Helyes útválasztás ({correct})", f"Nem optimális döntés ({n - correct})"],
              loc="upper center", bbox_to_anchor=(0.5, 0.02), ncol=2, fontsize=14, handlelength=1.2, frameon=False)
    fig.text(0.5, 0.035, f"n = {n} értékelt kérdés ({overall['notEvaluated']} kérdés referenciaválasz híján kimaradt)\n"
                         "végső útvonal, az eszkalációval együtt", ha="center", fontsize=13, color=TDK_MID,
             linespacing=1.5)
    fig.subplots_adjust(top=0.9, bottom=0.17)
    path = _tdk_save(fig, path)
    plt.close(fig)
    return path


def routing_decisions_by_category(path: Path, by_category: list[dict]) -> Path | None:
    from matplotlib.patches import Rectangle
    if not by_category:
        return None
    lookup = {r["value"]: r for r in by_category}
    order = _category_order(lookup)
    plt = _tdk_plt()
    fig, ax = plt.subplots(figsize=(12, 7.2))
    for y, category in enumerate(order):
        row = lookup[category]
        total = row["selectedSelective"] + row["selectedAgent"]
        start = 0.0
        for count, color, ink in ((row["selectedSelective"], TDK_LIGHT, TDK_DARK), (row["selectedAgent"], TDK_DARK, TDK_SURFACE)):
            share = count / total
            if share:
                ax.barh(y, share, left=start, height=0.66, color=color, edgecolor=TDK_SURFACE, linewidth=2, zorder=2)
                if share >= 0.1:
                    ax.text(start + share / 2, y, _pct(share), ha="center", va="center", fontsize=14,
                            fontweight="bold", color=ink, zorder=3)
            start += share
        ax.text(1.015, y, f"n = {total}", va="center", fontsize=13, color=TDK_MID)
    ax.set_yticks(range(len(order)), [CATEGORY_LABELS.get(c, c) for c in order], fontsize=15)
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1])
    ax.xaxis.set_major_formatter(lambda v, _: f"{v * 100:.0f}%")
    ax.grid(axis="x", zorder=0)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("Választási arány (%)", fontsize=15)
    ax.set_title("Az adaptív router döntései kérdéskategóriánként", loc="left", pad=46)
    ax.legend([Rectangle((0, 0), 1, 1, color=TDK_LIGHT), Rectangle((0, 0), 1, 1, color=TDK_DARK)],
              ["Szelektív pipeline", "Bizonyítékalapú ágens"],
              loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, fontsize=14, frameon=False, handlelength=1.2,
              borderaxespad=0.3)
    fig.text(0.01, 0.01, "A router eredeti döntése az eszkaláció előtt; kérdésenként az ismétlések többségi döntése.",
             fontsize=12, color=TDK_MID)
    fig.tight_layout(rect=(0, 0.04, 0.96, 1))
    path = _tdk_save(fig, path)
    plt.close(fig)
    return path


def routing_accuracy_by_category(path: Path, by_category: list[dict], overall: dict) -> Path | None:
    if not by_category:
        return None
    lookup = {r["value"]: r for r in by_category}
    order = _category_order(lookup)
    plt = _tdk_plt()
    fig, ax = plt.subplots(figsize=(12, 7.2))
    for y, category in enumerate(order):
        row = lookup[category]
        n = row["evaluated"]
        if not n:
            ax.text(0.01, y, "nincs értékelhető kérdés", va="center", fontsize=13, color=TDK_MID, style="italic")
            continue
        sparse = n < TDK_MIN_EVALUATED
        share = row["effectiveAccuracy"]
        ax.barh(y, share, height=0.62, color=TDK_PALE if sparse else TDK_DARK,
                edgecolor=TDK_MID if sparse else TDK_DARK, hatch="//" if sparse else None, linewidth=1, zorder=2)
        label = f"{_pct(share)}   n = {n}" + ("  · kevés adat" if sparse else "")
        ax.text(share + 0.012, y, label, va="center", fontsize=14, fontweight="bold" if not sparse else "normal",
                color=TDK_DARK if not sparse else TDK_MID)
    accuracy = overall.get("effectiveAccuracy")
    if accuracy is not None:
        ax.axvline(accuracy, color=TDK_MID, linestyle="--", linewidth=1.5, zorder=1)
        ax.text(accuracy, -0.72, f"összesen {_pct(accuracy)}", ha="center", va="center", fontsize=13, color=TDK_MID,
                bbox={"facecolor": TDK_SURFACE, "edgecolor": "none", "pad": 3}, zorder=4)
    ax.set_yticks(range(len(order)), [CATEGORY_LABELS.get(c, c) for c in order], fontsize=15)
    ax.set_ylim(len(order) - 0.5, -1.0)
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1])
    ax.xaxis.set_major_formatter(lambda v, _: f"{v * 100:.0f}%")
    ax.grid(axis="x", zorder=0)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("Helyes döntések aránya (%)", fontsize=15)
    ax.set_title("Az útválasztás helyessége kérdéskategóriánként", loc="left", pad=16)
    fig.text(0.01, 0.01, f"Végső útvonal, az eszkalációval együtt. Sávozott: {TDK_MIN_EVALUATED}-nél kevesebb "
                         "értékelhető kérdés. Referenciaválasz nélküli kérdések kimaradnak.", fontsize=12, color=TDK_MID)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    path = _tdk_save(fig, path)
    plt.close(fig)
    return path


def _thousands(value: float) -> str:
    return f"{round(value, -2):,.0f}".replace(",", " ")


def routing_nonoptimal_severity(path: Path, decisions: list[dict], summary: list[dict], tolerance: float) -> Path | None:
    styles = {
        "wasted_agent": ("Felesleges ágenshívás", TDK_LIGHT, "o"),
        "quality_loss_agent": ("Ágens, pedig a szelektív jobb", TDK_DARK, "s"),
        "quality_loss_selective": ("Szelektív, pedig az ágens jobb", TDK_MID, "^"),
    }
    items = [d for d in decisions if d.get("effectiveOutcome") in styles]
    if not items:
        return None
    stats = {r["outcome"]: r for r in summary}
    evaluated = sum(r["questions"] for r in summary)
    plt = _tdk_plt()
    fig, ax = plt.subplots(figsize=(12, 7.4))
    band = tolerance * 3
    ax.axhspan(-band, band, color="#EEF2FA", zorder=0)
    ax.text(0.01, band, f"tűrésen belül (±{_decimal(band)} pont)", transform=ax.get_yaxis_transform(), ha="left",
            va="bottom", fontsize=12, color=TDK_MID)
    ax.axhline(0, color=TDK_PALE, linewidth=1.2, zorder=1)
    ax.axvline(0, color=TDK_PALE, linewidth=1.2, zorder=1)
    handles = []
    for outcome, (label, color, marker) in styles.items():
        group = [d for d in items if d["effectiveOutcome"] == outcome]
        if not group:
            continue
        handle = ax.scatter([d["effectiveExtraTokens"] / 1000 for d in group],
                            [d["effectiveQualityLoss"] * 3 for d in group],
                            s=130, marker=marker, color=color, alpha=0.85, edgecolor=TDK_SURFACE, linewidth=1.5, zorder=3)
        row = stats[outcome]
        loss = row["qualityLossJudgePointsMean"]
        loss_text = "minőségvesztés ≈ 0" if abs(loss) < band else f"átl. {_decimal(loss, '{:.1f}')} pont vesztés"
        tokens = row["extraTokensMean"]
        ratio = _decimal(row["tokenRatioMedian"], "{:.1f}")
        cost_text = (f"+{_thousands(tokens)} token (medián {ratio}×)" if tokens >= 0
                     else f"{_thousands(-tokens)} tokennel olcsóbb")
        handles.append((handle, f"{label} – {row['questions']} eset: {loss_text}, {cost_text}"))
    ax.set_xlabel("Többlettoken a helyes választáshoz képest (ezer token / kérdés)", fontsize=15)
    ax.set_ylabel("Minőségvesztés (bírálói pont, 0–3 skála)", fontsize=15)
    ax.grid(axis="both", zorder=0)
    ax.set_ylim(-0.6, 2.3)
    ax.set_title("A nem optimális döntések súlyossága", loc="left", pad=100)
    ax.legend([h for h, _ in handles], [t for _, t in handles], loc="lower left", bbox_to_anchor=(0, 1.0),
              fontsize=13.5, frameon=False, handletextpad=0.4, borderaxespad=0.4, labelspacing=0.55)
    nonoptimal = len(items)
    fig.text(0.01, 0.012, (
        f"{nonoptimal} nem optimális döntés a {evaluated} értékelt kérdésből (végső útvonal, az eszkalációval együtt). "
        "A két stratégia saját futásainak kérdésenkénti átlagához mérve;\n"
        "átl. = átlag, 1 pont = egy fokozat a bíráló 0–3-as skáláján. Negatív többlettoken: a választott út olcsóbb volt."
    ), fontsize=11.5, color=TDK_MID, linespacing=1.4)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    path = _tdk_save(fig, path)
    plt.close(fig)
    return path


def routing_correctness_report(out_dir: Path, quality: str | None = None) -> dict[str, str | None]:
    from codemind_eval.routing import TIE_TOLERANCE, decision_correctness, summarize_decisions, summarize_non_optimal
    from codemind_eval.scoring import PRIMARY_QUALITY, write_csv
    scores = out_dir / "scores"
    figures = out_dir / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    rows = read_csv(scores / "rows.csv")
    quality = quality or PRIMARY_QUALITY
    decisions = decision_correctness(rows, quality, TIE_TOLERANCE)
    overall = summarize_decisions(decisions)[0] if decisions else {"evaluated": 0}
    by_category = summarize_decisions(decisions, "category")
    lookup = {r["value"]: r for r in by_category}
    ordered = [lookup[c] for c in _category_order(lookup)]
    summary = [{"qualityKey": quality, "tolerance": TIE_TOLERANCE, **r}
               for r in [overall, *ordered, *summarize_decisions(decisions, "experiment")]]
    for tolerance in TDK_TOLERANCES:
        if tolerance != TIE_TOLERANCE:
            summary.append({"qualityKey": quality, "tolerance": tolerance,
                            **summarize_decisions(decision_correctness(rows, quality, tolerance))[0],
                            "group": "sensitivity"})
    write_csv(scores / "routing_decision_correctness.csv", decisions)
    write_csv(scores / "routing_correctness_summary.csv", summary)
    severity = summarize_non_optimal(decisions)
    write_csv(scores / "routing_nonoptimal_summary.csv", [{"qualityKey": quality, "tolerance": TIE_TOLERANCE, **r}
                                                         for r in severity])
    produced = {
        "routing_decision_correctness": scores / "routing_decision_correctness.csv",
        "routing_correctness_summary": scores / "routing_correctness_summary.csv",
        "routing_nonoptimal_summary": scores / "routing_nonoptimal_summary.csv",
        "routing_nonoptimal_severity": routing_nonoptimal_severity(
            figures / "routing_nonoptimal_severity", decisions, severity, TIE_TOLERANCE),
        "routing_accuracy_donut": routing_accuracy_donut(figures / "routing_accuracy_donut", overall),
        "routing_decisions_by_category": routing_decisions_by_category(figures / "routing_decisions_by_category", by_category),
        "routing_accuracy_by_category": routing_accuracy_by_category(
            figures / "routing_accuracy_by_category", by_category, overall),
    }
    return {name: str(path) if path else None for name, path in produced.items()}


def ablation_chart(path: Path, ablation: list[dict]) -> Path | None:
    panels = [(k, l) for k, l in ABLATION_METRICS if any(r["metric"] == k and is_number(r.get("mean_delta")) for r in ablation)]
    if not panels:
        return None
    plt = _plt()
    fig, axes = plt.subplots(1, len(panels), figsize=(3.0 * len(panels) + 0.8, 3.2), squeeze=False)
    for ax, (metric, label) in zip(axes[0], panels):
        rows = [r for r in ablation if r["metric"] == metric and is_number(r.get("mean_delta"))]
        strategies = _ordered(r["strategy"] for r in rows)
        by = {r["strategy"]: r for r in rows}
        for y, s in enumerate(strategies):
            r = by[s]
            low = r["ci_low"] if is_number(r.get("ci_low")) else r["mean_delta"]
            high = r["ci_high"] if is_number(r.get("ci_high")) else r["mean_delta"]
            ax.plot([low, high], [y, y], color=INK_SECONDARY, linewidth=1, zorder=2)
            ax.scatter([r["mean_delta"]], [y], s=36, color=_color(s), edgecolor=SURFACE, linewidth=1.5, zorder=3)
        ax.axvline(0, color=AXIS, linewidth=1, zorder=1)
        ax.set_yticks(range(len(strategies)), [_label(s) for s in strategies] if ax is axes[0][0] else [""] * len(strategies))
        ax.invert_yaxis()
        ax.grid(axis="x")
        ax.grid(axis="y", visible=False)
        ax.set_title(label, loc="left", fontsize=9.5)
    fig.tight_layout()
    _note(fig, "Kérdésenként párosítva (az ismétlések átlagolva); pont = átlagos különbség, vonal = 95%-os bootstrap CI. "
               "Pozitív = kódmetrikákkal magasabb.")
    fig.savefig(path)
    plt.close(fig)
    return path


def generate_reports(out_dir: Path) -> dict[str, str | None]:
    scores = out_dir / "scores"
    figures = out_dir / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    rows = read_csv(scores / "rows.csv")
    summary = read_csv(scores / "summary_by_strategy.csv")
    by_category = read_csv(scores / "summary_by_category.csv")
    usage = read_csv(scores / "tool_usage.csv")
    ablation = read_csv(scores / "ablation.csv")
    routing_rows = read_csv(scores / "routing_questions.csv")
    routing_summary_path = scores / "routing_summary.json"
    routing_summary = json.loads(routing_summary_path.read_text(encoding="utf-8")) if routing_summary_path.exists() else {}
    composite_rows = read_csv(scores / "routing_questions_composite.csv")
    composite_summary_path = scores / "routing_summary_composite.json"
    composite_summary = (json.loads(composite_summary_path.read_text(encoding="utf-8"))
                         if composite_summary_path.exists() else {})
    quality = routing_summary.get("qualityKey") or "ctx_file_recall@5"
    quality_label = dict(RETRIEVAL_METRICS + ANSWER_METRICS + COMPOSITE_METRICS).get(quality, quality)

    produced = {
        "retrieval_by_strategy": grouped_bars(
            figures / "retrieval_by_strategy.png", summary, RETRIEVAL_METRICS, "Pontszám",
            "Átlag az arany bizonyítékkal rendelkező kérdéseken; hibasáv = 95%-os bootstrap CI a kérdések felett."),
        "answer_quality_by_strategy": grouped_bars(
            figures / "answer_quality_by_strategy.png", summary, ANSWER_METRICS, "Pontszám (0–1)",
            "Automatikus LLM-bírálói pontszámok, nem kézzel ellenőrzött referencia. Hibasáv = 95%-os bootstrap CI."),
        "overall_score_by_strategy": grouped_bars(
            figures / "overall_score_by_strategy.png", summary, COMPOSITE_METRICS, "Pontszám (0–1)",
            "Összetett pontszám = a válaszminőség, a megalapozottság és a visszakeresés átlaga; a hiányzó dimenziók "
            "kimaradnak. Hibasáv = 95%-os bootstrap CI."),
        "by_repository": repository_bars(figures / "by_repository.png", rows),
        "quality_by_category": category_heatmap(figures / "quality_by_category.png", by_category, quality, quality_label),
        "overall_score_by_category": category_heatmap(
            figures / "overall_score_by_category.png", by_category, "composite_score", "Összetett pontszám"),
        "latency_distribution": latency_boxplot(figures / "latency_distribution.png", rows),
        "tool_usage": tool_heatmap(figures / "tool_usage.png", usage),
        "routing_decisions": routing_chart(figures / "routing_decisions.png", routing_rows, routing_summary),
        "routing_decisions_composite": routing_chart(
            figures / "routing_decisions_composite.png", composite_rows, composite_summary),
        "cost_vs_quality": cost_quality_chart(figures / "cost_vs_quality.png", summary, quality, quality_label),
        "adaptive_savings_tradeoff": savings_tradeoff_chart(
            figures / "adaptive_savings_tradeoff.png", rows, routing_rows, quality, quality_label),
        "routing_policies": routing_policies_chart(figures / "routing_policies.png", rows, quality, quality_label),
        "routing_decision_quality": routing_decision_chart(
            figures / "routing_decision_quality.png", rows, quality, quality_label),
        "metrics_ablation": ablation_chart(figures / "metrics_ablation.png", ablation),
        "change_impact": grouped_bars(
            figures / "change_impact.png", summary, IMPACT_METRICS, "Pontszám",
            "Fájlszintű precision/recall/F1 a történeti commit által módosított fájlokhoz képest; "
            "az eltérő pillanatképen futott futások kimaradnak."),
    }
    return {name: str(path) if path else None for name, path in produced.items()}
