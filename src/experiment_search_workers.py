"""
Experiment: Such-Performance der Subgraph-Suche mit 1, 2 und 3 Workern.

Wählt per Seed 50 vorhandene Netzwerke (mindestens 15 Knoten) zufällig aus
der Datenbank (DATABASE_* aus der .env) und nutzt sie als Suchanfragen.
Für jede Worker-Anzahl werden dieselben Anfragen über crud.search_subgraph()
ausgeführt und die Zeit pro Anfrage gemessen, so dass die Ergebnisse direkt
vergleichbar sind. Die Auswahl ist reproduzierbar, solange sich die
Datenbank nicht ändert.

Aufruf (im Projektordner, damit die .env gefunden wird):
    python src/experiment_search_workers.py
    python src/experiment_search_workers.py --queries 5
    python src/experiment_search_workers.py --queries 50 --workers 1 2 3 --seed 42

Ergebnisse (Verzeichnis src/results/, Dateiname mit Zeitstempel):
- search_workers_<zeit>.json : Metadaten, Zusammenfassung und alle Einzelmessungen
- search_workers_<zeit>.pdf  : Diagramme (Gesamtzeit, Verteilung, Phasen, Skalierung)

Die JSON-Datei wird nach jeder Anfrage aktualisiert, ein Abbruch nach
Stunden verliert also keine Messwerte. Aus einer vorhandenen JSON-Datei
lässt sich das PDF ohne neuen Messlauf erzeugen:
    python src/experiment_search_workers.py --plot-from src/results/search_workers_<zeit>.json

Hinweis zur Laufzeit: Eine Suche kann mehrere Minuten dauern. 50 Anfragen
x 3 Worker-Einstellungen können Stunden dauern. Mit --queries 5 vorab testen.
Der Server darf währenddessen nicht dieselben Worker belegen (Server stoppen).
Für das PDF wird matplotlib benötigt (pip install matplotlib).
"""

import argparse
import json
import logging
import os
import platform
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

# Dieses Skript liegt in src/, daneben liegt das Paket backend/
SRC_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC_DIR))

from backend import crud, subgraph_executor  # noqa: E402

DEFAULT_RESULTS_DIR = SRC_DIR / "results"

PHASES_RE = re.compile(r"fetch ([\d.]+)s, compare ([\d.]+)s, build ([\d.]+)s")
CANDIDATES_RE = re.compile(r"search_subgraph: (\d+) candidates for query")


class _PhaseCapture(logging.Handler):
    """Liest Phasenzeiten und Kandidatenanzahl aus den Log-Zeilen von crud.py."""

    def __init__(self):
        super().__init__(level=logging.INFO)
        self.reset()

    def reset(self):
        self.candidates = None
        self.fetch = self.compare = self.build = None

    def emit(self, record):
        message = record.getMessage()
        match = CANDIDATES_RE.search(message)
        if match:
            self.candidates = int(match.group(1))
        match = PHASES_RE.search(message)
        if match:
            self.fetch, self.compare, self.build = (float(x) for x in match.groups())


# ---------------------------------------------------------------------------
# Auswahl der Anfragen und Messung
# ---------------------------------------------------------------------------

def load_queries_from_db(count, min_nodes, max_nodes, seed):
    """
    Wählt zufällig (per Seed) vorhandene Netzwerke aus der Datenbank als Queries.

    Es werden zuerst nur die IDs geladen (günstig auch bei 1 Mio. Zeilen) und
    erst danach die Matrizen der gewählten Netzwerke.

    Returns:
        Liste von (network_id, matrix, labels)
    """
    with crud.get_db_connection() as conn:
        cursor = crud.get_db_cursor(conn)

        sql = "SELECT network_id FROM biological_networks WHERE node_count >= %s"
        params = [min_nodes]
        if max_nodes is not None:
            sql += " AND node_count <= %s"
            params.append(max_nodes)
        sql += " ORDER BY network_id"
        cursor.execute(sql, tuple(params))
        ids = [row["network_id"] for row in cursor.fetchall()]

        if len(ids) < count:
            raise SystemExit(
                f"Nur {len(ids)} Netzwerke mit mindestens {min_nodes} Knoten in der Datenbank, "
                f"aber {count} Anfragen gewünscht (--queries verkleinern)."
            )

        rng = np.random.default_rng(seed)
        chosen = [int(i) for i in rng.choice(ids, size=count, replace=False)]

        cursor.execute(
            """
            SELECT nm.network_id, nm.node_labels, nm.adjacency_matrix
            FROM network_matrices nm
            WHERE nm.network_id = ANY(%s)
            """,
            (chosen,),
        )
        by_id = {row["network_id"]: row for row in cursor.fetchall()}

    # Reihenfolge der zufälligen Auswahl beibehalten
    return [
        (nid, [list(map(int, r)) for r in by_id[nid]["adjacency_matrix"]], list(by_id[nid]["node_labels"]))
        for nid in chosen
    ]


