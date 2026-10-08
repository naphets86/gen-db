"""
Experiment: Multi-Omics-Suche (Mehrschicht-Netzwerke), Python- gegen C++-Implementierung.

Erweiterung von experiment_search_workers.py und experiment_search_backends.py auf die
Multi-Omics-Suche (crud.search_multiomics). Die Implementierung der Relation
(``multiomics_python`` oder ``MultiOmics`` aus csubgraph) wird wie im Betrieb über
CSUBGRAPH_LIB_PATH gewählt. Das Experiment besteht aus sieben Teilexperimenten
(``--only`` wählt einzelne aus):

correctness  Korrektheit ohne Datenbank: Python-Referenz gegen C++ auf Zufallspaaren,
             eingebetteten Paaren (kohärent / unabhängig), identischen und umgekehrten
             Paaren, beide Modi. Geprüft werden außerdem Invarianten (Symmetrie,
             kohärent => unabhängig, erwartete Ergebnisse der eingebetteten Paare).
micro        Mikro-Benchmark ohne Datenbank: Zeit je Einzelvergleich in Abhängigkeit von
             Schichtzahl L, Knotenzahl n, Modus und Paartyp (Zufall = Worst Case ohne
             frühen Treffer, eingebettet = Treffer), dazu die Aufrufkosten (trivialer 1x1-Aufruf).
search       Ende-zu-Ende-Suche über crud.search_multiomics: Gitter aus Anfragen
             (Schichtzahl x Knotenzahl x Typ) x Implementierung x Modus x Wiederholungen,
             Phasen (Laden, Vergleichen, Treffer bauen), Kandidatenzahl, Treffer, Speedup mit
             Konfidenzintervall, Übereinstimmung der Treffer, Trefferquote der eingebetteten
             Netzwerke (Ground Truth), Selektivität des SQL-Vorfilters.
workers      Skalierung mit 1, 2, 3, ... Workern (Speedup, Effizienz, serieller Anteil nach Amdahl).
chunksize    Einfluss der Chunk-Größe von compare_many_multiomics.
dbsize       Skalierung mit der Datenbankgröße (Anzahl Netzwerke), lineare Anpassung.

Versuchsaufbau
- Datenbank: DATABASE_* aus der .env. Das Experiment legt synthetische Multi-Omics-Netzwerke
  mit network_type 'multi_omics_experiment' an (Zufallsnetzwerke ``mo_exp_rand_...``, Anzahl
  --networks, deterministisch aus --seed) und je eingebetteter Anfrage Netzwerke mit bekannter
  Lösung (``mo_exp_plant_...``): identische Kopie, kohärent eingebettet, nur unabhängig
  eingebettet. Damit gibt es eine Ground Truth (erwartete Treffer) zusätzlich zum Vergleich
  Python gegen C++. Vorhandene andere Netzwerke werden nicht verändert.
- Anfragen entstehen aus dem Seed (nicht aus der Datenbank). Je (Schichtzahl, Knotenzahl) gibt
  es eine Zufallsanfrage ohne eingebettete Treffer und eine eingebettete Anfrage.
- Einbetten: Die Relation vergleicht Zeilenkomponenten (Spaltenbitmuster). Ein Netzwerk B enthält
  A, wenn ein benachbartes Paar von Zeilenkomponenten von A als zyklisch benachbartes Paar in B
  vorkommt. Eingebettet wird, indem zwei benachbarte Spalten von A in zwei benachbarte Spalten
  von B kopiert werden (Zeilen ab n_A bleiben 0). Kohärent: alle Schichten am selben Paar und
  derselben Position; unabhängig: je Schicht eine andere Position.
- Wiederholungen: Jede Messung wird --reps mal wiederholt; die Reihenfolge der Implementierungen
  wechselt je Wiederholung, die Reihenfolge der Anfragen wird je Wiederholung zufällig (aus dem
  Seed) gemischt. Je Messreihe gibt es eine verworfene Aufwärmanfrage.
- Gemessen wird die Wanduhrzeit von crud.search_multiomics() (SQL, Vergleiche, Prozesskommunikation,
  Trefferliste). Die Phasen: Laden (bis zum Start der Vergleiche), Vergleichen (compare_many_multiomics),
  Treffer bauen (Rest).
- Es wird geprüft, dass wirklich die gewünschte Implementierung läuft (kein stiller Fallback von
  cpp auf python), auch in den Worker-Prozessen.

Aufruf (im Projektordner, damit die .env gefunden wird):
    python src/experiment_search_multiomics.py                  # vollständig, dauert Stunden
    python src/experiment_search_multiomics.py --quick          # kleiner Vorabtest
    python src/experiment_search_multiomics.py --only correctness micro
    python src/experiment_search_multiomics.py --backends python --networks 5000
    python src/experiment_search_multiomics.py --csubgraph-lib-path C:\\...\\libsubgraphlib.a
    python src/experiment_search_multiomics.py --cleanup-only   # Experiment-Netzwerke löschen

Ergebnisse (src/results/, Dateiname mit Zeitstempel):
- search_multiomics_<zeit>.json          : Metadaten, Anfragen, alle Einzelmessungen, Auswertung
- search_multiomics_<zeit>.pdf           : Diagramme auf mehreren Seiten
- search_multiomics_<zeit>.txt           : Textbericht (Kennzahlen aller Teilexperimente)
- search_multiomics_<zeit>_tabellen.tex  : Tabellen für gen-db.tex (\\input{...})
- plot11_multiomics_*.pdf ... plot26_multiomics_*.pdf : Einzeldiagramme für \\includegraphics

Die JSON-Datei wird nach jeder Messung aktualisiert (ein Abbruch verliert keine Werte). Aus einer
vorhandenen JSON-Datei lassen sich PDF, Diagramme, Tabellen und Bericht ohne neuen Messlauf erzeugen:
    python src/experiment_search_multiomics.py --plot-from src/results/search_multiomics_<zeit>.json

Der Server darf während des Experiments nicht laufen (Worker würden konkurrieren). Die Experiment-
Netzwerke bleiben standardmäßig in der Datenbank (Wiederholbarkeit, schneller Neustart);
--cleanup entfernt sie am Ende, --rebuild-data erzeugt sie neu. Für die Diagramme wird matplotlib
benötigt (pip install matplotlib). Die Mikro-Benchmarks und die Korrektheitsprüfung laufen im
Hauptprozess; für C++ wird libsubgraphlib.a mit MultiOmics benötigt (csubgraph neu bauen).
"""

import argparse
import hashlib
import json
import logging
import math
import os
import platform
import re
import statistics
import sys
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import numpy as np

# Dieses Skript liegt in src/, daneben liegt das Paket backend/
SRC_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC_DIR))

from backend import config as backend_config  # noqa: E402
from backend import crud, csubgraph_native, multiomics_python, subgraph_executor  # noqa: E402
from psycopg2.extras import execute_values  # noqa: E402

DEFAULT_RESULTS_DIR = SRC_DIR / "results"
BACKENDS = ("python", "cpp")
# Name des Multi-Omics-Algorithmus in subgraph_executor.get_multiomics_backend_name()
EXPECTED_NAME = {"python": "python", "cpp": "csubgraph"}
DISPLAY = {"python": "Python", "cpp": "C++"}
COLORS = {"python": "#1f77b4", "cpp": "#d62728"}
MODES = tuple(multiomics_python.MODES)  # ("coherent", "independent")
MODE_DISPLAY = {"coherent": "kohärent", "independent": "unabhängig"}
KIND_DISPLAY = {"random": "Zufall", "embedded": "eingebettet"}
PLANT_DISPLAY = {"exact": "identisch", "coherent": "kohärent", "independent": "unabhängig",
                 "reversed": "umgekehrt"}
PHASES = ("correctness", "micro", "search", "workers", "chunksize", "dbsize")
DB_PHASES = ("search", "workers", "chunksize", "dbsize")
FAILED_RE = re.compile(r"(\d+) of (\d+) comparisons failed")

EXPERIMENT_TYPE = "multi_omics_experiment"
RAND_PREFIX = "mo_exp_rand_"
PLANT_PREFIX = "mo_exp_plant_"

# Schichten (Name, Kantenwahrscheinlichkeit)
LAYER_POOL = [("Genom", 0.12), ("Transkriptom", 0.25), ("Proteom", 0.30),
              ("Metabolom", 0.20), ("Epigenom", 0.15), ("Lipidom", 0.22)]
DENSITY = dict(LAYER_POOL)
POOL_NAMES = [name for name, _ in LAYER_POOL]
ORGANISMS = ["Homo sapiens", "Mus musculus", "E. coli", "S. cerevisiae",
             "D. melanogaster", "C. elegans", "A. thaliana"]
LABELS = [f"Knoten{i + 1:02d}" for i in range(multiomics_python.MAX_NODES)]

# Ergebnisse, die als Treffer gelten (Namen der C++-Bibliothek)
MATCH_NAMES = {"KEEP_B", "EQUAL_KEEP_A", "EQUAL_KEEP_B", "IDENTICAL"}
EXPECTED_RESULTS = {
    "coherent": MATCH_NAMES,
    "exact": {"IDENTICAL"},
    "reversed": {"KEEP_A", "EQUAL_KEEP_A", "EQUAL_KEEP_B", "IDENTICAL"},
}

SINGLE_PLOTS = {
    "gesamtzeit_speedup": "plot11_multiomics_gesamtzeit_speedup.pdf",
    "verteilung_antwortzeiten": "plot12_multiomics_verteilung_antwortzeiten.pdf",
    "phasen": "plot13_multiomics_phasen.pdf",
    "skalierung_kandidaten": "plot14_multiomics_skalierung_kandidaten.pdf",
    "schichten": "plot15_multiomics_schichten.pdf",
    "knoten": "plot16_multiomics_knoten.pdf",
    "mikro_speedup_zufall": "plot17_multiomics_mikro_speedup_zufall.pdf",
    "mikro_speedup_eingebettet": "plot18_multiomics_mikro_speedup_eingebettet.pdf",
    "mikro_zeit": "plot19_multiomics_mikro_zeit.pdf",
    "workers": "plot20_multiomics_workers.pdf",
    "chunksize": "plot21_multiomics_chunksize.pdf",
    "dbsize": "plot22_multiomics_dbsize.pdf",
    "selektivitaet": "plot23_multiomics_selektivitaet.pdf",
    "modi": "plot24_multiomics_modi.pdf",
    "korrektheit": "plot25_multiomics_korrektheit.pdf",
    "treffer_erwartet": "plot26_multiomics_treffer_erwartet.pdf",
}


# ---------------------------------------------------------------------------
# Statistik-Hilfen
# ---------------------------------------------------------------------------

T_CRIT = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262}


def mean_ci(values):
    """Mittelwert und 95-%-Konfidenzintervall (t-Verteilung) -> (mittel, unten, oben)."""
    values = [v for v in values if v is not None]
    n = len(values)
    if n == 0:
        return None, None, None
    mean = statistics.fmean(values)
    if n < 2:
        return mean, mean, mean
    df = n - 1
    t = T_CRIT.get(df, 2.0 if df < 30 else 1.96)
    half = t * statistics.stdev(values) / math.sqrt(n)
    return mean, mean - half, mean + half


def percentile(values, q):
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def geomean(values):
    values = [v for v in values if v is not None and v > 0]
    if not values:
        return None
    return math.exp(statistics.fmean(math.log(v) for v in values))


