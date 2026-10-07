"""
Experiment: Such-Performance der Subgraph-Suche, Python- gegen C++-Implementierung.

Erweiterung von experiment_search_workers.py. Statt die Worker-Anzahl zu variieren,
wird hier die Implementierung des Subgraph Algorithmus verglichen, die der
Executor in den Worker-Prozessen verwendet:

- python : Dependency ``subgraph`` (naphets86/subgraph, ``Subgraph().compare_graphs``)
- cpp    : csubgraph (naphets86/csubgraph), statische Bibliothek ``libsubgraphlib.a``
           über CSUBGRAPH_LIB_PATH, direkt im Worker-Prozess aufgerufen (ctypes)

Versuchsaufbau (identisch zu experiment_search_workers.py, damit die Ergebnisse
in science/gen-db.tex direkt neben der Worker-Messreihe stehen können):
- 6 Anfragen (Standard), zufällig per Seed aus der Datenbank (DATABASE_* aus der
  .env), mindestens 15 Knoten, Seed 42 -> dieselben Netzwerke wie bei den
  Worker-Messungen, solange sich die Datenbank nicht ändert
- 2 Worker (Standard), je Implementierung ein neu erzeugter Prozess-Pool
- 1 verworfene Aufwärmanfrage je Messreihe
- gemessen wird die Wanduhrzeit von crud.search_subgraph() (DB-Abfrage,
  Vergleiche, Prozesskommunikation, Trefferliste); zusätzlich die Zeit der
  parallelen Vergleichsphase (compare_many) und der serielle Rest

Zusätzlich zur Messung der Gesamtsuche:
- Kontrolle, dass beide Implementierungen dieselben Treffer (network_id) liefern
- Kontrolle, dass wirklich die gewünschte Implementierung läuft (kein stiller
  Fallback von cpp auf python), in jedem Lauf und in den Worker-Prozessen
- Zählung fehlgeschlagener Einzelvergleiche (z.B. csubgraph-Timeout)
- Mikro-Benchmark ohne Datenbank: Zeit je Einzelvergleich beider Implementierungen
  auf denselben Zufallsgraphen sowie die reinen Aufrufkosten der Bibliothek
  (Marshalling + Funktionsaufruf) mit einem trivialen 1x1-Vergleich

Hinweis zur Deutung: Gen-DB bindet csubgraph als Bibliothek ein. Die statische
Bibliothek wird beim ersten Gebrauch mit einem C-Wrapper zu einer DLL/.so gelinkt
(Compiler, z.B. MinGW g++, nötig) und je Worker-Prozess einmal geladen; ein
Vergleich ist ein direkter Funktionsaufruf ohne Prozessstart und ohne JSON. Der
einmalige Link-Build findet vor dem Start des Prozess-Pools statt und ist nicht
Teil der Messung. Frühere Messläufe (JSON mit ``csubgraph_cli``) stammen von der
CLI-Variante und sind mit diesen Werten nicht direkt vergleichbar.

Aufruf (im Projektordner, damit die .env gefunden wird):
    python src/experiment_search_backends.py
    python src/experiment_search_backends.py --queries 2          # Vorab-Test
    python src/experiment_search_backends.py --csubgraph-lib-path C:\\...\\libsubgraphlib.a
    python src/experiment_search_backends.py --backends cpp python --workers 2

Ergebnisse (src/results/, Dateiname mit Zeitstempel):
- search_backends_<zeit>.json           : Metadaten, Zusammenfassung, Einzelmessungen
- search_backends_<zeit>.pdf            : Diagramme auf zwei Seiten
- search_backends_<zeit>_tabellen.tex   : Tabellen für gen-db.tex (\\input{...})
- plot6_backends_gesamtzeit_speedup.pdf, plot7_..._verteilung_antwortzeiten.pdf,
  plot8_..._phasen.pdf, plot9_..._skalierung_suchraum.pdf,
  plot10_..._gleiche_anfragen.pdf    : Einzeldiagramme für \\includegraphics

Die JSON-Datei wird nach jeder Anfrage aktualisiert (ein Abbruch verliert keine
Messwerte). Aus einer vorhandenen JSON-Datei lassen sich PDF, Einzeldiagramme und
Tabellen ohne neuen Messlauf erzeugen:
    python src/experiment_search_backends.py --plot-from src/results/search_backends_<zeit>.json

Der Server darf während des Experiments nicht laufen (Worker würden konkurrieren).
Für die Diagramme wird matplotlib benötigt (pip install matplotlib).
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

from backend import config as backend_config  # noqa: E402
from backend import crud, csubgraph_native, subgraph_executor  # noqa: E402

DEFAULT_RESULTS_DIR = SRC_DIR / "results"
BACKENDS = ("python", "cpp")
# Name des Executors in subgraph_executor.get_backend_name()
EXPECTED_NAME = {"python": "python", "cpp": "csubgraph"}
DISPLAY = {"python": "Python", "cpp": "C++"}
FAILED_RE = re.compile(r"(\d+) of (\d+) comparisons failed")

SINGLE_PLOTS = {
    "gesamtzeit_speedup": "plot6_backends_gesamtzeit_speedup.pdf",
    "verteilung_antwortzeiten": "plot7_backends_verteilung_antwortzeiten.pdf",
    "phasen": "plot8_backends_phasen.pdf",
    "skalierung_suchraum": "plot9_backends_skalierung_suchraum.pdf",
    "gleiche_anfragen": "plot10_backends_gleiche_anfragen.pdf",
}


# ---------------------------------------------------------------------------
# Auswahl der Implementierung
# ---------------------------------------------------------------------------

def resolve_lib(path_argument):
    """
    Findet libsubgraphlib.a: --csubgraph-lib-path, sonst CSUBGRAPH_LIB_PATH aus .env.

    Muss vor configure_backend() aufgerufen werden, solange die Konfiguration
    noch den Wert aus der .env enthält.

    Returns:
        (Pfad zur Bibliothek oder None, ursprüngliche Einstellung)
    """
    setting = path_argument
    if not setting:
        setting = getattr(backend_config.get_config(), "csubgraph_lib_path", None)
    lib = csubgraph_native.find_static_library(setting)
    return (str(lib) if lib else None), setting


def configure_backend(backend, lib):
    """
    Stellt die Implementierung für den nächsten Prozess-Pool ein.

    CSUBGRAPH_LIB_PATH wird über die Umgebung gesetzt (leer = Python). Umgebungs-
    variablen haben Vorrang vor der .env und werden von Worker-Prozessen
    geerbt, egal ob sie per fork oder spawn (Windows) gestartet werden.
    Der Link-Build der Wrapper-Bibliothek läuft hier (über get_backend_name),
    also vor jeder Messung.
    """
    os.environ["CSUBGRAPH_LIB_PATH"] = lib if backend == "cpp" else ""
    backend_config.reload_config()
    subgraph_executor.reset_backend()
    actual = subgraph_executor.get_backend_name()
    if actual != EXPECTED_NAME[backend]:
        reason = subgraph_executor.get_native_error()
        raise SystemExit(
            f"Implementierung '{backend}' angefordert, aufgelöst wurde '{actual}'."
            + (f"\nGrund: {reason}" if reason else "")
        )


def _probe_backend(_):
    """Läuft im Worker-Prozess: welche Implementierung wird dort verwendet?"""
    return os.getpid(), subgraph_executor.get_backend_name()


def start_pool(workers, backend):
    """Pool neu erzeugen, Worker vorab starten und deren Implementierung prüfen."""
    subgraph_executor.shutdown_executor()
    executor = subgraph_executor.get_executor(workers)
    seen = set(executor.map(_probe_backend, range(workers * 4)))
    wrong = {name for _, name in seen if name != EXPECTED_NAME[backend]}
    if wrong:
        raise SystemExit(f"Worker verwenden {sorted(wrong)} statt '{EXPECTED_NAME[backend]}'.")
    return sorted(pid for pid, _ in seen)


# ---------------------------------------------------------------------------
# Auswahl der Anfragen und Messung
# ---------------------------------------------------------------------------

def load_queries_from_db(count, min_nodes, max_nodes, seed):
    """
    Wählt zufällig (per Seed) vorhandene Netzwerke aus der Datenbank als Queries.

    Es werden zuerst nur die IDs geladen (günstig auch bei 1 Mio. Zeilen) und
    erst danach die Matrizen der gewählten Netzwerke. Auswahlverfahren und Seed
    sind identisch zu experiment_search_workers.py.

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

    return [
        (nid, [list(map(int, r)) for r in by_id[nid]["adjacency_matrix"]], list(by_id[nid]["node_labels"]))
        for nid in chosen
    ]