def run_search(capture, matrix, labels):
    """Eine Suche ausführen und Messwerte zurückgeben."""
    capture.reset()
    start = time.perf_counter()
    matches = crud.search_subgraph(matrix, labels)
    total = time.perf_counter() - start
    return {
        "nodes": len(matrix),
        "edges": int(sum(sum(row) for row in matrix)),
        "candidates": capture.candidates,
        "matches": len(matches),
        "total_s": total,
        "fetch_s": capture.fetch,
        "compare_s": capture.compare,
        "build_s": capture.build,
    }


def run_experiment(queries, workers_list, warmup, meta, json_path):
    """
    Führt das Experiment aus und schreibt nach jeder Anfrage die JSON-Datei.

    Returns:
        Liste der Einzelmessungen (dicts)
    """
    capture = _PhaseCapture()
    crud_logger = logging.getLogger("backend.crud")
    crud_logger.setLevel(logging.INFO)
    crud_logger.addHandler(capture)
    crud_logger.propagate = False  # Konsole nicht mit Log-Zeilen fluten

    rows = []
    try:
        for workers in workers_list:
            subgraph_executor.shutdown_executor()
            executor = subgraph_executor.get_executor(workers)
            # Worker-Prozesse vorab starten, damit die Startzeit nicht mitgemessen wird
            list(executor.map(abs, range(workers * 2)))

            for i in range(warmup):
                _, matrix, labels = queries[i % len(queries)]
                run_search(capture, matrix, labels)  # verworfen (Caches, Pool)

            print(f"\n=== {workers} Worker ===", flush=True)
            started = time.perf_counter()
            for index, (network_id, matrix, labels) in enumerate(queries, start=1):
                result = run_search(capture, matrix, labels)
                result.update(workers=workers, query=index, network_id=network_id)
                rows.append(result)
                save_json(json_path, meta, rows, workers_list, complete=False)

                elapsed = time.perf_counter() - started
                eta = elapsed / index * (len(queries) - index)
                print(
                    f"  Anfrage {index:>3}/{len(queries)}: Netzwerk {network_id} n={result['nodes']:>2} e={result['edges']:>3} "
                    f"Kandidaten={result['candidates']} Treffer={result['matches']} "
                    f"{result['total_s']:.1f}s (Rest ca. {eta / 60:.0f} min)",
                    flush=True,
                )
    finally:
        subgraph_executor.shutdown_executor()
        crud_logger.removeHandler(capture)

    save_json(json_path, meta, rows, workers_list, complete=True)
    return rows


# ---------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------

def percentile(values, q):
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def compute_summary(rows, workers_list):
    """Kennzahlen je Worker-Anzahl (Speedup relativ zur ersten Worker-Anzahl)."""
    summary = []
    baseline_total = None
    for workers in workers_list:
        subset = [r for r in rows if r["workers"] == workers]
        if not subset:
            continue
        totals = [r["total_s"] for r in subset]
        sum_total = sum(totals)
        if baseline_total is None:
            baseline_total = sum_total

        compare = [r["compare_s"] for r in subset if r.get("compare_s") is not None]
        candidates = [r["candidates"] for r in subset if r.get("candidates") is not None]
        has_phases = bool(compare) and len(compare) == len(subset) and sum(compare) > 0

        summary.append({
            "workers": workers,
            "queries": len(subset),
            "sum_s": sum_total,
            "mean_s": statistics.mean(totals),
            "median_s": statistics.median(totals),
            "p95_s": percentile(totals, 0.95),
            "speedup": baseline_total / sum_total if sum_total > 0 else None,
            "pairs_per_s": sum(candidates) / sum(compare) if has_phases and candidates else None,
            "serial_share": max(0.0, 1 - sum(compare) / sum_total) if has_phases and sum_total > 0 else None,
        })
    return summary


