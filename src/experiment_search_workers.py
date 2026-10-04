"""
Experiment: Such-Performance der Subgraph-Suche mit 1, 2 und 3 Workern.

Wählt per Seed 50 vorhandene Netzwerke (mindestens 15 Knoten) zufällig aus
der Datenbank (DATABASE_* aus der .env) und nutzt sie als Suchanfragen.
Für jede Worker-Anzahl werden dieselben Anfragen über crud.search_subgraph()
ausgeführt und die Zeit pro Anfrage gemessen, so dass die Ergebnisse direkt
vergleichbar sind. Die Auswahl ist reproduzierbar, solange sich die
Datenbank nicht ändert.

Aufruf (im Projektordner, damit die .env gefunden wird):
    python scripts/experiment_search_workers.py
    python scripts/experiment_search_workers.py --queries 50 --workers 1 2 3 --seed 42

Ausgabe:
- Zusammenfassung je Worker-Anzahl in der Konsole
- Einzelmessungen in experiment_search_workers.csv

Hinweis zur Laufzeit: Eine Suche kann mehrere Minuten dauern. 50 Anfragen
x 3 Worker-Einstellungen können Stunden dauern. Mit --queries 5 vorab testen.
Der Server darf währenddessen nicht dieselben Worker belegen (Server stoppen).
"""

import argparse
import csv
import logging
import re
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from backend import crud, subgraph_executor  # noqa: E402

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


def run_experiment(queries, workers_list, warmup, csv_path):
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

    write_csv(rows, csv_path)
    return rows


def write_csv(rows, path):
    fields = ["workers", "query", "network_id", "nodes", "edges", "candidates", "matches",
              "total_s", "fetch_s", "compare_s", "build_s"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def percentile(values, q):
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def summarize(rows, workers_list):
    print("\n=== Zusammenfassung ===")
    print(f"{'Worker':>6} {'Summe[s]':>9} {'Mittel[s]':>10} {'Median[s]':>10} {'P95[s]':>8} "
          f"{'Speedup':>8} {'Vergl./s':>9} {'seriell%':>9}")

    baseline_total = None
    for workers in workers_list:
        subset = [r for r in rows if r["workers"] == workers]
        if not subset:
            continue
        totals = [r["total_s"] for r in subset]
        sum_total = sum(totals)
        if baseline_total is None:
            baseline_total = sum_total

        compare = [r["compare_s"] for r in subset if r["compare_s"] is not None]
        candidates = [r["candidates"] for r in subset if r["candidates"] is not None]
        if compare and len(compare) == len(subset) and sum(compare) > 0:
            rate = f"{sum(candidates) / sum(compare):>9.0f}"
            serial = f"{max(0.0, 1 - sum(compare) / sum_total) * 100:>8.0f}%"
        else:
            rate = serial = f"{'n/a':>9}"

        print(f"{workers:>6} {sum_total:>9.0f} {statistics.mean(totals):>10.1f} "
              f"{statistics.median(totals):>10.1f} {percentile(totals, 0.95):>8.1f} "
              f"{baseline_total / sum_total:>7.2f}x {rate} {serial}")

    print("\nSpeedup = Gesamtzeit mit der ersten Worker-Anzahl / Gesamtzeit dieser Zeile.")
    print("Vergl./s = Kandidaten pro Sekunde in der Vergleichsphase (nur wenn crud.py die Phasenzeiten loggt).")
    print("seriell% = Anteil der Gesamtzeit außerhalb der parallelen Vergleiche (Laden, Treffer bauen).")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queries", type=int, default=50, help="Anzahl Suchanfragen je Worker-Anzahl")
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--min-nodes", type=int, default=15, help="Mindestanzahl Knoten der Query")
    parser.add_argument("--max-nodes", type=int, default=None, help="Optionale Obergrenze der Knotenanzahl")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--warmup", type=int, default=1, help="Verworfene Aufwärm-Suchen je Worker-Anzahl")
    parser.add_argument("--csv", default="experiment_search_workers.csv")
    args = parser.parse_args()

    if args.min_nodes < 15:
        parser.error("--min-nodes muss mindestens 15 sein")
    if args.max_nodes is not None and args.max_nodes < args.min_nodes:
        parser.error("--max-nodes muss >= --min-nodes sein")

    queries = load_queries_from_db(args.queries, args.min_nodes, args.max_nodes, args.seed)
    print(f"{len(queries)} Anfragen aus der Datenbank (mind. {args.min_nodes} Knoten), Seed {args.seed}, "
          f"Worker {args.workers}, Warm-up {args.warmup}")

    rows = run_experiment(queries, args.workers, args.warmup, args.csv)
    summarize(rows, args.workers)
    print(f"\nEinzelmessungen: {args.csv}")


if __name__ == "__main__":
    main()