class _CompareTimer:
    """Misst die Zeit der parallelen Vergleichsphase (crud.compare_many) einer Suche."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.compare_s = 0.0
        self.candidates = None

    def wrap(self, function):
        def timed(query, candidates, *args, **kwargs):
            self.candidates = len(candidates)
            start = time.perf_counter()
            try:
                return function(query, candidates, *args, **kwargs)
            finally:
                self.compare_s += time.perf_counter() - start
        return timed


class _FailureCapture(logging.Handler):
    """Zählt fehlgeschlagene Einzelvergleiche aus der Warnung von crud.search_subgraph."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.failed = 0

    def emit(self, record):
        match = FAILED_RE.search(record.getMessage())
        if match:
            self.failed = int(match.group(1))


def run_search(timer, failures, matrix, labels):
    """Eine Suche ausführen und Messwerte zurückgeben."""
    timer.reset()
    failures.failed = 0
    start = time.perf_counter()
    matches = crud.search_subgraph(matrix, labels)
    total = time.perf_counter() - start
    return {
        "nodes": len(matrix),
        "edges": int(sum(sum(row) for row in matrix)),
        "candidates": timer.candidates,
        "matches": len(matches),
        "match_ids": sorted(int(m.network_id) for m in matches),
        "failed": failures.failed,
        "total_s": total,
        "compare_s": timer.compare_s,
        "serial_s": max(0.0, total - timer.compare_s),
    }