def bootstrap_ci(values, statistic, seed=0, rounds=2000):
    """95-%-Bootstrap-Intervall einer Kennzahl -> (unten, oben) oder (None, None)."""
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return None, None
    rng = np.random.default_rng(seed)
    array = np.array(values, dtype=float)
    stats = []
    for _ in range(rounds):
        sample = array[rng.integers(0, len(array), len(array))]
        stats.append(statistic(sample.tolist()))
    stats = [s for s in stats if s is not None]
    if not stats:
        return None, None
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def linear_fit(xs, ys):
    """Gerade y = a*x + b -> (a, b, R^2) oder (None, None, None)."""
    if len(xs) < 3 or len(set(xs)) < 2:
        return None, None, None
    slope, intercept = np.polyfit(xs, ys, 1)
    predicted = slope * np.array(xs) + intercept
    ss_res = float(np.sum((np.array(ys) - predicted) ** 2))
    ss_tot = float(np.sum((np.array(ys) - np.mean(ys)) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None
    return float(slope), float(intercept), r2


def pick_evenly(items, count):
    """Gleichmäßig verteilte Auswahl von höchstens count Elementen (reproduzierbar)."""
    if count >= len(items):
        return list(items)
    indices = sorted(set(int(i) for i in np.linspace(0, len(items) - 1, count).round()))
    return [items[i] for i in indices]


def time_stats(values):
    """Kennzahlen einer Liste von Zeiten in ms."""
    mean, low, high = mean_ci(values)
    return {
        "median_ms": statistics.median(values), "mean_ms": mean,
        "std_ms": statistics.stdev(values) if len(values) > 1 else 0.0,
        "p95_ms": percentile(values, 0.95), "min_ms": min(values), "max_ms": max(values),
        "ci_low_ms": low, "ci_high_ms": high,
    }


# ---------------------------------------------------------------------------
# Synthetische Multi-Omics-Daten
# ---------------------------------------------------------------------------

def random_layer(rng, n, p):
    """Zufällige gerichtete Schicht ohne Schleifen (wie db-populate.py)."""
    matrix = (rng.random((n, n)) < p).astype(int)
    np.fill_diagonal(matrix, 0)
    return matrix


def random_stack(rng, n, names):
    return [random_layer(rng, n, DENSITY.get(name, 0.25)) for name in names]


def np_components(matrix):
    """Zeilenkomponenten (Spaltenbitmuster) wie multiomics_python.row_components, vektorisiert."""
    n = matrix.shape[0]
    weights = np.left_shift(np.int64(1), np.arange(n, dtype=np.int64))
    return (matrix.astype(np.int64) * weights[:, None]).sum(axis=0).tolist()


def embed_stack(rng, stack_a, n_b, names, kind):
    """
    Erzeugt einen Schichtstapel B (n_b Knoten), der A (n_a <= n_b Knoten) enthält.

    kind 'coherent'    : alle Schichten an derselben Position und demselben Spaltenpaar von A
    kind 'independent' : je Schicht andere Position und anderes Spaltenpaar (meist nur im
                         Modus 'independent' ein Treffer)
    kind 'exact'       : identische Kopie (n_b muss n_a entsprechen)

    Zwei benachbarte Spalten von A werden in zwei benachbarte Spalten von B kopiert, die Zeilen
    ab n_a bleiben 0; dadurch sind die Zeilenkomponenten dieser Spalten in A und B gleich.
    """
    if kind == "exact":
        return [m.copy() for m in stack_a]
    n_a = stack_a[0].shape[0]
    base_position = int(rng.integers(0, n_b))
    base_pair = int(rng.integers(0, n_a - 1))
    result = []
    for index, (matrix_a, name) in enumerate(zip(stack_a, names)):
        matrix_b = random_layer(rng, n_b, DENSITY.get(name, 0.25))
        if kind == "coherent":
            position, pair = base_position, base_pair
        else:
            position = (base_position + index) % n_b
            pair = (base_pair + index) % (n_a - 1)
        for offset in (0, 1):
            column = (position + offset) % n_b
            matrix_b[:, column] = 0
            matrix_b[:n_a, column] = matrix_a[:, pair + offset]
        result.append(matrix_b)
    return result


def pick_names(rng, count):
    """Zufällige Schichtnamen aus dem Pool, in Pool-Reihenfolge."""
    indices = sorted(int(i) for i in rng.choice(len(POOL_NAMES), size=count, replace=False))
    return [POOL_NAMES[i] for i in indices]


def to_lists(stack):
    return [m.tolist() for m in stack]


def sanity_check_components(seed):
    """Prüft, dass die vektorisierte Berechnung der Zeilenkomponenten der Referenz entspricht."""
    rng = np.random.default_rng([seed, 1])
    for n in (1, 2, 7, 20, 40, 63):
        matrix = random_layer(rng, n, 0.3)
        if np_components(matrix) != list(multiomics_python.row_components(matrix.tolist())):
            raise SystemExit(f"Zeilenkomponenten stimmen für n={n} nicht überein (Programmfehler).")


# ---------------------------------------------------------------------------
# Anfragen (aus dem Seed) mit eingebetteten Netzwerken (Ground Truth)
# ---------------------------------------------------------------------------

def make_plants(rng, spec, per_kind, extra_nodes):
    """
    Eingebettete Netzwerke zu einer Anfrage: 1 identische Kopie, per_kind kohärent und (ab zwei
    Schichten) per_kind nur unabhängig eingebettete. Je Plant wird mit der Python-Referenz
    festgehalten, in welchem Modus die Anfrage enthalten ist (Ground Truth).
    """
    names, stack, n = spec["names"], spec["stack"], spec["nodes"]
    query_lists = to_lists(stack)
    plan = [("exact", 1), ("coherent", per_kind)]
    if len(names) >= 2:
        plan.append(("independent", per_kind))
    plants = []
    for kind, count in plan:
        for k in range(count):
            n_b = n if kind == "exact" else min(multiomics_python.MAX_NODES,
                                                n + int(rng.integers(0, extra_nodes + 1)))
            extra = [name for name in POOL_NAMES if name not in names and rng.random() < 0.5]
            all_names = [name for name in POOL_NAMES if name in names or name in extra]
            embedded = dict(zip(names, embed_stack(rng, stack, n_b, names, kind)))
            full = [embedded[name] if name in embedded else random_layer(rng, n_b, DENSITY[name])
                    for name in all_names]
            valid = {mode: bool(multiomics_python.contains(
                query_lists, [embedded[name].tolist() for name in names], mode)) for mode in MODES}
            plants.append({"kind": kind, "index": k, "nodes": n_b, "names": all_names,
                           "stack": full, "valid": valid, "id": None})
    return plants


def build_query_specs(seed, sizes, layer_counts, per_kind, extra_nodes):
    """
    Anfragen: je (Schichtzahl, Knotenzahl) eine Zufallsanfrage ('random', ohne eingebettete
    Treffer) und eine eingebettete Anfrage ('embedded').
    """
    specs = []
    for layers in layer_counts:
        for n in sizes:
            for kind in ("random", "embedded"):
                rng = np.random.default_rng([seed, 11, layers, n, 0 if kind == "random" else 1])
                names = pick_names(rng, layers)
                stack = random_stack(rng, n, names)
                spec = {
                    "index": len(specs), "kind": kind, "layers": layers, "nodes": n,
                    "names": names, "labels": LABELS[:n], "stack": stack,
                    "matrices": to_lists(stack), "edges": int(sum(int(m.sum()) for m in stack)),
                    "plants": [], "expected": {mode: [] for mode in MODES},
                }
                if kind == "embedded":
                    spec["plants"] = make_plants(rng, spec, per_kind, extra_nodes)
                specs.append(spec)
    return specs


def public_spec(spec):
    """Anfrage ohne Matrizen für die JSON-Datei."""
    return {
        "index": spec["index"], "kind": spec["kind"], "layers": spec["layers"], "nodes": spec["nodes"],
        "names": spec["names"], "edges": spec["edges"], "expected": spec["expected"],
        "plants": [{"id": p["id"], "kind": p["kind"], "nodes": p["nodes"], "names": p["names"],
                    "valid": p["valid"]} for p in spec["plants"]],
    }


# ---------------------------------------------------------------------------
# Datenbank: Experiment-Netzwerke anlegen, verkleinern, löschen
# ---------------------------------------------------------------------------

def population_tag(args):
    return f"s{args.seed}n{args.min_nodes}-{args.max_nodes}l{args.min_layers}-{args.max_layers}"


def random_prefix(tag):
    return f"{RAND_PREFIX}{tag}_"


def generate_random_network(args, tag, index):
    """Zufallsnetzwerk Nummer index (deterministisch aus Seed und Index)."""
    rng = np.random.default_rng([args.seed, 7, index])
    n = int(rng.integers(args.min_nodes, args.max_nodes + 1))
    count = int(rng.integers(args.min_layers, args.max_layers + 1))
    names = pick_names(rng, count)
    stack = random_stack(rng, n, names)
    organism = ORGANISMS[int(rng.integers(0, len(ORGANISMS)))]
    return {
        "name": f"{random_prefix(tag)}{index:07d}", "organism": organism,
        "description": f"Synthetisches Multi-Omics-Netzwerk ({count} Schichten, {n} Knoten)",
        "labels": LABELS[:n], "names": names, "stack": stack,
    }


def insert_networks(records):
    """Fügt Multi-Omics-Netzwerke stapelweise ein (biological_networks, omics_networks, omics_layers)."""
    if not records:
        return []
    with crud.get_db_connection() as conn:
        cursor = crud.get_db_cursor(conn)
        cursor.execute(
            "SELECT nextval(pg_get_serial_sequence('biological_networks', 'network_id')) AS id "
            "FROM generate_series(1, %s)", (len(records),))
        ids = sorted(int(row["id"]) for row in cursor.fetchall())

        network_rows, omics_rows, layer_rows = [], [], []
        for network_id, record in zip(ids, records):
            components = [np_components(m) for m in record["stack"]]
            edges = int(sum(int(m.sum()) for m in record["stack"]))
            network_rows.append((network_id, record["name"], EXPERIMENT_TYPE, record["organism"],
                                 record["description"], len(record["labels"]), edges))
            omics_rows.append((network_id, record["labels"], len(record["names"]),
                               crud.compute_signature_hash(components)))
            for index, (name, matrix, comps) in enumerate(zip(record["names"], record["stack"], components)):
                layer_rows.append((network_id, index, name, matrix.tolist(), comps, int(matrix.sum())))

        execute_values(
            cursor,
            "INSERT INTO biological_networks (network_id, name, network_type, organism, description, "
            "node_count, edge_count) VALUES %s", network_rows, page_size=1000)
        execute_values(
            cursor,
            "INSERT INTO omics_networks (network_id, node_labels, layer_count, signature_hash) VALUES %s",
            omics_rows, template="(%s, %s::text[], %s, %s)", page_size=1000)
        execute_values(
            cursor,
            "INSERT INTO omics_layers (network_id, layer_index, layer_name, adjacency_matrix, "
            "row_components, edge_count) VALUES %s",
            layer_rows, template="(%s, %s, %s, %s::integer[][], %s::bigint[], %s)", page_size=500)
    return ids


def delete_experiment(condition_sql, params):
    """Löscht Experiment-Netzwerke (CASCADE entfernt die Schichten); gibt die Anzahl zurück."""
    with crud.get_db_connection() as conn:
        cursor = crud.get_db_cursor(conn)
        cursor.execute(
            f"DELETE FROM biological_networks WHERE network_type = %s AND {condition_sql}",
            (EXPERIMENT_TYPE, *params))
        return cursor.rowcount


def scalar(sql, params=()):
    with crud.get_db_connection() as conn:
        cursor = crud.get_db_cursor(conn)
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return list(row.values())[0]


def count_omics_networks():
    return int(scalar("SELECT COUNT(*) FROM omics_networks"))


def analyze_tables():
    """Aktualisiert die Planer-Statistik nach dem Anlegen oder Löschen vieler Zeilen."""
    with crud.get_db_connection() as conn:
        cursor = conn.cursor()
        for table in ("biological_networks", "omics_networks", "omics_layers"):
            cursor.execute(f"ANALYZE {table}")


def set_random_count(args, count, verbose=True):
    """Stellt die Zahl der Zufallsnetzwerke auf count (Netzwerke mit höchstem Index werden gelöscht)."""
    tag = population_tag(args)
    prefix = random_prefix(tag)
    delete_experiment("name LIKE %s AND name NOT LIKE %s", (RAND_PREFIX + "%", prefix + "%"))
    current = int(scalar(
        "SELECT COUNT(*) FROM biological_networks WHERE network_type = %s AND name LIKE %s",
        (EXPERIMENT_TYPE, prefix + "%")))
    if current > count:
        threshold = f"{prefix}{count - 1:07d}" if count > 0 else prefix
        delete_experiment("name LIKE %s AND name > %s", (prefix + "%", threshold))
    elif current < count:
        started = time.perf_counter()
        batch = 2000
        for start in range(current, count, batch):
            stop = min(count, start + batch)
            insert_networks([generate_random_network(args, tag, i) for i in range(start, stop)])
            if verbose:
                print(f"  Zufallsnetzwerke {stop}/{count} ({time.perf_counter() - started:.0f} s)", flush=True)
    analyze_tables()


def insert_plants(args, specs):
    """Legt die eingebetteten Netzwerke aller Anfragen neu an und trägt die IDs in die Anfragen ein."""
    delete_experiment("name LIKE %s", (PLANT_PREFIX + "%",))
    records, owners = [], []
    for spec in specs:
        for plant in spec["plants"]:
            records.append({
                "name": f"{PLANT_PREFIX}{args.seed}_q{spec['index']:03d}_{plant['kind']}_{plant['index']}",
                "organism": "Homo sapiens",
                "description": f"Eingebettet ({plant['kind']}) für Anfrage {spec['index']}",
                "labels": LABELS[:plant["nodes"]], "names": plant["names"], "stack": plant["stack"],
            })
            owners.append((spec, plant))
    ids = insert_networks(records)
    for network_id, (spec, plant) in zip(ids, owners):
        plant["id"] = network_id
        for mode in MODES:
            if plant["valid"][mode]:
                spec["expected"][mode].append(network_id)
    analyze_tables()


def prepare_population(args, specs):
    """Bereitet die Datenbank vor: Zufallsnetzwerke, eingebettete Netzwerke, Zählung."""
    try:
        if args.rebuild_data:
            removed = delete_experiment("TRUE", ())
            print(f"  {removed} Experiment-Netzwerke gelöscht (--rebuild-data)")
        set_random_count(args, args.networks)
        insert_plants(args, specs)
        return count_omics_networks()
    except SystemExit:
        raise
    except Exception as error:  # Verbindungs- oder Schemafehler
        raise SystemExit(
            f"Datenbankzugriff fehlgeschlagen: {error}\n"
            "DATABASE_* in der .env prüfen und init-db.sql (Tabellen omics_networks, omics_layers) einspielen."
        )


# ---------------------------------------------------------------------------
# Auswahl der Implementierung
# ---------------------------------------------------------------------------

def resolve_lib(path_argument):
    """libsubgraphlib.a: --csubgraph-lib-path, sonst CSUBGRAPH_LIB_PATH aus .env -> (Pfad|None, Einstellung)."""
    setting = path_argument
    if not setting:
        setting = getattr(backend_config.get_config(), "csubgraph_lib_path", None)
    lib = csubgraph_native.find_static_library(setting)
    return (str(lib) if lib else None), setting


def configure_backend(backend, lib):
    """
    Stellt die Multi-Omics-Implementierung für den nächsten Prozess-Pool ein.

    CSUBGRAPH_LIB_PATH wird über die Umgebung gesetzt (leer = Python); Umgebungsvariablen haben
    Vorrang vor der .env und werden von Worker-Prozessen geerbt. Der Link-Build des Wrappers
    läuft hier (über get_multiomics_backend_name), also vor jeder Messung.
    """
    os.environ["CSUBGRAPH_LIB_PATH"] = lib if backend == "cpp" else ""
    backend_config.reload_config()
    subgraph_executor.reset_backend()
    actual = subgraph_executor.get_multiomics_backend_name()
    if actual != EXPECTED_NAME[backend]:
        reason = subgraph_executor.get_multiomics_native_error()
        raise SystemExit(
            f"Implementierung '{backend}' angefordert, für Multi-Omics aufgelöst wurde '{actual}'."
            + (f"\nGrund: {reason}" if reason else ""))


def _probe_backend(_):
    """Läuft im Worker-Prozess: welche Multi-Omics-Implementierung wird dort verwendet?"""
    return os.getpid(), subgraph_executor.get_multiomics_backend_name()


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
# Messung einer Suche
# ---------------------------------------------------------------------------

class CompareTimer:
    """Misst Laden und Vergleichsphase (crud.compare_many_multiomics) einer Suche."""

    def __init__(self):
        self.chunksize = None
        self.start = 0.0
        self.reset()

    def reset(self):
        self.fetch_s = None
        self.compare_s = 0.0
        self.candidates = None

    def wrap(self, function):
        def timed(query, candidates, *args, **kwargs):
            now = time.perf_counter()
            self.fetch_s = now - self.start
            self.candidates = len(candidates)
            if self.chunksize is not None:
                kwargs["chunksize"] = self.chunksize
            try:
                return function(query, candidates, *args, **kwargs)
            finally:
                self.compare_s += time.perf_counter() - now
        return timed


class FailureCapture(logging.Handler):
    """Zählt fehlgeschlagene Einzelvergleiche aus der Warnung von crud.search_multiomics."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.failed = 0

    def emit(self, record):
        match = FAILED_RE.search(record.getMessage())
        if match:
            self.failed = int(match.group(1))


@contextmanager
def instrumented():
    """Hängt Zeitmessung und Fehlerzähler in crud ein und stellt danach alles wieder her."""
    timer, failures = CompareTimer(), FailureCapture()
    crud_logger = logging.getLogger("backend.crud")
    old_level, old_propagate = crud_logger.level, crud_logger.propagate
    original = crud.compare_many_multiomics
    crud_logger.addHandler(failures)
    crud_logger.setLevel(logging.INFO)
    crud_logger.propagate = False  # Konsole nicht mit Log-Zeilen fluten
    crud.compare_many_multiomics = timer.wrap(original)
    try:
        yield timer, failures
    finally:
        crud.compare_many_multiomics = original
        crud_logger.removeHandler(failures)
        crud_logger.setLevel(old_level)
        crud_logger.propagate = old_propagate
        subgraph_executor.shutdown_executor()


class Context:
    """Gemeinsamer Zustand eines Messlaufs."""

    def __init__(self, args, data, lib, json_path, timer, failures, specs):
        self.args, self.data, self.lib, self.json_path = args, data, lib, json_path
        self.timer, self.failures, self.specs = timer, failures, specs


class Progress:
    """Fortschritt mit Restzeitschätzung."""

    def __init__(self, total, label):
        self.total, self.label, self.done = max(1, total), label, 0
        self.started = time.perf_counter()

    def step(self, text):
        self.done += 1
        elapsed = time.perf_counter() - self.started
        eta = elapsed / self.done * (self.total - self.done)
        print(f"  [{self.label} {self.done:>4}/{self.total}] {text} (Rest ca. {eta / 60:.0f} min)", flush=True)


def run_search(ctx, spec, mode):
    """Eine Suche ausführen; gibt die Messwerte als dict zurück."""
    timer, failures = ctx.timer, ctx.failures
    timer.reset()
    failures.failed = 0
    start = time.perf_counter()
    timer.start = start
    matches = crud.search_multiomics(spec["names"], spec["matrices"], spec["labels"], mode)
    total = time.perf_counter() - start
    ids = sorted(int(m.network_id) for m in matches)
    expected = set(spec["expected"][mode])
    fetch_s = timer.fetch_s if timer.fetch_s is not None else total
    return {
        "query": spec["index"], "kind": spec["kind"], "layers": spec["layers"], "nodes": spec["nodes"],
        "mode": mode, "candidates": timer.candidates or 0, "matches": len(ids),
        "exact_matches": sum(1 for m in matches if m.match_type == "exact"),
        "match_digest": hashlib.sha1(",".join(map(str, ids)).encode()).hexdigest()[:16],
        "match_ids": ids if len(ids) <= 2000 else None,
        "expected_total": len(expected), "expected_found": len(expected & set(ids)),
        "missing_ids": sorted(expected - set(ids))[:20],
        "failed": failures.failed, "total_s": total, "fetch_s": fetch_s, "compare_s": timer.compare_s,
        "build_s": max(0.0, total - fetch_s - timer.compare_s),
    }


def save_json(ctx, final=False):
    """Schreibt die JSON-Datei atomar."""
    ctx.data["meta"]["complete"] = final
    path = Path(ctx.json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(ctx.data, handle, indent=1, ensure_ascii=False, default=json_default)
    os.replace(tmp, path)


def json_default(value):
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"{type(value)} nicht serialisierbar")


def warm_up(ctx, specs, count, mode="coherent"):
    for i in range(count):
        run_search(ctx, specs[i % len(specs)], mode)  # verworfen (Caches, Pool)


def rotated(items, shift):
    shift %= len(items)
    return list(items[shift:]) + list(items[:shift])


# ---------------------------------------------------------------------------
# Teilexperiment 1: Korrektheit (ohne Datenbank)
# ---------------------------------------------------------------------------

def make_pair(rng, kind, names, n_a, n_b):
    """Paar (x, y) von Schichtstapeln; kind: random, coherent, independent, exact, reversed."""
    if kind == "random":
        return random_stack(rng, n_a, names), random_stack(rng, n_b, names)
    small = random_stack(rng, n_a, names)
    if kind == "exact":
        return small, [m.copy() for m in small]
    big_kind = "independent" if kind == "independent" and len(names) >= 2 else "coherent"
    big = embed_stack(rng, small, n_b, names, big_kind)
    if kind == "reversed":
        return big, small
    return small, big


def is_symmetric(result, swapped):
    """Vertauscht man A und B, vertauschen sich KEEP_A und KEEP_B; die übrigen Klassen bleiben."""
    if result == "KEEP_A":
        return swapped == "KEEP_B"
    if result == "KEEP_B":
        return swapped == "KEEP_A"
    if result.startswith("EQUAL_"):
        return swapped.startswith("EQUAL_")
    return swapped == result


def run_correctness(ctx):
    """Python-Referenz gegen C++ und Invarianten auf Zufalls- und eingebetteten Paaren."""
    args = ctx.args
    rng = np.random.default_rng([args.seed, 21])
    native = None
    if "cpp" in args.backends:
        configure_backend("cpp", ctx.lib)
        native = subgraph_executor._get_native_omics()
    kinds = ("random", "coherent", "independent", "exact", "reversed")
    by_kind = {k: {"comparisons": 0, "agree": 0, "disagree": 0, "errors": 0} for k in kinds}
    results = {mode: Counter() for mode in MODES}
    violations = Counter()
    examples = []
    progress = Progress(args.correctness_pairs, "Korrektheit")

    for i in range(args.correctness_pairs):
        kind = kinds[i % len(kinds)]
        layers = int(rng.integers(1, 5))
        n_a = int(rng.integers(3, 21))
        n_b = int(rng.integers(n_a, 41))
        names = pick_names(rng, layers)
        x, y = make_pair(rng, kind, names, n_a, n_b)
        xl, yl = to_lists(x), to_lists(y)
        xa, ya = np.array(x, dtype=int), np.array(y, dtype=int)

        coherent_in = multiomics_python.contains(xl, yl, "coherent")
        independent_in = multiomics_python.contains(xl, yl, "independent")
        if coherent_in and not independent_in:
            violations["coherent_not_independent"] += 1

        for mode in MODES:
            reference = multiomics_python.compare_layered(xl, yl, mode)
            swapped = multiomics_python.compare_layered(yl, xl, mode)
            results[mode][reference] += 1
            by_kind[kind]["comparisons"] += 1
            if not is_symmetric(reference, swapped):
                violations["symmetry"] += 1

            expected = None
            if kind in ("exact", "reversed") or (kind == "coherent") or (kind == "independent" and mode == "independent"):
                expected = EXPECTED_RESULTS["coherent" if kind == "independent" else kind]
            if expected is not None and reference not in expected:
                violations["expected_result"] += 1
                if len(examples) < 20:
                    examples.append({"type": "expected", "kind": kind, "mode": mode, "layers": layers,
                                     "n_a": n_a, "n_b": n_b, "python": reference})

            if native is not None:
                result, error = native.compare(xa, ya, mode)
                if error:
                    by_kind[kind]["errors"] += 1
                    violations["native_error"] += 1
                elif result == reference:
                    by_kind[kind]["agree"] += 1
                else:
                    by_kind[kind]["disagree"] += 1
                    violations["native_disagree"] += 1
                    if len(examples) < 20:
                        examples.append({"type": "disagree", "kind": kind, "mode": mode, "layers": layers,
                                         "n_a": n_a, "n_b": n_b, "python": reference, "cpp": result})
        if (i + 1) % max(1, args.correctness_pairs // 10) == 0:
            progress.done = i
            progress.step(f"{i + 1} Paare, Verstöße {dict(violations)}")

    ctx.data["correctness"] = {
        "pairs": args.correctness_pairs, "native": native is not None,
        "comparisons": sum(v["comparisons"] for v in by_kind.values()),
        "agree": sum(v["agree"] for v in by_kind.values()),
        "disagree": sum(v["disagree"] for v in by_kind.values()),
        "errors": sum(v["errors"] for v in by_kind.values()),
        "by_kind": by_kind, "results": {mode: dict(c) for mode, c in results.items()},
        "violations": dict(violations), "examples": examples,
    }
    save_json(ctx)


# ---------------------------------------------------------------------------
# Teilexperiment 2: Mikro-Benchmark (ohne Datenbank)
# ---------------------------------------------------------------------------

def micro_pairs(args, layers, n_b, kind):
    """Dieselben Paare für jede Implementierung (deterministisch aus Seed und Zelle)."""
    n_a = max(3, n_b // 2)
    rng = np.random.default_rng([args.seed, 41, layers, n_b, 0 if kind == "random" else 1])
    names = [f"Schicht{i + 1}" for i in range(layers)]
    pairs = []
    for _ in range(args.micro_pairs):
        a = random_stack(rng, n_a, names)
        b = random_stack(rng, n_b, names) if kind == "random" else embed_stack(rng, a, n_b, names, "coherent")
        pairs.append((to_lists(a), to_lists(b)))
    return n_a, pairs


def run_micro(ctx):
    """
    Zeit je Einzelvergleich über subgraph_executor.execute_multiomics_comparison, also der Pfad
    im Worker (Umwandlung in numpy, Validierung, Aufruf) ohne Prozess-Pool.
    """
    args = ctx.args
    cells = []
    cases = [(layers, n_b, kind) for layers in args.micro_layers for n_b in args.micro_sizes
             for kind in ("random", "embedded")]
    progress = Progress(len(cases) * len(args.backends), "Mikro")
    for backend in args.backends:
        configure_backend(backend, ctx.lib)
        for layers, n_b, kind in cases:
            n_a, pairs = micro_pairs(args, layers, n_b, kind)
            subgraph_executor.execute_multiomics_comparison(pairs[0][0], pairs[0][1], "coherent")  # Aufwärmen
            for mode in MODES:
                values, errors, hits = [], 0, 0
                for a, b in pairs:
                    start = time.perf_counter()
                    result, error = subgraph_executor.execute_multiomics_comparison(a, b, mode)
                    values.append((time.perf_counter() - start) * 1000)
                    errors += 1 if error else 0
                    hits += 1 if result in crud.MATCH_RESULTS else 0
                cells.append({"backend": backend, "mode": mode, "kind": kind, "layers": layers,
                              "n_a": n_a, "n_b": n_b, "pairs": len(pairs), "errors": errors,
                              "match_rate": hits / len(pairs), **time_stats(values)})
            progress.step(f"{DISPLAY[backend]} L={layers} n={n_b} {KIND_DISPLAY[kind]}")

        # Aufrufkosten: trivialer 1x1-Vergleich
        trivial = [[[0]]]
        values, errors = [], 0
        subgraph_executor.execute_multiomics_comparison(trivial, trivial, "coherent")
        for _ in range(max(200, args.micro_pairs * 5)):
            start = time.perf_counter()
            _, error = subgraph_executor.execute_multiomics_comparison(trivial, trivial, "coherent")
            values.append((time.perf_counter() - start) * 1000)
            errors += 1 if error else 0
        cells.append({"backend": backend, "mode": "coherent", "kind": "trivial", "layers": 1, "n_a": 1,
                      "n_b": 1, "pairs": len(values), "errors": errors, "match_rate": None,
                      **time_stats(values)})
        ctx.data["micro"] = cells
        save_json(ctx)


# ---------------------------------------------------------------------------
# Teilexperiment 3: Ende-zu-Ende-Suche (Gitter)
# ---------------------------------------------------------------------------

def run_search_grid(ctx):
    """Anfragen x Modi x Implementierungen x Wiederholungen."""
    args, data = ctx.args, ctx.data
    backends = list(args.backends)
    progress = Progress(args.reps * len(backends) * len(MODES) * len(ctx.specs), "Suche")
    rows = data.setdefault("search", [])
    for rep in range(args.reps):
        queue = [(mode, spec) for mode in MODES for spec in ctx.specs]
        order = np.random.default_rng([args.seed, 31, rep]).permutation(len(queue))
        for backend in rotated(backends, rep):
            configure_backend(backend, ctx.lib)
            pids = start_pool(args.workers, backend)
            data["meta"].setdefault("worker_pids", {})[f"search/{backend}/rep{rep}"] = pids
            warm_up(ctx, ctx.specs, args.warmup)
            for position in order:
                mode, spec = queue[int(position)]
                row = run_search(ctx, spec, mode)
                row.update(backend=backend, workers=args.workers, rep=rep)
                rows.append(row)
                save_json(ctx)
                progress.step(
                    f"{DISPLAY[backend]} {MODE_DISPLAY[mode]} q{spec['index']} L={spec['layers']} "
                    f"n={spec['nodes']} Kand.={row['candidates']} Treffer={row['matches']} "
                    f"{row['total_s']:.2f}s")


# ---------------------------------------------------------------------------
# Teilexperimente 4 bis 6: Worker, Chunk-Größe, Datenbankgröße
# ---------------------------------------------------------------------------

def subset_specs(ctx):
    return pick_evenly(ctx.specs, ctx.args.subset_queries)


def measure_subset(ctx, key, specs, backend, progress, **fields):
    """Suchen im Modus 'coherent' für die Teilmenge und Zeilen an data[key] anhängen."""
    rows = ctx.data.setdefault(key, [])
    for spec in specs:
        row = run_search(ctx, spec, "coherent")
        row.update(backend=backend, **fields)
        rows.append(row)
        save_json(ctx)
        progress.step(f"{DISPLAY[backend]} q{spec['index']} {fields} {row['total_s']:.2f}s")


def run_workers(ctx):
    args = ctx.args
    specs = subset_specs(ctx)
    backends = list(args.backends)
    progress = Progress(args.worker_reps * len(backends) * len(args.worker_scaling) * len(specs), "Worker")
    for rep in range(args.worker_reps):
        for backend in rotated(backends, rep):
            configure_backend(backend, ctx.lib)
            for workers in args.worker_scaling:
                start_pool(workers, backend)
                warm_up(ctx, specs, args.warmup)
                measure_subset(ctx, "workers", specs, backend, progress, workers=workers, rep=rep)


def run_chunksize(ctx):
    args = ctx.args
    specs = subset_specs(ctx)
    backends = list(args.backends)
    progress = Progress(args.worker_reps * len(backends) * len(args.chunksizes) * len(specs), "Chunk")
    try:
        for rep in range(args.worker_reps):
            for backend in rotated(backends, rep):
                configure_backend(backend, ctx.lib)
                start_pool(args.workers, backend)
                for chunksize in args.chunksizes:
                    ctx.timer.chunksize = chunksize
                    warm_up(ctx, specs, args.warmup)
                    measure_subset(ctx, "chunksize", specs, backend, progress,
                                   workers=args.workers, chunksize=chunksize, rep=rep)
    finally:
        ctx.timer.chunksize = None


def run_dbsize(ctx):
    args = ctx.args
    specs = subset_specs(ctx)
    backends = list(args.backends)
    sizes = sorted(set(args.db_sizes))
    progress = Progress(len(sizes) * args.worker_reps * len(backends) * len(specs), "DB-Größe")
    for size in sizes:
        print(f"\n=== Datenbank mit {size} Zufallsnetzwerken ===", flush=True)
        set_random_count(args, size, verbose=False)
        omics_total = count_omics_networks()
        for rep in range(args.worker_reps):
            for backend in rotated(backends, rep):
                configure_backend(backend, ctx.lib)
                start_pool(args.workers, backend)
                warm_up(ctx, specs, args.warmup)
                measure_subset(ctx, "dbsize", specs, backend, progress, workers=args.workers,
                               random_networks=size, omics_networks=omics_total, rep=rep)
    set_random_count(args, args.networks, verbose=False)  # Ausgangszustand wiederherstellen


# ---------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------

def group_rows(rows, keys):
    groups = {}
    for row in rows:
        groups.setdefault(tuple(row[k] for k in keys), []).append(row)
    return groups


def per_query_means(rows, extra_keys=()):
    """Mittel über die Wiederholungen je (backend, mode, [extra], query)."""
    keys = ("backend", "mode") + tuple(extra_keys) + ("query",)
    result = []
    for key, items in group_rows(rows, keys).items():
        totals = [r["total_s"] for r in items]
        mean_total = statistics.fmean(totals)
        entry = dict(zip(keys, key))
        entry.update({
            "kind": items[0]["kind"], "layers": items[0]["layers"], "nodes": items[0]["nodes"],
            "reps": len(items), "candidates": items[0]["candidates"],
            "total_s": mean_total,
            "fetch_s": statistics.fmean(r["fetch_s"] for r in items),
            "compare_s": statistics.fmean(r["compare_s"] for r in items),
            "build_s": statistics.fmean(r["build_s"] for r in items),
            "matches": statistics.fmean(r["matches"] for r in items),
            "failed": sum(r["failed"] for r in items),
            "cv": statistics.stdev(totals) / mean_total if len(totals) > 1 and mean_total > 0 else None,
        })
        result.append(entry)
    return result


def aggregate(entries, keys):
    out = []
    for key, items in sorted(group_rows(entries, keys).items()):
        candidates = sum(v["candidates"] for v in items)
        compare = sum(v["compare_s"] for v in items)
        row = dict(zip(keys, key))
        row.update({
            "queries": len(items),
            "mean_total_s": statistics.fmean(v["total_s"] for v in items),
            "mean_compare_s": statistics.fmean(v["compare_s"] for v in items),
            "mean_candidates": statistics.fmean(v["candidates"] for v in items),
            "mean_matches": statistics.fmean(v["matches"] for v in items),
            "ms_per_candidate": compare / candidates * 1000 if candidates else None,
        })
        out.append(row)
    return out


def analyze_search(rows, meta):
    if not rows:
        return None
    entries = per_query_means(rows)
    backends = [b for b in BACKENDS if any(r["backend"] == b for r in rows)]
    modes = [m for m in MODES if any(r["mode"] == m for r in rows)]
    ref = "python" if "python" in backends else backends[0]
    summary = []
    for mode in modes:
        ref_entries = {v["query"]: v for v in entries if v["backend"] == ref and v["mode"] == mode}
        ref_total = sum(v["total_s"] for v in ref_entries.values())
        ref_compare = sum(v["compare_s"] for v in ref_entries.values())
        ref_rows = {(r["query"], r["rep"]): r for r in rows if r["backend"] == ref and r["mode"] == mode}
        for backend in backends:
            items = [v for v in entries if v["backend"] == backend and v["mode"] == mode]
            mine = [r for r in rows if r["backend"] == backend and r["mode"] == mode]
            if not items:
                continue
            totals = [v["total_s"] for v in items]
            sum_total = sum(totals)
            sum_compare = sum(v["compare_s"] for v in items)
            sum_fetch = sum(v["fetch_s"] for v in items)
            sum_build = sum(v["build_s"] for v in items)
            candidates = sum(v["candidates"] for v in items)
            rep_sums = [sum(r["total_s"] for r in group) for group in
                        group_rows(mine, ("rep",)).values()]
            sum_mean, sum_low, sum_high = mean_ci(rep_sums)
            ratios = [ref_entries[v["query"]]["total_s"] / v["total_s"] for v in items
                      if v["query"] in ref_entries and v["total_s"] > 0]
            ratios_compare = [ref_entries[v["query"]]["compare_s"] / v["compare_s"] for v in items
                              if v["query"] in ref_entries and v["compare_s"] > 0]
            low, high = bootstrap_ci(ratios, geomean)
            same = [(r["query"], r["rep"]) in ref_rows
                    and r["match_digest"] == ref_rows[(r["query"], r["rep"])]["match_digest"] for r in mine]
            cvs = [v["cv"] for v in items if v["cv"] is not None]
            summary.append({
                "backend": backend, "mode": mode, "queries": len(items), "measurements": len(mine),
                "reps": len(rep_sums), "sum_s": sum_total, "sum_s_ci": [sum_low, sum_high],
                "mean_s": statistics.fmean(totals), "median_s": statistics.median(totals),
                "p95_s": percentile(totals, 0.95), "max_s": max(totals),
                "candidates_sum": candidates,
                "pairs_per_s": candidates / sum_compare if sum_compare > 0 else None,
                "ms_per_candidate": sum_compare / candidates * 1000 if candidates else None,
                "ms_per_candidate_total": sum_total / candidates * 1000 if candidates else None,
                "fetch_share": sum_fetch / sum_total if sum_total > 0 else None,
                "compare_share": sum_compare / sum_total if sum_total > 0 else None,
                "build_share": sum_build / sum_total if sum_total > 0 else None,
                "speedup": ref_total / sum_total if sum_total > 0 and ref_total > 0 else None,
                "speedup_compare": ref_compare / sum_compare if sum_compare > 0 and ref_compare > 0 else None,
                "speedup_geomean": geomean(ratios), "speedup_geomean_ci": [low, high],
                "speedup_min": min(ratios) if ratios else None,
                "speedup_max": max(ratios) if ratios else None,
                "speedup_compare_geomean": geomean(ratios_compare),
                "matches_equal": all(same), "matches_equal_share": sum(same) / len(same) if same else None,
                "failed": sum(r["failed"] for r in mine), "cv_mean": statistics.fmean(cvs) if cvs else None,
            })

    # Trefferquote der eingebetteten Netzwerke (Ground Truth) und weitere Treffer
    recall = []
    for (backend, mode, kind), items in sorted(group_rows(rows, ("backend", "mode", "kind")).items()):
        expected = sum(r["expected_total"] for r in items)
        found = sum(r["expected_found"] for r in items)
        matches = sum(r["matches"] for r in items)
        recall.append({"backend": backend, "mode": mode, "kind": kind, "expected": expected,
                       "found": found, "recall": found / expected if expected else None,
                       "matches": matches, "other_matches": matches - found})

    # Kohärente Treffer müssen auch unabhängige Treffer sein
    checked = violations = 0
    by_key = {(r["backend"], r["query"], r["rep"], r["mode"]): r for r in rows}
    for (backend, query, rep, mode), row in by_key.items():
        if mode != "coherent":
            continue
        other = by_key.get((backend, query, rep, "independent"))
        if other is None:
            continue
        checked += 1
        if row["match_ids"] is not None and other["match_ids"] is not None:
            violations += 0 if set(row["match_ids"]) <= set(other["match_ids"]) else 1
        else:
            violations += 0 if row["matches"] <= other["matches"] else 1

    # Selektivität des SQL-Vorfilters (Kandidaten gegenüber allen Multi-Omics-Netzwerken)
    total = meta.get("omics_networks_total") or 0
    ref_entries_all = [v for v in entries if v["backend"] == ref and v["mode"] == modes[0]]
    prefilter = [{"layers": v["layers"], "nodes": v["nodes"], "kind": v["kind"],
                  "candidates": v["candidates"], "share": v["candidates"] / total if total else None}
                 for v in sorted(ref_entries_all, key=lambda x: x["query"])]

    return {
        "reference": ref, "summary": summary, "recall": recall,
        "by_layers": aggregate(entries, ("backend", "mode", "kind", "layers")),
        "by_nodes": aggregate(entries, ("backend", "mode", "kind", "nodes")),
        "mode_check": {"checked": checked, "violations": violations},
        "prefilter": prefilter, "failed": sum(r["failed"] for r in rows),
        "queries": sorted({r["query"] for r in rows}),
    }


def analyze_scaling(rows, key, label):
    """Summen je (backend, label) über die Anfragen (Mittel über Wiederholungen)."""
    if not rows:
        return None
    entries = per_query_means(rows, extra_keys=(label,))
    out = []
    for (backend, value), items in sorted(group_rows(entries, ("backend", label)).items()):
        out.append({"backend": backend, label: value, "queries": len(items),
                    "sum_total_s": sum(v["total_s"] for v in items),
                    "sum_compare_s": sum(v["compare_s"] for v in items),
                    "sum_fetch_s": sum(v["fetch_s"] for v in items),
                    "candidates": sum(v["candidates"] for v in items)})
    return out


def analyze_workers(rows):
    table = analyze_scaling(rows, "workers", "workers")
    if not table:
        return None
    result = []
    for backend in sorted({t["backend"] for t in table}):
        items = sorted((t for t in table if t["backend"] == backend), key=lambda t: t["workers"])
        base = items[0]
        for field, name in (("sum_total_s", "total"), ("sum_compare_s", "compare")):
            fit_x, fit_y = [], []
            for t in items:
                if t["workers"] > base["workers"] and base[field] > 0 and t[field] > 0:
                    p = t["workers"] / base["workers"]
                    fit_x.append(1 - 1 / p)
                    fit_y.append(t[field] / base[field] - 1 / p)
            denominator = sum(x * x for x in fit_x)
            serial = sum(x * y for x, y in zip(fit_x, fit_y)) / denominator if denominator > 0 else None
            serial = min(1.0, max(0.0, serial)) if serial is not None else None
            for t in items:
                t.setdefault("amdahl", {})[name] = serial
        for t in items:
            p = t["workers"] / base["workers"]
            result.append({
                **t, "speedup_total": base["sum_total_s"] / t["sum_total_s"] if t["sum_total_s"] > 0 else None,
                "speedup_compare": base["sum_compare_s"] / t["sum_compare_s"] if t["sum_compare_s"] > 0 else None,
                "efficiency_compare": (base["sum_compare_s"] / t["sum_compare_s"]) / p
                if t["sum_compare_s"] > 0 else None,
                "efficiency_total": (base["sum_total_s"] / t["sum_total_s"]) / p
                if t["sum_total_s"] > 0 else None,
            })
    return result


def analyze_chunksize(rows):
    table = analyze_scaling(rows, "chunksize", "chunksize")
    if not table:
        return None
    for backend in {t["backend"] for t in table}:
        items = [t for t in table if t["backend"] == backend]
        best = min(t["sum_total_s"] for t in items)
        for t in items:
            t["relative_to_best"] = t["sum_total_s"] / best if best > 0 else None
    return table


def analyze_dbsize(rows):
    table = analyze_scaling(rows, "random_networks", "random_networks")
    if not table:
        return None
    ref = "python" if any(t["backend"] == "python" for t in table) else table[0]["backend"]
    ref_totals = {t["random_networks"]: t["sum_total_s"] for t in table if t["backend"] == ref}
    omics = {r["random_networks"]: r["omics_networks"] for r in rows}
    for t in table:
        t["omics_networks"] = omics.get(t["random_networks"])
        base = ref_totals.get(t["random_networks"])
        t["speedup"] = base / t["sum_total_s"] if base and t["sum_total_s"] > 0 else None
    fits = []
    for backend in sorted({r["backend"] for r in rows}):
        mine = [r for r in rows if r["backend"] == backend]
        for field in ("total_s", "compare_s"):
            slope, intercept, r2 = linear_fit([r["candidates"] for r in mine], [r[field] for r in mine])
            fits.append({"backend": backend, "field": field, "ms_per_candidate":
                         slope * 1000 if slope is not None else None, "intercept_s": intercept, "r2": r2})
        slope, intercept, r2 = linear_fit([r["omics_networks"] for r in mine], [r["total_s"] for r in mine])
        fits.append({"backend": backend, "field": "total_s_vs_networks", "ms_per_candidate":
                     slope * 1000 if slope is not None else None, "intercept_s": intercept, "r2": r2})
    return {"table": table, "fits": fits}


def analyze_micro(cells):
    if not cells:
        return None
    index = {(c["backend"], c["mode"], c["kind"], c["layers"], c["n_b"]): c
             for c in cells if c["kind"] != "trivial"}
    speedups = []
    for key, py in index.items():
        if key[0] != "python":
            continue
        cpp = index.get(("cpp",) + key[1:])
        if cpp is None or cpp["median_ms"] <= 0:
            continue
        speedups.append({"mode": key[1], "kind": key[2], "layers": key[3], "n_b": key[4],
                         "python_median_ms": py["median_ms"], "cpp_median_ms": cpp["median_ms"],
                         "speedup_median": py["median_ms"] / cpp["median_ms"],
                         "speedup_mean": py["mean_ms"] / cpp["mean_ms"] if cpp["mean_ms"] > 0 else None})
    overall = []
    for (mode, kind), items in sorted(group_rows(speedups, ("mode", "kind")).items()):
        overall.append({"mode": mode, "kind": kind, "cells": len(items),
                        "speedup_geomean": geomean([i["speedup_median"] for i in items]),
                        "speedup_min": min(i["speedup_median"] for i in items),
                        "speedup_max": max(i["speedup_median"] for i in items)})
    return {"speedups": speedups, "overall": overall,
            "overhead": [c for c in cells if c["kind"] == "trivial"]}


def analyze(data):
    """Kennzahlen aller Teilexperimente aus den Rohdaten (auch für --plot-from)."""
    meta = data.get("meta", {})
    return {
        "search": analyze_search(data.get("search", []), meta),
        "workers": analyze_workers(data.get("workers", [])),
        "chunksize": analyze_chunksize(data.get("chunksize", [])),
        "dbsize": analyze_dbsize(data.get("dbsize", [])),
        "micro": analyze_micro(data.get("micro", [])),
        "correctness": data.get("correctness"),
    }


# ---------------------------------------------------------------------------
# Diagramme (PDF)
# ---------------------------------------------------------------------------

def no_data(ax, title, text="keine Daten"):
    ax.set_title(title)
    ax.text(0.5, 0.5, text, ha="center", va="center", transform=ax.transAxes, color="gray")
    ax.set_xticks([])
    ax.set_yticks([])


def style(backend, mode):
    return {"color": COLORS[backend], "linestyle": "-" if mode == "coherent" else "--",
            "marker": "o" if mode == "coherent" else "s"}


def label_of(backend, mode):
    return f"{DISPLAY[backend]}, {MODE_DISPLAY[mode]}"


def draw_total(ax, ctx):
    summary = (ctx["s"]["search"] or {}).get("summary") if ctx["s"]["search"] else None
    if not summary:
        return no_data(ax, "Gesamtzeit und Speedup")
    labels = [label_of(s["backend"], s["mode"]) for s in summary]
    values = [s["sum_s"] / 60 for s in summary]
    errors = [[(s["sum_s"] - (s["sum_s_ci"][0] if s["sum_s_ci"][0] is not None else s["sum_s"])) / 60 for s in summary],
              [((s["sum_s_ci"][1] if s["sum_s_ci"][1] is not None else s["sum_s"]) - s["sum_s"]) / 60 for s in summary]]
    bars = ax.bar(labels, values, color=[COLORS[s["backend"]] for s in summary], yerr=errors, capsize=4)
    for bar, s in zip(bars, summary):
        if s["speedup"] is not None and s["backend"] != ctx["s"]["search"]["reference"]:
            ax.annotate(f"{s['speedup']:.2f}x", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("Gesamtzeit aller Anfragen [min]")
    ax.set_title("Gesamtzeit (95-%-KI über Wiederholungen) und Speedup")
    ax.tick_params(axis="x", labelsize=8)
    ax.set_ylim(0, max(values) * 1.2)
    ax.grid(alpha=0.3, axis="y")


def draw_distribution(ax, ctx):
    rows = ctx["data"].get("search", [])
    if not rows:
        return no_data(ax, "Verteilung der Antwortzeiten")
    groups = [(b, m) for m in MODES for b in BACKENDS if any(r["backend"] == b and r["mode"] == m for r in rows)]
    ax.boxplot([[r["total_s"] for r in rows if r["backend"] == b and r["mode"] == m] for b, m in groups],
               showmeans=True)
    ax.set_xticklabels([label_of(b, m) for b, m in groups], fontsize=8)
    ax.set_yscale("log")
    ax.set_ylabel("Zeit pro Anfrage [s] (log)")
    ax.set_title("Verteilung der Antwortzeiten")
    ax.grid(alpha=0.3)


def draw_phases(ax, ctx):
    search = ctx["s"]["search"]
    if not search:
        return no_data(ax, "Zeit je Phase")
    summary = search["summary"]
    labels = [label_of(s["backend"], s["mode"]) for s in summary]
    parts = [("fetch_share", "Laden (SQL, seriell)", "#7f7f7f"),
             ("compare_share", "Vergleichen (parallel)", "#2ca02c"),
             ("build_share", "Treffer bauen (seriell)", "#ff7f0e")]
    bottom = np.zeros(len(summary))
    for field, name, color in parts:
        values = np.array([(s[field] or 0) * s["sum_s"] / s["queries"] for s in summary])
        ax.bar(labels, values, bottom=bottom, label=name, color=color)
        bottom += values
    ax.legend(fontsize=8)
    ax.tick_params(axis="x", labelsize=8)
    ax.set_ylabel("Mittlere Zeit pro Anfrage [s]")
    ax.set_title("Zeit je Phase")
    ax.grid(alpha=0.3, axis="y")


def draw_scaling_candidates(ax, ctx):
    rows = ctx["data"].get("search", [])
    if not rows:
        return no_data(ax, "Vergleichszeit gegen Kandidatenzahl")
    for entry_key, items in group_rows(per_query_means(rows), ("backend", "mode")).items():
        backend, mode = entry_key
        points = [(v["candidates"], v["compare_s"]) for v in items if v["candidates"] > 0 and v["compare_s"] > 0]
        if points:
            xs, ys = zip(*points)
            ax.scatter(xs, ys, s=18, alpha=0.7, color=COLORS[backend],
                       marker="o" if mode == "coherent" else "s", label=label_of(backend, mode))
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.legend(fontsize=8)
    ax.set_xlabel("Kandidaten nach SQL-Vorauswahl")
    ax.set_ylabel("Vergleichsphase pro Anfrage [s]")
    ax.set_title("Skalierung mit der Kandidatenzahl")
    ax.grid(alpha=0.3, which="both")


def _draw_by(ax, ctx, field, xlabel, title):
    search = ctx["s"]["search"]
    if not search:
        return no_data(ax, title)
    for backend in BACKENDS:
        for mode in MODES:
            items = [a for a in search[f"by_{field}s"] if a["backend"] == backend and a["mode"] == mode
                     and a["kind"] == "random" and a["ms_per_candidate"] is not None]
            if items:
                ax.plot([a[field + "s"] for a in items], [a["ms_per_candidate"] for a in items],
                        label=label_of(backend, mode), markersize=4, **style(backend, mode))
    ax.set_yscale("log")
    ax.legend(fontsize=8)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Vergleichsphase [ms je Kandidat] (log)")
    ax.set_title(title)
    ax.grid(alpha=0.3, which="both")


def draw_layers(ax, ctx):
    _draw_by(ax, ctx, "layer", "Schichten der Anfrage", "Einfluss der Schichtzahl (Zufallsanfragen)")


def draw_nodes(ax, ctx):
    _draw_by(ax, ctx, "node", "Knoten der Anfrage", "Einfluss der Knotenzahl (Zufallsanfragen)")


def _draw_heat(ax, ctx, kind, title):
    micro = ctx["s"]["micro"]
    items = [s for s in (micro["speedups"] if micro else []) if s["mode"] == "coherent" and s["kind"] == kind]
    if not items:
        return no_data(ax, title)
    layers = sorted({s["layers"] for s in items})
    sizes = sorted({s["n_b"] for s in items})
    grid = np.full((len(layers), len(sizes)), np.nan)
    for s in items:
        grid[layers.index(s["layers"]), sizes.index(s["n_b"])] = s["speedup_median"]
    image = ax.imshow(grid, aspect="auto", cmap="viridis", origin="lower")
    ax.set_xticks(range(len(sizes)))
    ax.set_xticklabels(sizes)
    ax.set_yticks(range(len(layers)))
    ax.set_yticklabels(layers)
    for i in range(len(layers)):
        for j in range(len(sizes)):
            if not np.isnan(grid[i, j]):
                ax.text(j, i, f"{grid[i, j]:.1f}", ha="center", va="center", color="white", fontsize=8)
    ax.figure.colorbar(image, ax=ax, label="Speedup (Median)")
    ax.set_xlabel("Knoten des Kandidaten n_B")
    ax.set_ylabel("Schichten")
    ax.set_title(title)


def draw_micro_heat_random(ax, ctx):
    _draw_heat(ax, ctx, "random", "Mikro: Speedup C++/Python, Zufallspaare (kohärent)")


def draw_micro_heat_embedded(ax, ctx):
    _draw_heat(ax, ctx, "embedded", "Mikro: Speedup C++/Python, eingebettete Paare (kohärent)")


def draw_micro_time(ax, ctx):
    cells = [c for c in ctx["data"].get("micro", []) if c["kind"] == "random" and c["mode"] == "coherent"]
    if not cells:
        return no_data(ax, "Mikro: Zeit je Einzelvergleich")
    layers = sorted({c["layers"] for c in cells})
    cmap = ctx["plt"].get_cmap("viridis")
    for index, layer in enumerate(layers):
        for backend in BACKENDS:
            items = sorted((c for c in cells if c["backend"] == backend and c["layers"] == layer),
                           key=lambda c: c["n_b"])
            if items:
                ax.plot([c["n_b"] for c in items], [c["median_ms"] for c in items], marker="o", markersize=3,
                        linestyle="-" if backend == "python" else "--", color=cmap(index / max(1, len(layers) - 1)),
                        label=f"{DISPLAY[backend]}, L={layer}")
    ax.set_yscale("log")
    ax.legend(fontsize=6, ncol=2)
    ax.set_xlabel("Knoten des Kandidaten n_B")
    ax.set_ylabel("Median je Einzelvergleich [ms] (log)")
    ax.set_title("Mikro: Zeit je Einzelvergleich (Zufallspaare, kohärent)")
    ax.grid(alpha=0.3, which="both")


def draw_workers(ax, ctx):
    table = ctx["s"]["workers"]
    if not table:
        return no_data(ax, "Skalierung mit Workern")
    maximum = max(t["workers"] for t in table)
    base = min(t["workers"] for t in table)
    ax.plot([base, maximum], [1, maximum / base], color="gray", linestyle=":", label="ideal")
    for backend in BACKENDS:
        items = [t for t in table if t["backend"] == backend]
        if items:
            ax.plot([t["workers"] for t in items], [t["speedup_compare"] for t in items], marker="o",
                    color=COLORS[backend], label=f"{DISPLAY[backend]}, Vergleichsphase")
            ax.plot([t["workers"] for t in items], [t["speedup_total"] for t in items], marker="s",
                    linestyle="--", color=COLORS[backend], label=f"{DISPLAY[backend]}, gesamt")
    ax.legend(fontsize=8)
    ax.set_xlabel("Worker")
    ax.set_ylabel(f"Speedup gegenüber {base} Worker(n)")
    ax.set_title("Skalierung mit der Worker-Anzahl")
    ax.grid(alpha=0.3)


def draw_chunksize(ax, ctx):
    table = ctx["s"]["chunksize"]
    if not table:
        return no_data(ax, "Einfluss der Chunk-Größe")
    for backend in BACKENDS:
        items = sorted((t for t in table if t["backend"] == backend), key=lambda t: t["chunksize"])
        if items:
            ax.plot([t["chunksize"] for t in items], [t["sum_total_s"] for t in items], marker="o",
                    color=COLORS[backend], label=f"{DISPLAY[backend]}, gesamt")
            ax.plot([t["chunksize"] for t in items], [t["sum_compare_s"] for t in items], marker="s",
                    linestyle="--", color=COLORS[backend], label=f"{DISPLAY[backend]}, Vergleichsphase")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.legend(fontsize=8)
    ax.set_xlabel("Chunk-Größe (Vergleiche je Task)")
    ax.set_ylabel("Summe über die Anfragen [s]")
    ax.set_title("Einfluss der Chunk-Größe")
    ax.grid(alpha=0.3, which="both")


def draw_dbsize(ax, ctx):
    result = ctx["s"]["dbsize"]
    if not result:
        return no_data(ax, "Skalierung mit der Datenbankgröße")
    for backend in BACKENDS:
        items = sorted((t for t in result["table"] if t["backend"] == backend),
                       key=lambda t: t["random_networks"])
        if items:
            xs = [t["omics_networks"] or t["random_networks"] for t in items]
            ax.plot(xs, [t["sum_total_s"] for t in items], marker="o", color=COLORS[backend],
                    label=f"{DISPLAY[backend]}, gesamt")
            ax.plot(xs, [t["sum_compare_s"] for t in items], marker="s", linestyle="--",
                    color=COLORS[backend], label=f"{DISPLAY[backend]}, Vergleichsphase")
    ax.legend(fontsize=8)
    ax.set_xlabel("Multi-Omics-Netzwerke in der Datenbank")
    ax.set_ylabel("Summe über die Anfragen [s]")
    ax.set_title("Skalierung mit der Datenbankgröße")
    ax.grid(alpha=0.3)


def draw_selectivity(ax, ctx):
    search = ctx["s"]["search"]
    if not search:
        return no_data(ax, "Selektivität")
    ref = search["reference"]
    for mode in MODES:
        items = [a for a in search["by_nodes"] if a["backend"] == ref and a["mode"] == mode
                 and a["kind"] == "random"]
        if items:
            ax.plot([a["node"] if "node" in a else a["nodes"] for a in items],
                    [max(a["mean_matches"], 0.5) for a in items], label=f"Treffer, {MODE_DISPLAY[mode]}",
                    color="#2ca02c", linestyle="-" if mode == "coherent" else "--", marker="o")
    ax.set_yscale("log")
    ax.set_xlabel("Knoten der Anfrage")
    ax.set_ylabel("Treffer je Zufallsanfrage (log, min. 0,5)")
    ax2 = ax.twinx()
    items = [p for p in search["prefilter"] if p["kind"] == "random" and p["share"] is not None]
    for layers in sorted({p["layers"] for p in items}):
        mine = sorted((p for p in items if p["layers"] == layers), key=lambda p: p["nodes"])
        ax2.plot([p["nodes"] for p in mine], [p["share"] * 100 for p in mine], color="gray", alpha=0.6,
                 marker=".", linestyle=":", label=f"Kandidaten [%], L={layers}")
    ax2.set_ylabel("Kandidaten [% aller Netzwerke]")
    handles = ax.get_legend_handles_labels()
    handles2 = ax2.get_legend_handles_labels()
    ax.legend(handles[0] + handles2[0], handles[1] + handles2[1], fontsize=7)
    ax.set_title("Selektivität von SQL-Vorfilter und Relation")
    ax.grid(alpha=0.3)


def draw_modes(ax, ctx):
    search = ctx["s"]["search"]
    if not search:
        return no_data(ax, "Modi im Vergleich")
    width = 0.35
    backends = [b for b in BACKENDS if any(s["backend"] == b for s in search["summary"])]
    for i, mode in enumerate(MODES):
        values = []
        for backend in backends:
            entry = next((s for s in search["summary"] if s["backend"] == backend and s["mode"] == mode), None)
            values.append(entry["ms_per_candidate"] if entry and entry["ms_per_candidate"] else 0)
        bars = ax.bar(np.arange(len(backends)) + (i - 0.5) * width, values, width, label=MODE_DISPLAY[mode])
        for bar, value in zip(bars, values):
            ax.annotate(f"{value:.4f}", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        ha="center", va="bottom", fontsize=8)
    ax.set_xticks(np.arange(len(backends)))
    ax.set_xticklabels([DISPLAY[b] for b in backends])
    ax.set_ylabel("Vergleichsphase [ms je Kandidat]")
    ax.set_title("Kohärenter gegen unabhängigen Modus")
    ax.legend()
    ax.grid(alpha=0.3, axis="y")


def draw_correctness(ax, ctx):
    result = ctx["s"]["correctness"]
    if not result:
        return no_data(ax, "Korrektheit")
    kinds = list(result["by_kind"])
    if result["native"]:
        shares = [100 * v["agree"] / v["comparisons"] if v["comparisons"] else 0 for v in result["by_kind"].values()]
        ax.bar([PLANT_DISPLAY.get(k, "Zufall") for k in kinds], shares, color="#2ca02c")
        ax.set_ylim(0, 105)
        ax.set_ylabel("Übereinstimmung Python/C++ [%]")
        ax.set_title(f"Korrektheit: {result['agree']}/{result['comparisons']} Vergleiche identisch")
    else:
        counts = [v["comparisons"] for v in result["by_kind"].values()]
        ax.bar([PLANT_DISPLAY.get(k, "Zufall") for k in kinds], counts, color="#1f77b4")
        ax.set_ylabel("Vergleiche")
        ax.set_title("Korrektheit (nur Python-Referenz, kein C++)")
    violations = sum(v for k, v in result["violations"].items())
    ax.text(0.5, 0.05, f"Verstöße gegen Invarianten/Erwartung: {violations}", transform=ax.transAxes,
            ha="center", fontsize=9, bbox={"facecolor": "white", "alpha": 0.8})
    ax.grid(alpha=0.3, axis="y")


def draw_expected(ax, ctx):
    search = ctx["s"]["search"]
    if not search:
        return no_data(ax, "Trefferquote eingebetteter Netzwerke")
    items = [r for r in search["recall"] if r["kind"] == "embedded" and r["expected"]]
    if not items:
        return no_data(ax, "Trefferquote eingebetteter Netzwerke")
    labels = [label_of(r["backend"], r["mode"]) for r in items]
    ax.bar(labels, [100 * r["recall"] for r in items], color=[COLORS[r["backend"]] for r in items])
    for index, r in enumerate(items):
        ax.annotate(f"{r['found']}/{r['expected']}\n+{r['other_matches']} weitere", (index, 100 * r["recall"]),
                    ha="center", va="bottom", fontsize=8)
    ax.set_ylim(0, 120)
    ax.tick_params(axis="x", labelsize=8)
    ax.set_ylabel("Gefundene eingebettete Netzwerke [%]")
    ax.set_title("Trefferquote gegen Ground Truth")
    ax.grid(alpha=0.3, axis="y")


DRAWERS = {
    "gesamtzeit_speedup": draw_total, "verteilung_antwortzeiten": draw_distribution,
    "phasen": draw_phases, "skalierung_kandidaten": draw_scaling_candidates,
    "schichten": draw_layers, "knoten": draw_nodes,
    "mikro_speedup_zufall": draw_micro_heat_random, "mikro_speedup_eingebettet": draw_micro_heat_embedded,
    "mikro_zeit": draw_micro_time, "workers": draw_workers, "chunksize": draw_chunksize,
    "dbsize": draw_dbsize, "selektivitaet": draw_selectivity, "modi": draw_modes,
    "korrektheit": draw_correctness, "treffer_erwartet": draw_expected,
}
PAGES = [
    ["gesamtzeit_speedup", "verteilung_antwortzeiten", "phasen", "skalierung_kandidaten"],
    ["schichten", "knoten", "selektivitaet", "modi"],
    ["mikro_speedup_zufall", "mikro_speedup_eingebettet", "mikro_zeit", "korrektheit"],
    ["workers", "chunksize", "dbsize", "treffer_erwartet"],
]


def build_context(data, summary):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return {"plt": plt, "data": data, "s": summary}


def save_figures(data, summary, pdf_path, results_dir):
    """Schreibt das mehrseitige PDF und die Einzeldiagramme; ein Fehler in einem Diagramm bricht nicht alles ab."""
    from matplotlib.backends.backend_pdf import PdfPages

    ctx = build_context(data, summary)
    plt = ctx["plt"]
    meta = data.get("meta", {})
    status = "" if meta.get("complete", True) else " (unvollständig)"
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    written = [pdf_path]
    with PdfPages(pdf_path) as pdf:
        for number, page in enumerate(PAGES, start=1):
            fig, axes = plt.subplots(2, 2, figsize=(11.69, 8.27))  # A4 quer
            fig.suptitle(f"Multi-Omics-Suche Python vs. C++, Seite {number}/{len(PAGES)}{status}", fontsize=13)
            for ax, name in zip(axes.flat, page):
                try:
                    DRAWERS[name](ax, ctx)
                except Exception as error:  # noqa: BLE001
                    no_data(ax, name, f"Fehler: {error}")
            fig.tight_layout(rect=(0, 0, 1, 0.95))
            pdf.savefig(fig)
            plt.close(fig)
    for name, drawer in DRAWERS.items():
        fig, ax = plt.subplots(figsize=(7.0, 4.6))
        try:
            drawer(ax, ctx)
            fig.tight_layout()
            target = Path(results_dir) / SINGLE_PLOTS[name]
            fig.savefig(target)
            written.append(target)
        except Exception as error:  # noqa: BLE001
            print(f"Diagramm {name} nicht erzeugt: {error}")
        plt.close(fig)
    return written


# ---------------------------------------------------------------------------
# Textbericht und LaTeX-Tabellen
# ---------------------------------------------------------------------------

def _num(value, digits=1):
    """Zahl im deutschen Format ($1.234{,}5$): Tausenderpunkt, Dezimalkomma."""
    if value is None:
        return "--"
    return f"{value:,.{digits}f}".replace(",", "#").replace(".", "{,}").replace("#", ".")


def _txt(value, digits=2, width=0):
    text = "n/a" if value is None else f"{value:,.{digits}f}"
    return text.rjust(width)


def format_report(data, summary):
    """Textbericht mit den Kennzahlen aller Teilexperimente."""
    meta = data.get("meta", {})
    lines = ["Multi-Omics-Experiment", "=" * 70,
             f"Messlauf: {meta.get('created', '?')}, Seed {meta.get('seed', '?')}, "
             f"Plattform {meta.get('platform', '?')}, {meta.get('logical_cpus', '?')} logische CPUs",
             f"Netzwerke in der Datenbank: {meta.get('omics_networks_total', '?')} "
             f"(Zufallsnetzwerke: {meta.get('random_networks', '?')}), C++-Bibliothek: {meta.get('csubgraph_lib')}",
             f"Wiederholungen: {meta.get('reps', '?')}, Worker: {meta.get('workers', '?')}", ""]

    correctness = summary.get("correctness")
    if correctness:
        lines += ["--- Korrektheit ---",
                  f"Paare {correctness['pairs']}, Vergleiche {correctness['comparisons']}, "
                  f"C++ geprüft: {'ja' if correctness['native'] else 'nein'}, identisch {correctness['agree']}, "
                  f"abweichend {correctness['disagree']}, Fehler {correctness['errors']}",
                  f"Verstöße: {correctness['violations'] or 'keine'}"]
        for kind, v in correctness["by_kind"].items():
            lines.append(f"  {PLANT_DISPLAY.get(kind, 'Zufall'):<12} Vergleiche {v['comparisons']:>6} "
                         f"identisch {v['agree']:>6} abweichend {v['disagree']:>4} Fehler {v['errors']:>4}")
        for example in correctness["examples"][:5]:
            lines.append(f"  Beispiel: {example}")
        lines.append("")

    micro = summary.get("micro")
    if micro:
        lines.append("--- Mikro-Benchmark (Median je Einzelvergleich) ---")
        for o in micro["overall"]:
            lines.append(f"  {MODE_DISPLAY[o['mode']]:<11} {KIND_DISPLAY.get(o['kind'], o['kind']):<12} "
                         f"Zellen {o['cells']:>3} Speedup geom. {_txt(o['speedup_geomean'])} "
                         f"(min {_txt(o['speedup_min'])}, max {_txt(o['speedup_max'])})")
        for c in micro["overhead"]:
            lines.append(f"  Aufrufkosten {DISPLAY[c['backend']]} (trivial 1x1): Median {_txt(c['median_ms'], 4)} ms, "
                         f"Mittel {_txt(c['mean_ms'], 4)} ms")
        lines.append("")

    search = summary.get("search")
    if search:
        lines += ["--- Suche (Ende-zu-Ende) ---",
                  f"{'Impl.':>7} {'Modus':>11} {'Summe[s]':>9} {'Mittel[s]':>9} {'Median':>8} {'p95':>8} "
                  f"{'Speedup':>8} {'geom.':>14} {'ms/Kand.':>9} {'Laden%':>7} {'Vergl.%':>8} {'Bauen%':>7} "
                  f"{'Fehler':>6} {'Treffer=':>8}"]
        for s in search["summary"]:
            ci = s["speedup_geomean_ci"]
            geo = (f"{_txt(s['speedup_geomean'])} [{_txt(ci[0])},{_txt(ci[1])}]"
                   if ci[0] is not None else _txt(s["speedup_geomean"]))
            lines.append(
                f"{DISPLAY[s['backend']]:>7} {MODE_DISPLAY[s['mode']]:>11} {s['sum_s']:>9.0f} {s['mean_s']:>9.2f} "
                f"{s['median_s']:>8.2f} {s['p95_s']:>8.2f} {_txt(s['speedup'], 2, 8)} {geo:>14} "
                f"{_txt(s['ms_per_candidate'], 4, 9)} {_txt((s['fetch_share'] or 0) * 100, 0, 7)} "
                f"{_txt((s['compare_share'] or 0) * 100, 0, 8)} {_txt((s['build_share'] or 0) * 100, 0, 7)} "
                f"{s['failed']:>6} {'ja' if s['matches_equal'] else 'NEIN':>8}")
        lines += [f"Speedup = Gesamtzeit {DISPLAY[search['reference']]} / Gesamtzeit der Zeile; geom. = geometrischer "
                  "Mittelwert der Speedups je Anfrage mit 95-%-Bootstrap-Intervall.",
                  f"Kohärent => unabhängig geprüft an {search['mode_check']['checked']} Messungen, Verstöße: "
                  f"{search['mode_check']['violations']}. Fehlgeschlagene Vergleiche insgesamt: {search['failed']}.",
                  "", "Trefferquote eingebetteter Netzwerke (Ground Truth):"]
        for r in search["recall"]:
            if r["expected"]:
                lines.append(f"  {label_of(r['backend'], r['mode']):<20} {r['found']}/{r['expected']} "
                             f"({_txt(100 * r['recall'], 1)} %), weitere Treffer {r['other_matches']}")
        lines.append("")

    workers = summary.get("workers")
    if workers:
        lines.append("--- Worker-Skalierung ---")
        for t in workers:
            lines.append(f"  {DISPLAY[t['backend']]:>7} {t['workers']:>2} Worker: gesamt {t['sum_total_s']:>8.1f} s "
                         f"(Speedup {_txt(t['speedup_total'])}), Vergleichen {t['sum_compare_s']:>8.1f} s "
                         f"(Speedup {_txt(t['speedup_compare'])}, Effizienz {_txt(t['efficiency_compare'])}), "
                         f"serieller Anteil (Amdahl) {_txt((t['amdahl'].get('total') or 0) * 100, 1)} %")
        lines.append("")

    chunk = summary.get("chunksize")
    if chunk:
        lines.append("--- Chunk-Größe ---")
        for t in chunk:
            lines.append(f"  {DISPLAY[t['backend']]:>7} Chunk {t['chunksize']:>5}: gesamt {t['sum_total_s']:>8.1f} s, "
                         f"Vergleichen {t['sum_compare_s']:>8.1f} s, relativ zum Besten {_txt(t['relative_to_best'])}")
        lines.append("")

    dbsize = summary.get("dbsize")
    if dbsize:
        lines.append("--- Datenbankgröße ---")
        for t in dbsize["table"]:
            lines.append(f"  {DISPLAY[t['backend']]:>7} {t['omics_networks']} Netzwerke: gesamt {t['sum_total_s']:>8.1f} s, "
                         f"Vergleichen {t['sum_compare_s']:>8.1f} s, Kandidaten {t['candidates']}")
        for f in dbsize["fits"]:
            lines.append(f"  Fit {DISPLAY[f['backend']]} {f['field']}: {_txt(f['ms_per_candidate'], 4)} ms je Einheit, "
                         f"Achsenabschnitt {_txt(f['intercept_s'], 2)} s, R^2 {_txt(f['r2'], 3)}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _table(caption, label, colspec, header, rows):
    lines = ["\\begin{table}[h]", "\t\\centering", "\t\\small", f"\t\\caption{{{caption}}}", f"\t\\label{{{label}}}",
             f"\t\\begin{{tabular}}{{@{{}}{colspec}@{{}}}}", "\t\t\\toprule", "\t\t" + " & ".join(header) + " \\\\",
             "\t\t\\midrule"]
    lines += ["\t\t" + " & ".join(str(c) for c in row) + " \\\\" for row in rows]
    return lines + ["\t\t\\bottomrule", "\t\\end{tabular}", "\\end{table}", ""]


def write_latex_tables(data, summary, path):
    """Tabellen für gen-db.tex als \\input-fähiges Fragment."""
    meta = data.get("meta", {})
    lines = ["% Automatisch erzeugt von src/experiment_search_multiomics.py -- nicht von Hand ändern.",
             f"% Messlauf: {meta.get('created', '?')}, Seed {meta.get('seed', '?')}", ""]

    search = summary.get("search")
    if search:
        rows = []
        for s in search["summary"]:
            rows.append([DISPLAY[s["backend"]], MODE_DISPLAY[s["mode"]], _num(s["sum_s"], 0), _num(s["mean_s"], 2),
                         _num(s["median_s"], 2), _num(s["speedup"], 2), _num(s["speedup_geomean"], 2),
                         _num(s["pairs_per_s"], 0), _num(s["ms_per_candidate"], 4),
                         _num((s["fetch_share"] or 0) * 100, 0)])
        lines += _table(
            f"Kennzahlen der Multi-Omics-Suche ({search['summary'][0]['queries']} Anfragen je Zeile, "
            f"Speedup relativ zu {DISPLAY[search['reference']]}, $\\Theta$ Vergleiche je Sekunde der Vergleichsphase).",
            "tab:mo_summary", "llrrrrrrrr",
            ["Variante", "Modus", "$T$ [s]", "Mittel [s]", "Median [s]", "$S$", "$\\bar S_{\\mathrm{geo}}$",
             "$\\Theta$ [1/s]", "$\\kappa$ [ms]", "Laden [\\%]"], rows)
        recall_rows = [[DISPLAY[r["backend"]], MODE_DISPLAY[r["mode"]], r["found"], r["expected"],
                        _num(100 * r["recall"], 1), r["other_matches"]]
                       for r in search["recall"] if r["expected"]]
        if recall_rows:
            lines += _table("Trefferquote der eingebetteten Netzwerke (Ground Truth) und weitere Treffer.",
                            "tab:mo_recall", "llrrrr",
                            ["Variante", "Modus", "gefunden", "erwartet", "Quote [\\%]", "weitere"], recall_rows)

    micro = summary.get("micro")
    if micro:
        rows = [[MODE_DISPLAY[o["mode"]], KIND_DISPLAY.get(o["kind"], o["kind"]), o["cells"],
                 _num(o["speedup_geomean"], 1), _num(o["speedup_min"], 1), _num(o["speedup_max"], 1)]
                for o in micro["overall"]]
        lines += _table("Mikro-Benchmark: Speedup C++ gegenüber Python je Einzelvergleich (Median, geometrisches Mittel über Zellen).",
                        "tab:mo_micro", "llrrrr", ["Modus", "Paare", "Zellen", "geom.", "min.", "max."], rows)
        rows = [[DISPLAY[c["backend"]], _num(c["median_ms"], 4), _num(c["mean_ms"], 4), _num(c["max_ms"], 4)]
                for c in micro["overhead"]]
        if rows:
            lines += _table("Aufrufkosten: trivialer $1\\times1$-Vergleich einer Schicht.", "tab:mo_overhead", "lrrr",
                            ["Variante", "Median [ms]", "Mittel [ms]", "Max. [ms]"], rows)

    workers = summary.get("workers")
    if workers:
        rows = [[DISPLAY[t["backend"]], t["workers"], _num(t["sum_total_s"], 1), _num(t["speedup_total"], 2),
                 _num(t["sum_compare_s"], 1), _num(t["speedup_compare"], 2), _num(t["efficiency_compare"], 2)]
                for t in workers]
        lines += _table("Skalierung mit der Worker-Anzahl (Modus kohärent).", "tab:mo_workers", "lrrrrrr",
                        ["Variante", "$p$", "$T$ [s]", "$S$", "$T_{\\mathrm{cmp}}$ [s]", "$S_{\\mathrm{cmp}}$", "$E_{\\mathrm{cmp}}$"], rows)

    chunk = summary.get("chunksize")
    if chunk:
        rows = [[DISPLAY[t["backend"]], t["chunksize"], _num(t["sum_total_s"], 1), _num(t["sum_compare_s"], 1),
                 _num(t["relative_to_best"], 2)] for t in chunk]
        lines += _table("Einfluss der Chunk-Größe (Modus kohärent).", "tab:mo_chunksize", "lrrrr",
                        ["Variante", "Chunk", "$T$ [s]", "$T_{\\mathrm{cmp}}$ [s]", "relativ"], rows)

    dbsize = summary.get("dbsize")
    if dbsize:
        rows = [[DISPLAY[t["backend"]], t["omics_networks"], t["candidates"], _num(t["sum_total_s"], 1),
                 _num(t["sum_compare_s"], 1), _num(t["speedup"], 2)] for t in dbsize["table"]]
        lines += _table("Skalierung mit der Datenbankgröße (Modus kohärent).", "tab:mo_dbsize", "lrrrrr",
                        ["Variante", "Netzwerke", "Kandidaten", "$T$ [s]", "$T_{\\mathrm{cmp}}$ [s]", "$S$"], rows)

    correctness = summary.get("correctness")
    if correctness:
        rows = [[PLANT_DISPLAY.get(k, "Zufall"), v["comparisons"], v["agree"], v["disagree"], v["errors"]]
                for k, v in correctness["by_kind"].items()]
        lines += _table("Korrektheit: Python-Referenz gegen C++ je Paartyp.", "tab:mo_correctness", "lrrrr",
                        ["Paartyp", "Vergleiche", "identisch", "abweichend", "Fehler"], rows)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return Path(path)


def write_outputs(json_path, pdf_path, results_dir):
    """PDF, Einzeldiagramme, Tabellen und Bericht aus einer JSON-Datei erzeugen."""
    with open(json_path, encoding="utf-8") as handle:
        data = json.load(handle)
    summary = analyze(data)
    stem = Path(pdf_path).stem
    written = []
    try:
        written += save_figures(data, summary, pdf_path, results_dir)
    except ImportError:
        print("Diagramme nicht erzeugt: matplotlib fehlt (pip install matplotlib).")
    written.append(write_latex_tables(data, summary, Path(results_dir) / f"{stem}_tabellen.tex"))
    report_path = Path(results_dir) / f"{stem}.txt"
    report_path.write_text(format_report(data, summary), encoding="utf-8")
    written.append(report_path)
    return written, summary


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

QUICK = {
    "networks": 1500, "reps": 1, "query_sizes": [6, 12, 20], "query_layers": [1, 2, 3],
    "correctness_pairs": 300, "micro_pairs": 20, "micro_layers": [1, 3], "micro_sizes": [8, 24],
    "worker_scaling": [1, 2], "worker_reps": 1, "chunksizes": [16, 256], "subset_queries": 3,
    "max_nodes": 30,
}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add = parser.add_argument
    add("--only", nargs="+", choices=PHASES, default=list(PHASES), help="nur diese Teilexperimente ausführen")
    add("--backends", nargs="+", choices=BACKENDS, default=list(BACKENDS), help="Implementierungen")
    add("--csubgraph-lib-path", default=None,
        help="Pfad zu libsubgraphlib.a (Datei oder Ordner); Standard: CSUBGRAPH_LIB_PATH aus .env")
    add("--workers", type=int, default=2, help="Worker für Suche, Chunk-Größe und Datenbankgröße (Standard 2)")
    add("--worker-scaling", type=int, nargs="+", default=[1, 2, 3, 4], help="Worker-Anzahlen für 'workers'")
    add("--reps", type=int, default=3, help="Wiederholungen der Suchen (Standard 3)")
    add("--worker-reps", type=int, default=2, help="Wiederholungen für workers/chunksize/dbsize (Standard 2)")
    add("--warmup", type=int, default=1, help="Verworfene Aufwärm-Suchen je Messreihe")
    add("--seed", type=int, default=42)
    add("--networks", type=int, default=20000, help="Zufallsnetzwerke in der Datenbank (Standard 20000)")
    add("--min-nodes", type=int, default=4, help="Mindestknotenzahl der Zufallsnetzwerke")
    add("--max-nodes", type=int, default=40, help="Höchstknotenzahl der Zufallsnetzwerke (höchstens 63)")
    add("--min-layers", type=int, default=2, help="Mindestschichtzahl der Zufallsnetzwerke")
    add("--max-layers", type=int, default=5, help=f"Höchstschichtzahl der Zufallsnetzwerke (höchstens {len(POOL_NAMES)})")
    add("--query-sizes", type=int, nargs="+", default=[4, 6, 8, 12, 16, 24, 32], help="Knotenzahlen der Anfragen")
    add("--query-layers", type=int, nargs="+", default=[1, 2, 3, 4], help="Schichtzahlen der Anfragen")
    add("--plants", type=int, default=3, help="eingebettete Netzwerke je Art (kohärent/unabhängig) und Anfrage")
    add("--plant-extra-nodes", type=int, default=12, help="höchstens so viele zusätzliche Knoten bei eingebetteten Netzwerken")
    add("--correctness-pairs", type=int, default=5000, help="Paare der Korrektheitsprüfung (0 = überspringen)")
    add("--micro-pairs", type=int, default=100, help="Paare je Zelle im Mikro-Benchmark")
    add("--micro-layers", type=int, nargs="+", default=[1, 2, 3, 4, 6, 8], help="Schichtzahlen im Mikro-Benchmark")
    add("--micro-sizes", type=int, nargs="+", default=[8, 16, 24, 32, 48, 63], help="n_B im Mikro-Benchmark")
    add("--chunksizes", type=int, nargs="+", default=[1, 8, 32, 128, 256, 1024, 4096], help="Chunk-Größen")
    add("--db-sizes", type=int, nargs="+", default=None,
        help="Zufallsnetzwerke je Stufe für 'dbsize' (Standard: 10, 25, 50, 100 %% von --networks)")
    add("--subset-queries", type=int, default=6, help="Anfragen für workers/chunksize/dbsize (Standard 6)")
    add("--results-dir", default=str(DEFAULT_RESULTS_DIR), help="Zielverzeichnis (Standard: src/results)")
    add("--plot-from", metavar="JSON", help="Nur PDF, Diagramme, Tabellen und Bericht aus einer JSON-Datei erzeugen")
    add("--rebuild-data", action="store_true", help="Experiment-Netzwerke vorab löschen und neu erzeugen")
    add("--cleanup", action="store_true", help="Experiment-Netzwerke am Ende löschen")
    add("--cleanup-only", action="store_true", help="Nur die Experiment-Netzwerke löschen und beenden")
    add("--quick", action="store_true", help="Kleiner Vorabtest (wenige Anfragen, kleine Datenbank)")
    return parser


def validate_args(parser, args):
    if args.min_nodes < 4 or args.max_nodes > multiomics_python.MAX_NODES or args.max_nodes < args.min_nodes:
        parser.error(f"--min-nodes >= 4, --max-nodes <= {multiomics_python.MAX_NODES} und min <= max erforderlich")
    if args.min_layers < 1 or args.max_layers > len(POOL_NAMES) or args.max_layers < args.min_layers:
        parser.error(f"Schichtzahlen müssen zwischen 1 und {len(POOL_NAMES)} liegen")
    if any(n < 4 or n + args.plant_extra_nodes > multiomics_python.MAX_NODES for n in args.query_sizes):
        parser.error("--query-sizes: Werte >= 4 und (Wert + --plant-extra-nodes) <= 63")
    if any(not 1 <= layers <= len(POOL_NAMES) for layers in args.query_layers):
        parser.error(f"--query-layers: Werte zwischen 1 und {len(POOL_NAMES)}")
    if any(not 1 <= n <= multiomics_python.MAX_NODES for n in args.micro_sizes) or any(l < 1 for l in args.micro_layers):
        parser.error("--micro-sizes zwischen 1 und 63, --micro-layers >= 1")
    if len(set(args.backends)) != len(args.backends):
        parser.error("--backends enthält eine Implementierung doppelt")
    if args.reps < 1 or args.worker_reps < 1 or args.networks < 0:
        parser.error("--reps, --worker-reps >= 1 und --networks >= 0")
    if args.db_sizes is None:
        args.db_sizes = sorted({max(1, int(args.networks * f)) for f in (0.1, 0.25, 0.5, 1.0)})


def main():
    parser = build_parser()
    args = parser.parse_args()
    results_dir = Path(args.results_dir)

    if args.plot_from:
        stem = Path(args.plot_from).stem
        written, summary = write_outputs(args.plot_from, results_dir / f"{stem}.pdf", results_dir)
        for path in written:
            print(f"geschrieben: {path}")
        return

    if args.quick:
        for key, value in QUICK.items():
            if getattr(args, key) == parser.get_default(key):
                setattr(args, key, value)
    validate_args(parser, args)

    if args.cleanup_only:
        print(f"{delete_experiment('TRUE', ())} Experiment-Netzwerke gelöscht.")
        analyze_tables()
        return

    phases = [p for p in PHASES if p in args.only]
    if args.correctness_pairs == 0 and "correctness" in phases:
        phases.remove("correctness")
    needs_db = any(p in DB_PHASES for p in phases)

    lib, lib_setting = resolve_lib(args.csubgraph_lib_path)
    if "cpp" in args.backends and not lib:
        raise SystemExit(
            f"libsubgraphlib.a nicht gefunden (Einstellung: {lib_setting!r}). "
            "CSUBGRAPH_LIB_PATH in der .env oder --csubgraph-lib-path auf libsubgraphlib.a setzen, "
            "oder --backends python wählen. Ein stiller Fallback auf Python würde den Vergleich verfälschen.")
    if "cpp" in args.backends:
        configure_backend("cpp", lib)  # bricht mit Grund ab, wenn die Bibliothek MultiOmics nicht enthält
    sanity_check_components(args.seed)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = results_dir / f"search_multiomics_{stamp}.json"
    pdf_path = results_dir / f"search_multiomics_{stamp}.pdf"

    specs = build_query_specs(args.seed, args.query_sizes, args.query_layers, args.plants, args.plant_extra_nodes)
    print(f"Multi-Omics-Experiment: Teilexperimente {phases}, Implementierungen {args.backends}, "
          f"{len(specs)} Anfragen, Wiederholungen {args.reps}, Worker {args.workers}, Seed {args.seed}")
    if lib:
        print(f"csubgraph: {lib}")

    meta = {
        "created": datetime.now().isoformat(timespec="seconds"), "seed": args.seed, "phases": phases,
        "backends": args.backends, "workers": args.workers, "worker_scaling": args.worker_scaling,
        "reps": args.reps, "worker_reps": args.worker_reps, "warmup": args.warmup,
        "random_networks": args.networks, "node_range": [args.min_nodes, args.max_nodes],
        "layer_range": [args.min_layers, args.max_layers], "layer_pool": POOL_NAMES,
        "query_sizes": args.query_sizes, "query_layers": args.query_layers, "plants_per_kind": args.plants,
        "chunksizes": args.chunksizes, "db_sizes": args.db_sizes, "default_chunksize":
            subgraph_executor.DEFAULT_CHUNKSIZE, "csubgraph_lib": lib,
        "csubgraph_lib_sha256": hashlib.sha256(Path(lib).read_bytes()).hexdigest() if lib else None,
        "logical_cpus": os.cpu_count(), "python": platform.python_version(), "numpy": np.__version__,
        "platform": platform.platform(), "arguments": vars(args), "complete": False,
    }
    data = {"meta": meta}

    with instrumented() as (timer, failures):
        ctx = Context(args, data, lib, json_path, timer, failures, specs)
        try:
            if needs_db:
                print("\nDatenbank vorbereiten ...", flush=True)
                meta["omics_networks_total"] = prepare_population(args, specs)
                meta["postgres"] = scalar("SELECT version()")
                data["queries"] = [public_spec(s) for s in specs]
                print(f"  {meta['omics_networks_total']} Multi-Omics-Netzwerke in der Datenbank", flush=True)
            save_json(ctx)

            runners = {"correctness": run_correctness, "micro": run_micro, "search": run_search_grid,
                       "workers": run_workers, "chunksize": run_chunksize, "dbsize": run_dbsize}
            for phase in phases:
                print(f"\n=== Teilexperiment: {phase} ===", flush=True)
                started = time.perf_counter()
                runners[phase](ctx)
                meta.setdefault("phase_seconds", {})[phase] = time.perf_counter() - started
                if phase == "dbsize":
                    meta["omics_networks_total"] = count_omics_networks()
                save_json(ctx)
        finally:
            save_json(ctx)
        save_json(ctx, final=True)

    print(f"\nJSON: {json_path}")
    written, summary = write_outputs(json_path, pdf_path, results_dir)
    for path in written:
        print(f"geschrieben: {path}")
    print()
    print(format_report(data, summary))

    if args.cleanup and needs_db:
        print(f"{delete_experiment('TRUE', ())} Experiment-Netzwerke gelöscht (--cleanup).")
        analyze_tables()


if __name__ == "__main__":
    main()