def print_summary(summary):
    print("\n=== Zusammenfassung ===")
    print(f"{'Worker':>6} {'Summe[s]':>9} {'Mittel[s]':>10} {'Median[s]':>10} {'P95[s]':>8} "
          f"{'Speedup':>8} {'Vergl./s':>9} {'seriell%':>9}")
    for s in summary:
        rate = f"{s['pairs_per_s']:>9.0f}" if s["pairs_per_s"] is not None else f"{'n/a':>9}"
        serial = f"{s['serial_share'] * 100:>8.0f}%" if s["serial_share"] is not None else f"{'n/a':>9}"
        print(f"{s['workers']:>6} {s['sum_s']:>9.0f} {s['mean_s']:>10.1f} "
              f"{s['median_s']:>10.1f} {s['p95_s']:>8.1f} "
              f"{s['speedup']:>7.2f}x {rate} {serial}")

    print("\nSpeedup = Gesamtzeit mit der ersten Worker-Anzahl / Gesamtzeit dieser Zeile.")
    print("Vergl./s = Kandidaten pro Sekunde in der Vergleichsphase (nur wenn crud.py die Phasenzeiten loggt).")
    print("seriell% = Anteil der Gesamtzeit außerhalb der parallelen Vergleiche (Laden, Treffer bauen).")


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def save_json(path, meta, rows, workers_list, complete):
    """Schreibt Metadaten, Zusammenfassung und Einzelmessungen (atomar)."""
    data = {
        "meta": {**meta, "complete": complete},
        "summary": compute_summary(rows, workers_list),
        "measurements": rows,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# Diagramme (PDF)
# ---------------------------------------------------------------------------

def build_figures(data):
    """
    Erzeugt die Diagramme aus den JSON-Daten.

    Seite 1: Gesamtzeit und Speedup, Verteilung der Zeit pro Anfrage,
             Phasen (Laden/Vergleichen/Treffer bauen), Zeit gegen Kandidatenanzahl.
    Seite 2: Zeit pro Anfrage für alle Worker-Anzahlen (gleiche Anfragen).

    Returns:
        Liste von matplotlib-Figures
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    meta = data["meta"]
    rows = data["measurements"]
    summary = data["summary"]
    workers_list = [s["workers"] for s in summary]
    labels = [str(w) for w in workers_list]
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    color_of = {w: colors[i % len(colors)] for i, w in enumerate(workers_list)}
    by_workers = {w: [r for r in rows if r["workers"] == w] for w in workers_list}

    status = "" if meta.get("complete", True) else " (unvollständig)"
    title = (f"Subgraph-Suche: {len(by_workers[workers_list[0]])} Anfragen aus der Datenbank, "
             f"mind. {meta.get('min_nodes', '?')} Knoten{status}")

    # --- Seite 1 -----------------------------------------------------------
    fig1, axes = plt.subplots(2, 2, figsize=(11.69, 8.27))  # A4 quer
    fig1.suptitle(title, fontsize=13)

    # (a) Gesamtzeit + Speedup
    ax = axes[0, 0]
    totals_min = [s["sum_s"] / 60 for s in summary]
    bars = ax.bar(labels, totals_min, color=[color_of[w] for w in workers_list])
    for bar, s in zip(bars, summary):
        ax.annotate(f"{s['speedup']:.2f}x", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    ha="center", va="bottom", fontsize=10)
    ax.set_xlabel("Worker")
    ax.set_ylabel("Gesamtzeit aller Anfragen [min]")
    ax.set_title("Gesamtzeit und Speedup")
    ax.set_ylim(0, max(totals_min) * 1.15)

    # (b) Verteilung der Zeit pro Anfrage
    ax = axes[0, 1]
    ax.boxplot([[r["total_s"] for r in by_workers[w]] for w in workers_list], showmeans=True)
    ax.set_xticklabels(labels)
    ax.set_yscale("log")
    ax.set_xlabel("Worker")
    ax.set_ylabel("Zeit pro Anfrage [s] (log)")
    ax.set_title("Verteilung der Antwortzeiten")

    # (c) Phasen
    ax = axes[1, 0]
    phase_names = [("fetch_s", "Laden (DB)"), ("compare_s", "Vergleichen (parallel)"),
                   ("build_s", "Treffer bauen")]
    has_phases = all(r.get("compare_s") is not None for r in rows)
    if has_phases:
        bottom = np.zeros(len(workers_list))
        for key, name in phase_names:
            means = np.array([statistics.mean(r[key] for r in by_workers[w]) for w in workers_list])
            ax.bar(labels, means, bottom=bottom, label=name)
            bottom += means
        ax.legend(fontsize=8)
        ax.set_ylabel("Mittlere Zeit pro Anfrage [s]")
        ax.set_title("Zeit je Phase")
    else:
        ax.text(0.5, 0.5, "Keine Phasenzeiten vorhanden\n(crud.py loggt sie nicht)",
                ha="center", va="center", transform=ax.transAxes)
        ax.set_title("Zeit je Phase")
    ax.set_xlabel("Worker")

    # (d) Zeit gegen Kandidatenanzahl
    ax = axes[1, 1]
    plotted = False
    for w in workers_list:
        points = [(r["candidates"], r["total_s"]) for r in by_workers[w] if r.get("candidates") is not None]
        if points:
            plotted = True
            xs, ys = zip(*points)
            ax.scatter(xs, ys, s=18, alpha=0.7, color=color_of[w], label=f"{w} Worker")
    if plotted:
        ax.legend(fontsize=8)
        ax.set_xlabel("Kandidaten nach SQL-Vorauswahl")
        ax.set_ylabel("Zeit pro Anfrage [s]")
    else:
        ax.text(0.5, 0.5, "Keine Kandidatenanzahl vorhanden", ha="center", va="center",
                transform=ax.transAxes)
    ax.set_title("Skalierung mit der Suchraumgröße")

    for a in axes.flat:
        a.grid(alpha=0.3)
    fig1.tight_layout(rect=(0, 0, 1, 0.95))

    # --- Seite 2 -----------------------------------------------------------
    fig2, ax = plt.subplots(figsize=(11.69, 8.27))
    base = {r["query"]: r["total_s"] for r in by_workers[workers_list[0]]}
    order = sorted(base, key=base.get)
    position = {q: i + 1 for i, q in enumerate(order)}
    for w in workers_list:
        points = sorted((position[r["query"]], r["total_s"]) for r in by_workers[w] if r["query"] in position)
        if points:
            xs, ys = zip(*points)
            ax.plot(xs, ys, marker="o", markersize=3.5, linewidth=1, color=color_of[w], label=f"{w} Worker")
    ax.set_yscale("log")
    ax.set_xlabel(f"Anfragen, sortiert nach Zeit mit {workers_list[0]} Worker")
    ax.set_ylabel("Zeit pro Anfrage [s] (log)")
    ax.set_title("Dieselben Anfragen mit unterschiedlicher Worker-Anzahl")
    ax.grid(alpha=0.3)
    ax.legend()
    fig2.tight_layout()

    return [fig1, fig2]


def save_pdf(figures, path):
    from matplotlib.backends.backend_pdf import PdfPages
    import matplotlib.pyplot as plt

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(path) as pdf:
        for fig in figures:
            pdf.savefig(fig)
            plt.close(fig)


def write_pdf_from_json(json_path, pdf_path=None):
    data = load_json(json_path)
    pdf_path = Path(pdf_path) if pdf_path else Path(json_path).with_suffix(".pdf")
    save_pdf(build_figures(data), pdf_path)
    return pdf_path


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queries", type=int, default=50, help="Anzahl Suchanfragen je Worker-Anzahl")
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--min-nodes", type=int, default=15, help="Mindestanzahl Knoten der Query")
    parser.add_argument("--max-nodes", type=int, default=None, help="Optionale Obergrenze der Knotenanzahl")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--warmup", type=int, default=1, help="Verworfene Aufwärm-Suchen je Worker-Anzahl")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR),
                        help="Zielverzeichnis für JSON und PDF (Standard: src/results)")
    parser.add_argument("--plot-from", metavar="JSON",
                        help="Nur das PDF aus einer vorhandenen JSON-Datei erzeugen (kein Messlauf)")
    args = parser.parse_args()

    if args.plot_from:
        pdf_path = write_pdf_from_json(args.plot_from, Path(args.results_dir) / (Path(args.plot_from).stem + ".pdf"))
        print(f"PDF: {pdf_path}")
        return

    if args.min_nodes < 15:
        parser.error("--min-nodes muss mindestens 15 sein")
    if args.max_nodes is not None and args.max_nodes < args.min_nodes:
        parser.error("--max-nodes muss >= --min-nodes sein")

    results_dir = Path(args.results_dir)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = results_dir / f"search_workers_{stamp}.json"
    pdf_path = results_dir / f"search_workers_{stamp}.pdf"

    queries = load_queries_from_db(args.queries, args.min_nodes, args.max_nodes, args.seed)
    print(f"{len(queries)} Anfragen aus der Datenbank (mind. {args.min_nodes} Knoten), Seed {args.seed}, "
          f"Worker {args.workers}, Warm-up {args.warmup}")

    meta = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "seed": args.seed,
        "queries": len(queries),
        "workers": args.workers,
        "min_nodes": args.min_nodes,
        "max_nodes": args.max_nodes,
        "warmup": args.warmup,
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "query_network_ids": [nid for nid, _, _ in queries],
    }

    rows = run_experiment(queries, args.workers, args.warmup, meta, json_path)
    print_summary(compute_summary(rows, args.workers))

    print(f"\nJSON: {json_path}")
    try:
        save_pdf(build_figures(load_json(json_path)), pdf_path)
        print(f"PDF:  {pdf_path}")
    except ImportError:
        print("PDF nicht erzeugt: matplotlib fehlt (pip install matplotlib). "
              f"Danach: python src/experiment_search_workers.py --plot-from {json_path}")


if __name__ == "__main__":
    main()