def run_experiment(queries, backends, workers_list, warmup, lib, meta, json_path):
    """
    Führt das Experiment aus und schreibt nach jeder Anfrage die JSON-Datei.

    Reihenfolge: je Implementierung ein Block, darin je Worker-Anzahl dieselben
    Anfragen in derselben Reihenfolge.

    Returns:
        Liste der Einzelmessungen (dicts)
    """
    timer = _CompareTimer()
    failures = _FailureCapture()
    crud_logger = logging.getLogger("backend.crud")
    crud_logger.addHandler(failures)
    crud_logger.setLevel(logging.INFO)
    crud_logger.propagate = False  # Konsole nicht mit Log-Zeilen fluten
    original_compare_many = crud.compare_many
    crud.compare_many = timer.wrap(original_compare_many)

    rows = []
    try:
        for backend in backends:
            configure_backend(backend, lib)
            for workers in workers_list:
                pids = start_pool(workers, backend)
                meta.setdefault("worker_pids", {})[f"{backend}/{workers}"] = pids

                for i in range(warmup):
                    _, matrix, labels = queries[i % len(queries)]
                    run_search(timer, failures, matrix, labels)  # verworfen (Caches, Pool)

                print(f"\n=== {DISPLAY[backend]}, {workers} Worker ===", flush=True)
                started = time.perf_counter()
                for index, (network_id, matrix, labels) in enumerate(queries, start=1):
                    result = run_search(timer, failures, matrix, labels)
                    result.update(backend=backend, workers=workers, query=index, network_id=network_id)
                    rows.append(result)
                    save_json(json_path, meta, rows, backends, workers_list, complete=False)

                    elapsed = time.perf_counter() - started
                    eta = elapsed / index * (len(queries) - index)
                    print(
                        f"  Anfrage {index:>3}/{len(queries)}: Netzwerk {network_id} n={result['nodes']:>2} "
                        f"e={result['edges']:>3} Kandidaten={result['candidates']} Treffer={result['matches']} "
                        f"Fehler={result['failed']} {result['total_s']:.1f}s (Rest ca. {eta / 60:.0f} min)",
                        flush=True,
                    )
    finally:
        crud.compare_many = original_compare_many
        subgraph_executor.shutdown_executor()
        crud_logger.removeHandler(failures)

    save_json(json_path, meta, rows, backends, workers_list, complete=True)
    return rows


# ---------------------------------------------------------------------------
# Mikro-Benchmark (ohne Datenbank)
# ---------------------------------------------------------------------------

def _random_graph(rng, n, p=0.3):
    """Zufallsgraph wie in db-populate.py: gerichtet, Kante mit Wahrscheinlichkeit p, keine Schleifen."""
    matrix = (rng.random((n, n)) < p).astype(int)
    np.fill_diagonal(matrix, 0)
    return matrix


def calibrate(backends, lib, pairs, seed):
    """
    Zeit je Einzelvergleich im Hauptprozess (ohne Pool, ohne Datenbank).

    Gemessen werden dieselben Zufallspaare (A mit 15 bis 19 Knoten, B mit 20
    Knoten, Kantenwahrscheinlichkeit 0,3) für jede Implementierung. Für cpp
    wird zusätzlich ein trivialer 1x1-Vergleich gemessen: das sind die
    Aufrufkosten der Bibliothek (Marshalling und Funktionsaufruf), nahezu ohne
    Rechenzeit.
    """
    rng = np.random.default_rng(seed)
    sample = [(_random_graph(rng, int(rng.integers(15, 20))), _random_graph(rng, 20)) for _ in range(pairs)]
    result = {"pairs": pairs, "seed": seed}

    def timed(function, graphs):
        values = []
        for a, b in graphs:
            start = time.perf_counter()
            function(a, b)
            values.append((time.perf_counter() - start) * 1000)
        return {"mean_ms": statistics.mean(values), "median_ms": statistics.median(values),
                "max_ms": max(values)}

    if "python" in backends:
        configure_backend("python", lib)
        subgraph_executor._compare_with_python(*sample[0])  # Instanz erzeugen, nicht mitmessen
        result["python"] = timed(subgraph_executor._compare_with_python, sample)

    if "cpp" in backends and lib:
        configure_backend("cpp", lib)
        native = subgraph_executor._get_native()
        call = lambda a, b: subgraph_executor._compare_with_csubgraph(native, a, b)  # noqa: E731
        call(*sample[0])
        result["cpp"] = timed(call, sample)
        trivial = np.zeros((1, 1), dtype=int)
        result["cpp_overhead"] = timed(call, [(trivial, trivial)] * pairs)
    return result


# ---------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------

def percentile(values, q):
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def reference_backend(backends):
    """Bezugsimplementierung für den Speedup: python, sonst die erste."""
    return "python" if "python" in backends else backends[0]


def compute_summary(rows, backends, workers_list):
    """
    Kennzahlen je (Implementierung, Worker-Anzahl).

    speedup  = Gesamtzeit der Bezugsimplementierung / Gesamtzeit dieser Zeile
               (gleiche Worker-Anzahl, summiert über alle Anfragen)
    speedup_min/max = kleinster/größter Speedup einer einzelnen Anfrage
    matches_equal   = dieselben network_id je Anfrage wie die Bezugsimplementierung
    """
    ref = reference_backend(backends)
    summary = []
    for workers in workers_list:
        ref_rows = {r["query"]: r for r in rows if r["backend"] == ref and r["workers"] == workers}
        ref_total = sum(r["total_s"] for r in ref_rows.values())
        for backend in backends:
            subset = [r for r in rows if r["backend"] == backend and r["workers"] == workers]
            if not subset:
                continue
            totals = [r["total_s"] for r in subset]
            sum_total = sum(totals)
            sum_compare = sum(r["compare_s"] for r in subset)
            cands = [r["candidates"] for r in subset if r.get("candidates") is not None]
            sum_cands = sum(cands) if len(cands) == len(subset) else None

            per_query = [ref_rows[r["query"]]["total_s"] / r["total_s"]
                         for r in subset if r["query"] in ref_rows and r["total_s"] > 0]
            same = [r["query"] in ref_rows and r["match_ids"] == ref_rows[r["query"]]["match_ids"]
                    for r in subset]

            slope = corr = None
            if sum_cands is not None and len(subset) >= 3 and len(set(cands)) > 1:
                slope = float(np.polyfit(cands, totals, 1)[0]) * 1000
                corr = float(np.corrcoef(cands, totals)[0, 1])

            summary.append({
                "backend": backend,
                "workers": workers,
                "queries": len(subset),
                "sum_s": sum_total,
                "mean_s": statistics.mean(totals),
                "median_s": statistics.median(totals),
                "p95_s": percentile(totals, 0.95),
                "max_s": max(totals),
                "candidates_sum": sum_cands,
                "pairs_per_s": sum_cands / sum_total if sum_cands and sum_total > 0 else None,
                "ms_per_candidate": sum_total / sum_cands * 1000 if sum_cands else None,
                "compare_share": sum_compare / sum_total if sum_total > 0 else None,
                "serial_share": max(0.0, 1 - sum_compare / sum_total) if sum_total > 0 else None,
                "speedup": ref_total / sum_total if ref_total and sum_total > 0 else None,
                "speedup_min": min(per_query) if per_query else None,
                "speedup_max": max(per_query) if per_query else None,
                "matches_equal": all(same),
                "failed": sum(r["failed"] for r in subset),
                "slope_ms_per_candidate": slope,
                "corr_candidates_time": corr,
            })
    return summary


def print_summary(summary, ref):
    print("\n=== Zusammenfassung ===")
    print(f"{'Impl.':>7} {'Worker':>6} {'Summe[s]':>9} {'Mittel[s]':>10} {'Median[s]':>10} {'Max[s]':>8} "
          f"{'Speedup':>8} {'ms/Kand.':>9} {'seriell%':>9} {'Fehler':>7} {'Treffer=':>9}")
    for s in summary:
        kappa = f"{s['ms_per_candidate']:>9.3f}" if s["ms_per_candidate"] is not None else f"{'n/a':>9}"
        serial = f"{s['serial_share'] * 100:>8.0f}%" if s["serial_share"] is not None else f"{'n/a':>9}"
        speedup = f"{s['speedup']:>7.2f}x" if s["speedup"] is not None else f"{'n/a':>8}"
        print(f"{DISPLAY[s['backend']]:>7} {s['workers']:>6} {s['sum_s']:>9.0f} {s['mean_s']:>10.1f} "
              f"{s['median_s']:>10.1f} {s['max_s']:>8.1f} {speedup} {kappa} {serial} "
              f"{s['failed']:>7} {'ja' if s['matches_equal'] else 'NEIN':>9}")
    print(f"\nSpeedup = Gesamtzeit von {DISPLAY[ref]} / Gesamtzeit dieser Zeile (gleiche Worker-Anzahl).")
    print("seriell% = Anteil der Gesamtzeit außerhalb von compare_many (Laden, Treffer bauen).")
    print(f"Treffer= : gleiche network_id je Anfrage wie {DISPLAY[ref]}.")
    if any(s["failed"] for s in summary):
        print("ACHTUNG: Es gab fehlgeschlagene Einzelvergleiche (z.B. Timeout); Zeiten und Treffer sind "
              "nicht vollständig vergleichbar.")


def print_calibration(calibration, cpp_variant="Bibliothek"):
    if not calibration:
        return
    print(f"\n=== Mikro-Benchmark ({calibration['pairs']} Zufallspaare, im Hauptprozess) ===")
    labels = [("python", "Python, Einzelvergleich"), ("cpp", f"C++ ({cpp_variant}), Einzelvergleich"),
              ("cpp_overhead", f"C++ ({cpp_variant}), trivialer 1x1-Aufruf")]
    for key, label in labels:
        if key in calibration:
            c = calibration[key]
            print(f"  {label:<34} Median {c['median_ms']:>8.3f} ms  Mittel {c['mean_ms']:>8.3f} ms  "
                  f"Max {c['max_ms']:>8.3f} ms")


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def save_json(path, meta, rows, backends, workers_list, complete):
    """Schreibt Metadaten, Zusammenfassung und Einzelmessungen (atomar)."""
    data = {
        "meta": {**meta, "complete": complete, "reference_backend": reference_backend(backends)},
        "summary": compute_summary(rows, backends, workers_list),
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

def _context(data):
    """Gruppen (Implementierung, Worker-Anzahl) mit Beschriftung, Farbe und Messwerten."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    summary = data["summary"]
    rows = data["measurements"]
    multi_workers = len({s["workers"] for s in summary}) > 1
    colors = {"python": "#1f77b4", "cpp": "#d62728"}
    groups = []
    for s in summary:
        label = DISPLAY[s["backend"]] + (f", {s['workers']} Worker" if multi_workers else "")
        groups.append({
            "label": label,
            "color": colors[s["backend"]],
            "linestyle": "-" if s["workers"] == summary[0]["workers"] else "--",
            "summary": s,
            "rows": [r for r in rows if r["backend"] == s["backend"] and r["workers"] == s["workers"]],
        })
    return {"plt": plt, "groups": groups, "meta": data["meta"], "ref": data["meta"].get("reference_backend", "python")}


def draw_total(ax, ctx):
    groups = ctx["groups"]
    values = [g["summary"]["sum_s"] / 60 for g in groups]
    bars = ax.bar([g["label"] for g in groups], values, color=[g["color"] for g in groups])
    for bar, g in zip(bars, groups):
        speedup = g["summary"]["speedup"]
        if speedup is not None:
            ax.annotate(f"{speedup:.2f}x", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        ha="center", va="bottom", fontsize=10)
    ax.set_ylabel("Gesamtzeit aller Anfragen [min]")
    ax.set_title(f"Gesamtzeit und Speedup (Bezug: {DISPLAY[ctx['ref']]})")
    ax.set_ylim(0, max(values) * 1.15)
    ax.grid(alpha=0.3, axis="y")


def draw_distribution(ax, ctx):
    groups = ctx["groups"]
    ax.boxplot([[r["total_s"] for r in g["rows"]] for g in groups], showmeans=True)
    ax.set_xticklabels([g["label"] for g in groups])
    ax.set_yscale("log")
    ax.set_ylabel("Zeit pro Anfrage [s] (log)")
    ax.set_title("Verteilung der Antwortzeiten")
    ax.grid(alpha=0.3)


def draw_phases(ax, ctx):
    groups = ctx["groups"]
    labels = [g["label"] for g in groups]
    compare = np.array([statistics.mean(r["compare_s"] for r in g["rows"]) for g in groups])
    serial = np.array([statistics.mean(r["serial_s"] for r in g["rows"]) for g in groups])
    ax.bar(labels, compare, label="Vergleichen (parallel)", color="#2ca02c")
    ax.bar(labels, serial, bottom=compare, label="Laden, Treffer bauen (seriell)", color="#7f7f7f")
    ax.legend(fontsize=8)
    ax.set_ylabel("Mittlere Zeit pro Anfrage [s]")
    ax.set_title("Zeit je Phase")
    ax.grid(alpha=0.3, axis="y")


def draw_scaling(ax, ctx):
    plotted = False
    for g in ctx["groups"]:
        points = [(r["candidates"], r["total_s"]) for r in g["rows"] if r.get("candidates") is not None]
        if points:
            plotted = True
            xs, ys = zip(*points)
            ax.scatter(xs, ys, s=22, alpha=0.8, color=g["color"], label=g["label"])
    if plotted:
        ax.legend(fontsize=8)
    ax.set_xlabel("Kandidaten nach SQL-Vorauswahl")
    ax.set_ylabel("Zeit pro Anfrage [s]")
    ax.set_title("Skalierung mit der Suchraumgröße")
    ax.grid(alpha=0.3)


def draw_same_queries(ax, ctx):
    groups = ctx["groups"]
    base = {r["query"]: r["total_s"] for r in groups[0]["rows"]}
    order = sorted(base, key=base.get)
    position = {q: i + 1 for i, q in enumerate(order)}
    for g in groups:
        points = sorted((position[r["query"]], r["total_s"]) for r in g["rows"] if r["query"] in position)
        if points:
            xs, ys = zip(*points)
            ax.plot(xs, ys, marker="o", markersize=4, linewidth=1.2, color=g["color"],
                    linestyle=g["linestyle"], label=g["label"])
    ax.set_yscale("log")
    ax.set_xlabel(f"Anfragen, sortiert nach Zeit bei {groups[0]['label']}")
    ax.set_ylabel("Zeit pro Anfrage [s] (log)")
    ax.set_title("Dieselben Anfragen mit beiden Implementierungen")
    ax.grid(alpha=0.3)
    ax.legend()


DRAWERS = {
    "gesamtzeit_speedup": draw_total,
    "verteilung_antwortzeiten": draw_distribution,
    "phasen": draw_phases,
    "skalierung_suchraum": draw_scaling,
    "gleiche_anfragen": draw_same_queries,
}


def build_figures(data):
    """
    Erzeugt die Diagramme aus den JSON-Daten.

    Returns:
        (Liste der Seiten für das PDF, dict Name -> Einzeldiagramm)
    """
    ctx = _context(data)
    plt = ctx["plt"]
    meta = data["meta"]
    queries = len(ctx["groups"][0]["rows"])
    status = "" if meta.get("complete", True) else " (unvollständig)"
    title = (f"Subgraph-Suche Python vs. C++: {queries} Anfragen aus der Datenbank, "
             f"mind. {meta.get('min_nodes', '?')} Knoten{status}")

    fig1, axes = plt.subplots(2, 2, figsize=(11.69, 8.27))  # A4 quer
    fig1.suptitle(title, fontsize=13)
    for ax, name in zip(axes.flat, ["gesamtzeit_speedup", "verteilung_antwortzeiten", "phasen",
                                    "skalierung_suchraum"]):
        DRAWERS[name](ax, ctx)
    fig1.tight_layout(rect=(0, 0, 1, 0.95))

    fig2, ax = plt.subplots(figsize=(11.69, 8.27))
    draw_same_queries(ax, ctx)
    fig2.tight_layout()

    singles = {}
    for name, drawer in DRAWERS.items():
        fig, ax = plt.subplots(figsize=(7.0, 4.6))
        drawer(ax, ctx)
        fig.tight_layout()
        singles[name] = fig
    return [fig1, fig2], singles


def save_figures(data, pdf_path, results_dir):
    from matplotlib.backends.backend_pdf import PdfPages
    import matplotlib.pyplot as plt

    pages, singles = build_figures(data)
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(pdf_path) as pdf:
        for fig in pages:
            pdf.savefig(fig)
            plt.close(fig)
    written = [pdf_path]
    for name, fig in singles.items():
        target = Path(results_dir) / SINGLE_PLOTS[name]
        fig.savefig(target)
        plt.close(fig)
        written.append(target)
    return written


# ---------------------------------------------------------------------------
# LaTeX-Tabellen für gen-db.tex
# ---------------------------------------------------------------------------

def _num(value, digits=1):
    """Zahl im deutschen Format ($1.234{,}5$): Tausenderpunkt, Dezimalkomma."""
    if value is None:
        return "--"
    text = f"{value:,.{digits}f}".replace(",", "#").replace(".", "{,}").replace("#", ".")
    return text


def cpp_variant_name(meta):
    """Name der Variante: "CLI" für ältere Messläufe (Prozess je Vergleich), sonst "Bibliothek"."""
    return "CLI" if meta.get("csubgraph_cli") and not meta.get("csubgraph_lib") else "Bibliothek"


def write_latex_tables(data, path):
    """Schreibt Kennzahlen- und Mikro-Benchmark-Tabelle als \\input-fähiges Fragment."""
    summary = data["summary"]
    meta = data["meta"]
    ref = DISPLAY[meta.get("reference_backend", "python")]
    queries = summary[0]["queries"]
    cands = summary[0]["candidates_sum"]
    lines = [
        "% Automatisch erzeugt von src/experiment_search_backends.py -- nicht von Hand ändern.",
        f"% Messlauf: {meta.get('created', '?')}, Seed {meta.get('seed', '?')}",
        "\\begin{table}[h]",
        "\t\\centering",
        "\t\\small",
        f"\t\\caption{{Kennzahlen der Suche je Implementierung (jeweils ${queries}$ Anfragen, "
        f"$C_\\Sigma = {_num(cands, 0)}$ Kandidaten, Speedup $S$ relativ zu {ref}).}}",
        "\t\\label{tab:backend_summary}",
        "\t\\begin{tabular}{@{}lrrrrrrrrr@{}}",
        "\t\t\\toprule",
        "\t\tVariante & $p$ & $T$ [s] & Mittel [s] & Median [s] & Max. [s] & $S$ & $\\Theta$ [1/s] "
        "& $\\kappa$ [ms] & seriell [\\%] \\\\",
        "\t\t\\midrule",
    ]
    for s in summary:
        serial = _num(s["serial_share"] * 100, 1) if s["serial_share"] is not None else "--"
        lines.append(
            f"\t\t{DISPLAY[s['backend']]} & {s['workers']} & {_num(s['sum_s'], 0)} & "
            f"{_num(s['mean_s'])} & {_num(s['median_s'])} & {_num(s['max_s'])} & {_num(s['speedup'], 2)} & "
            f"{_num(s['pairs_per_s'], 0)} & {_num(s['ms_per_candidate'], 3)} & {serial} \\\\"
        )
    lines += ["\t\t\\bottomrule", "\t\\end{tabular}", "\\end{table}"]

    calibration = meta.get("calibration")
    if calibration:
        lines += [
            "",
            "\\begin{table}[h]",
            "\t\\centering",
            "\t\\small",
            f"\t\\caption{{Zeit je Einzelvergleich im Hauptprozess ({calibration['pairs']} Zufallspaare "
            "mit $n_A\\in\\{15,\\dots,19\\}$, $n_B=20$, Kantenwahrscheinlichkeit $0{,}3$).}",
            "\t\\label{tab:backend_calibration}",
            "\t\\begin{tabular}{@{}lrrr@{}}",
            "\t\t\\toprule",
            "\t\tMessung & Median [ms] & Mittel [ms] & Max. [ms] \\\\",
            "\t\t\\midrule",
        ]
        variant = cpp_variant_name(meta)
        for key, label in [("python", "Python, Einzelvergleich"), ("cpp", f"C++ ({variant}), Einzelvergleich"),
                           ("cpp_overhead", f"C++ ({variant}), trivialer $1\\times1$-Aufruf")]:
            if key in calibration:
                c = calibration[key]
                lines.append(f"\t\t{label} & {_num(c['median_ms'], 3)} & {_num(c['mean_ms'], 3)} & "
                             f"{_num(c['max_ms'], 3)} \\\\")
        lines += ["\t\t\\bottomrule", "\t\\end{tabular}", "\\end{table}"]

    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return Path(path)


def write_outputs(json_path, pdf_path, results_dir):
    """PDF, Einzeldiagramme und Tabellen aus einer JSON-Datei erzeugen."""
    data = load_json(json_path)
    tex_path = Path(results_dir) / (Path(pdf_path).stem + "_tabellen.tex")
    written = save_figures(data, pdf_path, results_dir)
    written.append(write_latex_tables(data, tex_path))
    return written


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queries", type=int, default=6,
                        help="Anzahl Suchanfragen je Messreihe (Standard 6, wie bei den Worker-Messungen)")
    parser.add_argument("--workers", type=int, nargs="+", default=[2], help="Worker-Anzahlen (Standard: 2)")
    parser.add_argument("--backends", nargs="+", choices=BACKENDS, default=list(BACKENDS),
                        help="Reihenfolge der Implementierungen (Standard: python cpp)")
    parser.add_argument("--csubgraph-lib-path", default=None,
                        help="Pfad zu libsubgraphlib.a (Datei oder Ordner); Standard: CSUBGRAPH_LIB_PATH aus .env")
    parser.add_argument("--min-nodes", type=int, default=15, help="Mindestanzahl Knoten der Query")
    parser.add_argument("--max-nodes", type=int, default=None, help="Optionale Obergrenze der Knotenanzahl")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--warmup", type=int, default=1, help="Verworfene Aufwärm-Suchen je Messreihe")
    parser.add_argument("--calibration-pairs", type=int, default=200,
                        help="Zufallspaare für den Mikro-Benchmark (0 = überspringen)")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR),
                        help="Zielverzeichnis (Standard: src/results)")
    parser.add_argument("--plot-from", metavar="JSON",
                        help="Nur PDF, Einzeldiagramme und Tabellen aus einer JSON-Datei erzeugen")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)

    if args.plot_from:
        stem = Path(args.plot_from).stem
        for path in write_outputs(args.plot_from, results_dir / f"{stem}.pdf", results_dir):
            print(f"geschrieben: {path}")
        return

    if args.min_nodes < 15:
        parser.error("--min-nodes muss mindestens 15 sein")
    if args.max_nodes is not None and args.max_nodes < args.min_nodes:
        parser.error("--max-nodes muss >= --min-nodes sein")
    if len(set(args.backends)) != len(args.backends):
        parser.error("--backends enthält eine Implementierung doppelt")

    lib, lib_setting = resolve_lib(args.csubgraph_lib_path)
    if "cpp" in args.backends and not lib:
        raise SystemExit(
            f"libsubgraphlib.a nicht gefunden (Einstellung: {lib_setting!r}). "
            "CSUBGRAPH_LIB_PATH in der .env oder --csubgraph-lib-path auf libsubgraphlib.a setzen, "
            "oder --backends python wählen. Ein stiller Fallback auf Python würde den Vergleich verfälschen."
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = results_dir / f"search_backends_{stamp}.json"
    pdf_path = results_dir / f"search_backends_{stamp}.pdf"

    queries = load_queries_from_db(args.queries, args.min_nodes, args.max_nodes, args.seed)
    print(f"{len(queries)} Anfragen aus der Datenbank (mind. {args.min_nodes} Knoten), Seed {args.seed}, "
          f"Implementierungen {args.backends}, Worker {args.workers}, Warm-up {args.warmup}")
    if lib:
        print(f"csubgraph: {lib}")

    meta = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "seed": args.seed,
        "queries": len(queries),
        "backends": args.backends,
        "workers": args.workers,
        "min_nodes": args.min_nodes,
        "max_nodes": args.max_nodes,
        "warmup": args.warmup,
        "csubgraph_lib": lib,
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "query_network_ids": [nid for nid, _, _ in queries],
    }

    if args.calibration_pairs > 0:
        print("\nMikro-Benchmark ...", flush=True)
        meta["calibration"] = calibrate(args.backends, lib, args.calibration_pairs, args.seed)
        print_calibration(meta["calibration"])

    rows = run_experiment(queries, args.backends, args.workers, args.warmup, lib, meta, json_path)
    print_summary(compute_summary(rows, args.backends, args.workers), reference_backend(args.backends))

    print(f"\nJSON: {json_path}")
    try:
        for path in write_outputs(json_path, pdf_path, results_dir):
            print(f"geschrieben: {path}")
    except ImportError:
        print("Diagramme nicht erzeugt: matplotlib fehlt (pip install matplotlib). "
              f"Danach: python src/experiment_search_backends.py --plot-from {json_path}")


if __name__ == "__main__":
    main()
