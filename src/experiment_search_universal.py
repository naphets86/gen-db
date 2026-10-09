"""
Experiment: Universelle Kodierung, Indexsuche gegen Einzelvergleiche (Python und C++).

Experimenteller Teil des Kapitels "Universelle Kodierung" (science/gen-db-universelle-kodierung.tex,
Abschnitt "Vorbereitung des zweiten Schritts"): Es vergleicht bei gleichen Anfragen und gleichen
Daten die Indexsuche mit Einzelvergleichen in Python und mit der nativen Bibliothek. Aufbau und
Auswertung folgen experiment_search_workers.py, experiment_search_backends.py und
experiment_search_multiomics.py.

Verglichene Varianten (``--backends`` wählt aus; Referenz für Speedups ist ``python``):

index      crud.search_universal: Suche über den SQL-Paarindex (Tabelle universal_pairs), ohne
           Prozess-Pool. Im Modus independent ist das Suchergebnis der Schnitt der Trefferlisten
           (Satz "Korrektheit des Index"), im Modus coherent werden die Kandidaten verifiziert.
python     Einzelvergleiche in Python mit universal_core.compare_stacks (subgraph_executor.
           compare_many_universal, Prozess-Pool): Alle gespeicherten Stapel des Schemas mit
           ausreichender Länge werden geladen und einzeln verglichen, ohne Index.
mo_python  bisherige Multi-Omics-Pipeline (crud.search_multiomics) mit der Python-Implementierung
           multiomics_python (Vorfilter über Schichtnamen und Knotenzahl, Einzelvergleiche im Pool).
cpp        dieselbe Pipeline mit der nativen Bibliothek (MultiOmics aus csubgraph über
           CSUBGRAPH_LIB_PATH). Es wird geprüft, dass kein stiller Fallback auf Python stattfindet.

Teilexperimente (``--only`` wählt einzelne aus):

correctness  Korrektheit ohne Datenbank: universal_core gegen multiomics_python (und gegen C++) auf
             Zufallspaaren, eingebetteten, identischen und umgekehrten Paaren, beide Modi, auch auf
             Schichtauswahlen (Projektion). Invarianten: Symmetrie, kohärent => unabhängig,
             Monotonie unter Projektion. Zusätzlich im Speicher: PairIndex gegen Einzelvergleiche
             über alle gespeicherten Stapel (Treffer, Gegenrichtung, Klassifikation), auch nach
             Löschen und erneutem Einfügen.
micro        Mikro-Benchmark ohne Datenbank: Zeit je Einzelvergleich (universal_core, multiomics_python,
             C++) nach Schichtzahl L, Knotenzahl n, Modus und Paartyp, dazu die Aufrufkosten.
memory       Indexsuche im Speicher (PairIndex) gegen lineare Suche mit Einzelvergleichen in
             Abhängigkeit von der Zahl N gespeicherter Stapel: Aufbau- und Anfragezeit, Trefferlast H
             (Satz "Laufzeit der Indexsuche"), lineare Anpassung der Anfragezeit an H, Exponent der
             Skalierung in N (Korollar "Unabhängigkeit von N").
search       Ende-zu-Ende-Suche mit allen Varianten: Gitter aus Anfragen (Schichtzahl x Knotenzahl x
             Typ) x Variante x Modus x Wiederholungen, Phasen (Laden, Vergleichen, Rest), Kandidaten,
             Treffer, Speedup mit Konfidenzintervall, Übereinstimmung der Treffer aller Varianten,
             Trefferquote der eingebetteten Netzwerke (Ground Truth).
workers      Skalierung mit 1, 2, 3, ... Workern (nur Varianten mit Prozess-Pool).
chunksize    Einfluss der Chunk-Größe der parallelen Einzelvergleiche.
dbsize       Skalierung mit der Datenbankgröße (Zahl der Netzwerke), lineare Anpassung und Exponent
             t ~ N^b je Variante, dazu Speicherbedarf und Einfügezeit des Index.

Versuchsaufbau
- Schema: ein Matrixschema (universal_schema.matrix_schema, lokale Koordinaten) mit ``--schema-layers``
  Schichten aus dem Pool Genom, Transkriptom, Proteom, Metabolom, Epigenom, Lipidom. Jedes Netzwerk
  besitzt alle Schichten des Schemas; dadurch bilden alle Varianten dieselbe Datenbasis desselben
  Schemas (Voraussetzung der Sätze des Kapitels). Ein Netzwerk wird gleichzeitig als universelle
  Struktur (universal_structures, Wörterbuch, Paarindex) und als Multi-Omics-Netzwerk (omics_*)
  abgelegt; beides stammt aus denselben Matrizen. Für Matrixschemas ist der kodierte Stapel auf den
  Schichten des Schemas genau der Matrixstapel (universal_schema.encode_matrices).
- Daten: synthetische Netzwerke mit network_type 'universal_experiment' (Zufallsnetzwerke
  ``uc_exp_rand_...``, Anzahl --networks, deterministisch aus --seed) und je eingebetteter Anfrage
  Netzwerke mit bekannter Lösung (``uc_exp_plant_...``: identische Kopie, kohärent eingebettet, nur
  unabhängig eingebettet). Damit gibt es eine Ground Truth zusätzlich zum Vergleich der Varianten.
  Vorhandene andere Netzwerke werden nicht verändert.
- Anfragen entstehen aus dem Seed. Je (Schichtzahl, Knotenzahl) gibt es eine Zufallsanfrage und
  eine eingebettete Anfrage. Aktive Schichten sind die Schichten der Anfrage; die übrigen
  Schichten des Schemas sind leer und nicht aktiv. Jede Anfrageschicht enthält mindestens eine Kante.
- Gleiche Trefferbedingung: Treffer sind Q enthalten in M_k (keep_B, equal_keep_A, equal_keep_B).
  Anfragen haben mindestens vier Knoten; für Stapel der Länge 1 (keine Paare) unterscheiden sich
  Indexsuche und compare_stacks per Definition (siehe PairIndex.classify) und sie werden nicht
  verwendet.
- Wiederholungen: Jede Messung wird --reps mal wiederholt; die Reihenfolge der Varianten wechselt je
  Wiederholung, die Reihenfolge der Anfragen wird je Wiederholung zufällig (aus dem Seed) gemischt. Je
  Messreihe gibt es verworfene Aufwärmanfragen.
- Gemessen wird die Wanduhrzeit der gesamten Suche (SQL, Vergleiche, Prozesskommunikation,
  Trefferliste). Phasen: Laden (bis zum ersten Vergleich bzw. bis alle Kandidaten geladen sind),
  Vergleichen (Zeit in den Vergleichen), Rest (Umwandlung der Stapel, Treffer bauen). Bei ``index``
  umfasst Laden das Lesen der Indexlisten und das Laden der Kandidaten; die Vergleiche dort
  klassifizieren nur die Kandidaten (im Modus independent sind alle Kandidaten Treffer).
- Der Server darf während des Experiments nicht laufen. Andere Multi-Omics-Netzwerke in der
  Datenbank (z. B. vom Multi-Omics-Experiment) sieht nur die Pipeline der Varianten mo_python und
  cpp (anderes Schema); sie verlangsamen diese und werden im Bericht als Warnung vermerkt. Besser
  vorher ``python src/experiment_search_multiomics.py --cleanup-only`` ausführen.
- Beim Löschen vieler Netzwerke legt das Skript kurzzeitig einen Hilfsindex auf
  universal_pairs(network_id) an, weil die Kaskade von biological_networks sonst je Netzwerk die
  ganze Indextabelle durchsucht; der Index wird danach wieder entfernt.

Aufruf (im Projektordner, damit die .env gefunden wird):
    python src/experiment_search_universal.py                  # vollständig, dauert Stunden
    python src/experiment_search_universal.py --quick          # kleiner Vorabtest
    python src/experiment_search_universal.py --only correctness micro memory
    python src/experiment_search_universal.py --backends index python --networks 5000
    python src/experiment_search_universal.py --csubgraph-lib-path C:\\...\\libsubgraphlib.a
    python src/experiment_search_universal.py --cleanup-only   # Experiment-Netzwerke und -Schemata löschen

Ergebnisse (src/results/, Dateiname mit Zeitstempel):
- search_universal_<zeit>.json          : Metadaten, Anfragen, alle Einzelmessungen, Auswertung
- search_universal_<zeit>.pdf           : Diagramme auf mehreren Seiten
- search_universal_<zeit>.txt           : Textbericht (Kennzahlen aller Teilexperimente)
- search_universal_<zeit>_tabellen.tex  : Tabellen für gen-db.tex (\\input{...})
- plot27_universal_*.pdf ... plot45_universal_*.pdf : Einzeldiagramme für \\includegraphics

Die JSON-Datei wird während der Messung regelmäßig aktualisiert (ein Abbruch verliert höchstens
einige Sekunden). Aus einer vorhandenen JSON-Datei lassen sich PDF, Diagramme, Tabellen und Bericht
ohne neuen Messlauf erzeugen:
    python src/experiment_search_universal.py --plot-from src/results/search_universal_<zeit>.json

Die Experiment-Netzwerke bleiben standardmäßig in der Datenbank (Wiederholbarkeit, schneller
Neustart); --cleanup entfernt sie am Ende, --rebuild-data erzeugt sie neu. Für die Diagramme wird
matplotlib benötigt. Für die Variante cpp wird libsubgraphlib.a mit MultiOmics benötigt.
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
from backend import (crud, csubgraph_native, multiomics_python, subgraph_executor,  # noqa: E402
                     universal_core, universal_index, universal_schema)
from psycopg2.extras import execute_values  # noqa: E402

DEFAULT_RESULTS_DIR = SRC_DIR / "results"
BACKENDS = ("index", "python", "mo_python", "cpp")
POOL_BACKENDS = ("python", "mo_python", "cpp")  # Varianten mit Prozess-Pool
MICRO_BACKENDS = POOL_BACKENDS
REFERENCE = "python"
# Name des Multi-Omics-Algorithmus in subgraph_executor.get_multiomics_backend_name()
EXPECTED_NAME = {"mo_python": "python", "cpp": "csubgraph"}
DISPLAY = {"index": "Paarindex (SQL)", "python": "Einzelvergleiche Python",
           "mo_python": "Multi-Omics Python", "cpp": "Multi-Omics C++"}
SHORT = {"index": "Index", "python": "Python", "mo_python": "MO-Python", "cpp": "C++"}
COLORS = {"index": "#2ca02c", "python": "#1f77b4", "mo_python": "#9467bd", "cpp": "#d62728"}
MODES = tuple(universal_core.MODES)  # ("coherent", "independent")
MODE_DISPLAY = {"coherent": "kohärent", "independent": "unabhängig"}
KIND_DISPLAY = {"random": "Zufall", "embedded": "eingebettet"}
PLANT_DISPLAY = {"exact": "identisch", "coherent": "kohärent", "independent": "unabhängig",
                 "reversed": "umgekehrt"}
PHASES = ("correctness", "micro", "memory", "search", "workers", "chunksize", "dbsize")
DB_PHASES = ("search", "workers", "chunksize", "dbsize")
FAILED_RE = re.compile(r"(\d+) of (\d+) comparisons failed")

EXPERIMENT_TYPE = "universal_experiment"
SCHEMA_PREFIX = "uc_exp_"
RAND_PREFIX = "uc_exp_rand_"
PLANT_PREFIX = "uc_exp_plant_"
HELPER_INDEX = "idx_exp_universal_pairs_network"
INSERT_BATCH = 500

# Schichten (Name, Kantenwahrscheinlichkeit)
LAYER_POOL = [("Genom", 0.12), ("Transkriptom", 0.25), ("Proteom", 0.30),
              ("Metabolom", 0.20), ("Epigenom", 0.15), ("Lipidom", 0.22)]
DENSITY = dict(LAYER_POOL)
POOL_NAMES = [name for name, _ in LAYER_POOL]
ORGANISMS = ["Homo sapiens", "Mus musculus", "E. coli", "S. cerevisiae",
             "D. melanogaster", "C. elegans", "A. thaliana"]
MAX_NODES = multiomics_python.MAX_NODES
LABELS = [f"Knoten{i + 1:02d}" for i in range(MAX_NODES)]

# Ergebnisse von universal_core.compare_stacks, die als Treffer gelten
MATCH_NAMES = {"KEEP_B", "EQUAL_KEEP_A", "EQUAL_KEEP_B", "IDENTICAL"}
EXPECTED_RESULTS = {
    "coherent": MATCH_NAMES,
    "exact": {"IDENTICAL"},
    "reversed": {"KEEP_A", "EQUAL_KEEP_A", "EQUAL_KEEP_B", "IDENTICAL"},
}

SINGLE_PLOTS = {
    "gesamtzeit_speedup": "plot27_universal_gesamtzeit_speedup.pdf",
    "verteilung_antwortzeiten": "plot28_universal_verteilung_antwortzeiten.pdf",
    "phasen": "plot29_universal_phasen.pdf",
    "skalierung_kandidaten": "plot30_universal_skalierung_kandidaten.pdf",
    "schichten": "plot31_universal_schichten.pdf",
    "knoten": "plot32_universal_knoten.pdf",
    "selektivitaet": "plot33_universal_selektivitaet.pdf",
    "modi": "plot34_universal_modi.pdf",
    "mikro_zeit": "plot35_universal_mikro_zeit.pdf",
    "mikro_speedup_zufall": "plot36_universal_mikro_speedup_zufall.pdf",
    "mikro_speedup_eingebettet": "plot37_universal_mikro_speedup_eingebettet.pdf",
    "korrektheit": "plot38_universal_korrektheit.pdf",
    "memory_zeit": "plot39_universal_memory_zeit.pdf",
    "memory_trefferlast": "plot40_universal_memory_trefferlast.pdf",
    "dbsize": "plot41_universal_dbsize.pdf",
    "speicher": "plot42_universal_speicher.pdf",
    "workers": "plot43_universal_workers.pdf",
    "chunksize": "plot44_universal_chunksize.pdf",
    "treffer_erwartet": "plot45_universal_treffer_erwartet.pdf",
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


def loglog_fit(xs, ys):
    """Potenzgesetz y ~ x^b (Gerade im doppelt logarithmischen Raum) -> (b, R^2) oder (None, None)."""
    points = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None and x > 0 and y > 0]
    if len(points) < 3 or len({x for x, _ in points}) < 2:
        return None, None
    lx = np.log([x for x, _ in points])
    ly = np.log([y for _, y in points])
    slope, intercept = np.polyfit(lx, ly, 1)
    predicted = slope * lx + intercept
    ss_res = float(np.sum((ly - predicted) ** 2))
    ss_tot = float(np.sum((ly - np.mean(ly)) ** 2))
    return float(slope), (1 - ss_res / ss_tot if ss_tot > 0 else None)


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
# Synthetische Daten und Kodierung
# ---------------------------------------------------------------------------

def random_layer(rng, n, p, nonempty=False):
    """Zufällige gerichtete Schicht ohne Schleifen (wie db-populate.py); optional mit mindestens einer Kante."""
    matrix = (rng.random((n, n)) < p).astype(int)
    np.fill_diagonal(matrix, 0)
    if nonempty and not matrix.any():
        matrix[0, 1] = 1
    return matrix


def random_stack(rng, n, names, nonempty=False):
    return [random_layer(rng, n, DENSITY.get(name, 0.25), nonempty) for name in names]


def np_components(matrix):
    """Zeilenkomponenten (Spaltenbitmuster) wie multiomics_python.row_components, vektorisiert."""
    n = matrix.shape[0]
    weights = np.left_shift(np.int64(1), np.arange(n, dtype=np.int64))
    return (matrix.astype(np.int64) * weights[:, None]).sum(axis=0).tolist()


def fast_stack(matrices):
    """
    Kodierter Stapel eines Matrixschemas: Existenzschicht (Komponente j = {j}) gefolgt von den
    Schichten s_j = {i : A[i][j] = 1}. Entspricht universal_schema.encode_matrices (lokale
    Koordinaten), ist aber für große Zahlen von Netzwerken schnell (siehe sanity_check_encoding).
    """
    n = matrices[0].shape[0]
    layers = [tuple(frozenset([j]) for j in range(n))]
    for matrix in matrices:
        layers.append(tuple(frozenset(np.flatnonzero(column).tolist()) for column in matrix.T))
    return universal_core.Stack(tuple(layers))


def to_lists(stack):
    return [m.tolist() for m in stack]


def pick_names(rng, count, pool):
    """Zufällige Schichtnamen aus dem Pool, in Pool-Reihenfolge."""
    indices = sorted(int(i) for i in rng.choice(len(pool), size=count, replace=False))
    return [pool[i] for i in indices]


def embed_stack(rng, stack_a, n_b, names, kind):
    """
    Erzeugt einen Schichtstapel B (n_b Knoten), der A (n_a <= n_b Knoten) enthält.

    kind 'coherent'    : alle Schichten an derselben Position und demselben Spaltenpaar von A
    kind 'independent' : je Schicht andere Position und anderes Spaltenpaar (meist nur im
                         Modus 'independent' ein Treffer)
    kind 'exact'       : identische Kopie (n_b muss n_a entsprechen)

    Zwei benachbarte Spalten von A werden in zwei benachbarte Spalten von B kopiert, die Zeilen
    ab n_a bleiben 0; dadurch sind die Komponenten dieser Spalten in A und B gleich.
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


def full_matrices(schema_names, given):
    """Matrizen in Schemareihenfolge; nicht angegebene Schichten sind leer."""
    n = next(iter(given.values())).shape[0]
    return [given.get(name, np.zeros((n, n), dtype=int)) for name in schema_names]


def sanity_check_encoding(args, schema):
    """Prüft, dass die schnellen Hilfen der offiziellen Kodierung und der Referenz entsprechen."""
    rng = np.random.default_rng([args.seed, 1])
    names = [relation.name for relation in schema.relations]
    for n in (2, 5, 17, 40, 63):
        matrices = [random_layer(rng, n, 0.3) for _ in names]
        if np_components(matrices[0]) != list(multiomics_python.row_components(matrices[0].tolist())):
            raise SystemExit(f"Zeilenkomponenten stimmen für n={n} nicht überein (Programmfehler).")
        official = universal_schema.encode_matrices(schema, LABELS[:n], [m.tolist() for m in matrices])
        if fast_stack(matrices) != official:
            raise SystemExit(f"Kodierung stimmt für n={n} nicht mit encode_matrices überein (Programmfehler).")
        if official.layers[1:] != universal_core.stack_from_matrices([m.tolist() for m in matrices]).layers:
            raise SystemExit(f"Kodierung stimmt für n={n} nicht mit stack_from_matrices überein.")


# ---------------------------------------------------------------------------
# Aufbau des Experiments (Schema, Anfragen, eingebettete Netzwerke)
# ---------------------------------------------------------------------------

def schema_names(args):
    """Schichtnamen des Experiment-Schemas (die ersten --schema-layers des Pools)."""
    return POOL_NAMES[:args.schema_layers]


def make_schema(args):
    """Matrixschema mit lokalen Koordinaten, eine Schicht je Name."""
    return universal_schema.matrix_schema(schema_names(args), name=f"{SCHEMA_PREFIX}l{args.schema_layers}")


def make_plants(rng, spec, names_all, per_kind, extra_nodes):
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
            n_b = n if kind == "exact" else min(MAX_NODES, n + int(rng.integers(0, extra_nodes + 1)))
            embedded = dict(zip(names, embed_stack(rng, stack, n_b, names, kind)))
            full = [embedded[name] if name in embedded else random_layer(rng, n_b, DENSITY[name])
                    for name in names_all]
            valid = {mode: bool(multiomics_python.contains(
                query_lists, [embedded[name].tolist() for name in names], mode)) for mode in MODES}
            plants.append({"kind": kind, "index": k, "nodes": n_b, "stack": full, "valid": valid, "id": None})
    return plants


def build_query_specs(args, schema):
    """
    Anfragen: je (Schichtzahl, Knotenzahl) eine Zufallsanfrage ('random', ohne eingebettete
    Treffer) und eine eingebettete Anfrage ('embedded').
    """
    names_all = schema_names(args)
    specs = []
    for layers in args.query_layers:
        for n in args.query_sizes:
            for kind in ("random", "embedded"):
                rng = np.random.default_rng([args.seed, 11, layers, n, 0 if kind == "random" else 1])
                names = pick_names(rng, layers, names_all)
                stack = random_stack(rng, n, names, nonempty=True)
                labels = LABELS[:n]
                given = dict(zip(names, stack))
                spec = {
                    "index": len(specs), "kind": kind, "layers": layers, "nodes": n,
                    "names": names, "labels": labels, "stack": stack,
                    "matrices": to_lists(stack), "edges": int(sum(int(m.sum()) for m in stack)),
                    "relations": {name: [(labels[int(i)], labels[int(j)]) for i, j in zip(*np.nonzero(m))]
                                  for name, m in given.items()},
                    "stack_u": fast_stack(full_matrices(names_all, given)),
                    "active": tuple(schema.layout[("bin", name, 1)] for name in names),
                    "plants": [], "expected": {mode: [] for mode in MODES},
                }
                if kind == "embedded":
                    spec["plants"] = make_plants(rng, spec, names_all, args.plants, args.plant_extra_nodes)
                specs.append(spec)
    return specs


def public_spec(spec):
    """Anfrage ohne Matrizen und Stapel für die JSON-Datei."""
    return {
        "index": spec["index"], "kind": spec["kind"], "layers": spec["layers"], "nodes": spec["nodes"],
        "names": spec["names"], "edges": spec["edges"], "expected": spec["expected"],
        "plants": [{"id": p["id"], "kind": p["kind"], "nodes": p["nodes"], "valid": p["valid"]}
                   for p in spec["plants"]],
    }


# ---------------------------------------------------------------------------
# Datenbank: Experiment-Netzwerke anlegen, verkleinern, löschen
# ---------------------------------------------------------------------------

INSERT_COMPONENTS_SQL = """
    INSERT INTO universal_components (schema_id, layer_index, members_hash, members)
    SELECT %s, (e->>0)::int, e->>1, ARRAY(SELECT jsonb_array_elements_text(e->2)::bigint)
    FROM jsonb_array_elements(%s::jsonb) AS e
    ON CONFLICT (schema_id, layer_index, members_hash) DO NOTHING
"""


def population_tag(args):
    return f"s{args.seed}n{args.min_nodes}-{args.max_nodes}k{args.schema_layers}"


def random_prefix(tag):
    return f"{RAND_PREFIX}{tag}_"


def generate_random_network(ctx, index):
    """Zufallsnetzwerk Nummer index (deterministisch aus Seed und Index), alle Schichten des Schemas."""
    args = ctx.args
    rng = np.random.default_rng([args.seed, 7, index])
    n = int(rng.integers(args.min_nodes, args.max_nodes + 1))
    organism = ORGANISMS[int(rng.integers(0, len(ORGANISMS)))]
    stack = random_stack(rng, n, ctx.names)
    return {
        "name": f"{random_prefix(ctx.tag)}{index:07d}", "organism": organism,
        "description": f"Synthetisches Netzwerk ({len(ctx.names)} Schichten, {n} Knoten)",
        "labels": LABELS[:n], "stack": stack,
    }


def insert_networks(ctx, records):
    """
    Fügt Netzwerke stapelweise ein: biological_networks, omics_networks, omics_layers (für die
    Multi-Omics-Pipeline) und universal_structures, universal_components, universal_pairs (für die
    Indexsuche). Die Zeilen entsprechen denen von crud.create_multiomics_network und
    crud.create_universal_structure.
    """
    if not records:
        return []
    stacks = [fast_stack(record["stack"]) for record in records]
    with crud.get_db_connection() as conn:
        cursor = crud.get_db_cursor(conn)
        cursor.execute(
            "SELECT nextval(pg_get_serial_sequence('biological_networks', 'network_id')) AS id "
            "FROM generate_series(1, %s)", (len(records),))
        ids = sorted(int(row["id"]) for row in cursor.fetchall())

        network_rows, omics_rows, layer_rows, structure_rows = [], [], [], []
        for network_id, record, stack in zip(ids, records, stacks):
            components = [np_components(m) for m in record["stack"]]
            edges = int(sum(int(m.sum()) for m in record["stack"]))
            layers_json = json.dumps(stack.to_lists(), separators=(",", ":"))
            network_rows.append((network_id, record["name"], EXPERIMENT_TYPE, record["organism"],
                                 record["description"], len(record["labels"]), edges))
            omics_rows.append((network_id, record["labels"], len(ctx.names),
                               crud.compute_signature_hash(components)))
            for index, (name, matrix, comps) in enumerate(zip(ctx.names, record["stack"], components)):
                layer_rows.append((network_id, index, name, matrix.tolist(), comps, int(matrix.sum())))
            structure_rows.append((network_id, ctx.schema_id, stack.length, record["labels"], layers_json,
                                   hashlib.sha256(layers_json.encode()).hexdigest()))

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
        execute_values(
            cursor,
            "INSERT INTO universal_structures (network_id, schema_id, length, entity_names, layers, "
            "signature_hash) VALUES %s",
            structure_rows, template="(%s, %s, %s, %s::text[], %s::jsonb, %s)", page_size=200)

        # Wörterbuch (je Schicht und Komponente eine Zahl) und Paarindex
        digests, distinct = {}, {}
        for stack in stacks:
            for layer_index, layer in enumerate(stack.layers):
                for component in layer:
                    digest = digests.get(component)
                    if digest is None:
                        digest = digests[component] = crud.component_hash(component)
                    distinct[(layer_index, digest)] = component
        payload = [[layer_index, digest, sorted(component)]
                   for (layer_index, digest), component in sorted(distinct.items())]
        cursor.execute(INSERT_COMPONENTS_SQL, (ctx.schema_id, json.dumps(payload)))
        component_ids = crud._component_ids(cursor, ctx.schema_id, [digest for _, digest in distinct])

        pair_rows = []
        for network_id, stack in zip(ids, stacks):
            for layer_index, layer in enumerate(stack.layers):
                sequence = [component_ids[(layer_index, digests[component])] for component in layer]
                for kind, pairs in (("cyc", universal_core.cyclic_pairs(sequence)),
                                    ("lin", universal_core.linear_pairs(sequence))):
                    for first, second in pairs:
                        pair_rows.append((ctx.schema_id, layer_index, kind, first, second,
                                          network_id, stack.length))
        execute_values(
            cursor,
            "INSERT INTO universal_pairs (schema_id, layer_index, kind, first_id, second_id, "
            "network_id, length) VALUES %s", pair_rows, page_size=5000)
    return ids


@contextmanager
def helper_index():
    """
    Hilfsindex auf universal_pairs(network_id) während des Löschens: Die Kaskade löscht sonst je
    Netzwerk mit einem Durchlauf der ganzen Indextabelle. Wird danach wieder entfernt, damit
    Einfüge- und Suchmessungen den Zustand von init-db.sql widerspiegeln.
    """
    created = False
    try:
        with crud.get_db_connection() as conn:
            conn.cursor().execute(f"CREATE INDEX IF NOT EXISTS {HELPER_INDEX} ON universal_pairs(network_id)")
        created = True
    except Exception as error:  # noqa: BLE001
        print(f"  Hinweis: Hilfsindex nicht angelegt ({error}); das Löschen kann lange dauern.")
    try:
        yield
    finally:
        if created:
            with crud.get_db_connection() as conn:
                conn.cursor().execute(f"DROP INDEX IF EXISTS {HELPER_INDEX}")


def delete_experiment(condition_sql, params):
    """Löscht Experiment-Netzwerke (CASCADE entfernt Stapel, Paare und Schichten); gibt die Anzahl zurück."""
    with helper_index():
        with crud.get_db_connection() as conn:
            cursor = crud.get_db_cursor(conn)
            cursor.execute(
                f"DELETE FROM biological_networks WHERE network_type = %s AND {condition_sql}",
                (EXPERIMENT_TYPE, *params))
            return cursor.rowcount


def delete_schemas():
    """Löscht die Experiment-Schemata ohne Strukturen (CASCADE entfernt das Wörterbuch)."""
    with crud.get_db_connection() as conn:
        cursor = crud.get_db_cursor(conn)
        cursor.execute(
            "DELETE FROM universal_schemas WHERE starts_with(name, %s) AND NOT EXISTS "
            "(SELECT 1 FROM universal_structures us WHERE us.schema_id = universal_schemas.schema_id)",
            (SCHEMA_PREFIX,))
        return cursor.rowcount


def scalar(sql, params=()):
    with crud.get_db_connection() as conn:
        cursor = crud.get_db_cursor(conn)
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return list(row.values())[0]


def count_structures(ctx):
    return int(scalar("SELECT COUNT(*) FROM universal_structures WHERE schema_id = %s", (ctx.schema_id,)))


def analyze_tables():
    """Aktualisiert die Planer-Statistik nach dem Anlegen oder Löschen vieler Zeilen."""
    with crud.get_db_connection() as conn:
        cursor = conn.cursor()
        for table in ("biological_networks", "omics_networks", "omics_layers", "universal_structures",
                      "universal_components", "universal_pairs"):
            cursor.execute(f"ANALYZE {table}")


def storage_stats(ctx):
    """Größe der Tabellen (gesamt, inkl. Indizes) und Zeilenzahlen des Experiment-Schemas."""
    stats = {}
    for key, table in (("pairs", "universal_pairs"), ("structures", "universal_structures"),
                       ("components", "universal_components"), ("omics_layers", "omics_layers")):
        stats[f"{key}_bytes"] = int(scalar("SELECT pg_total_relation_size(%s)", (table,)))
    stats["pairs_rows"] = int(scalar("SELECT COUNT(*) FROM universal_pairs WHERE schema_id = %s", (ctx.schema_id,)))
    stats["components_rows"] = int(scalar(
        "SELECT COUNT(*) FROM universal_components WHERE schema_id = %s", (ctx.schema_id,)))
    stats["structures_rows"] = count_structures(ctx)
    return stats


def set_random_count(ctx, count, verbose=True):
    """
    Stellt die Zahl der Zufallsnetzwerke auf count (Netzwerke mit höchstem Index werden gelöscht).
    Gibt {'added': Anzahl, 'insert_s': Sekunden} zurück (insert_s ist None, wenn nichts eingefügt wurde).
    """
    prefix = random_prefix(ctx.tag)
    delete_experiment("starts_with(name, %s) AND NOT starts_with(name, %s)", (RAND_PREFIX, prefix))
    current = int(scalar(
        "SELECT COUNT(*) FROM biological_networks WHERE network_type = %s AND starts_with(name, %s)",
        (EXPERIMENT_TYPE, prefix)))
    result = {"added": 0, "insert_s": None}
    if current > count:
        threshold = f"{prefix}{count - 1:07d}" if count > 0 else prefix
        delete_experiment("starts_with(name, %s) AND name > %s", (prefix, threshold))
    elif current < count:
        started = time.perf_counter()
        for start in range(current, count, INSERT_BATCH):
            stop = min(count, start + INSERT_BATCH)
            insert_networks(ctx, [generate_random_network(ctx, i) for i in range(start, stop)])
            if verbose:
                print(f"  Zufallsnetzwerke {stop}/{count} ({time.perf_counter() - started:.0f} s)", flush=True)
        result = {"added": count - current, "insert_s": time.perf_counter() - started}
    analyze_tables()
    return result


def insert_plants(ctx):
    """Legt die eingebetteten Netzwerke aller Anfragen neu an und trägt die IDs in die Anfragen ein."""
    delete_experiment("starts_with(name, %s)", (PLANT_PREFIX,))
    records, owners = [], []
    for spec in ctx.specs:
        for plant in spec["plants"]:
            records.append({
                "name": f"{PLANT_PREFIX}{ctx.args.seed}_q{spec['index']:03d}_{plant['kind']}_{plant['index']}",
                "organism": "Homo sapiens",
                "description": f"Eingebettet ({plant['kind']}) für Anfrage {spec['index']}",
                "labels": LABELS[:plant["nodes"]], "stack": plant["stack"],
            })
            owners.append((spec, plant))
    ids = insert_networks(ctx, records)
    for network_id, (spec, plant) in zip(ids, owners):
        plant["id"] = network_id
        for mode in MODES:
            if plant["valid"][mode]:
                spec["expected"][mode].append(network_id)
    analyze_tables()


def prepare_population(ctx):
    """Bereitet die Datenbank vor: Schema, Zufallsnetzwerke, eingebettete Netzwerke, Zählung."""
    args = ctx.args
    try:
        if args.rebuild_data:
            removed = delete_experiment("TRUE", ())
            delete_schemas()
            print(f"  {removed} Experiment-Netzwerke gelöscht (--rebuild-data)")
        ctx.schema_id = crud.register_universal_schema(ctx.schema)
        set_random_count(ctx, args.networks)
        insert_plants(ctx)
        return count_structures(ctx)
    except SystemExit:
        raise
    except Exception as error:  # Verbindungs- oder Schemafehler
        raise SystemExit(
            f"Datenbankzugriff fehlgeschlagen: {error}\n"
            "DATABASE_* in der .env prüfen und init-db.sql (Tabellen omics_* und universal_*, entity_register) "
            "einspielen."
        )


def foreign_omics_networks():
    """Multi-Omics-Netzwerke, die nicht zum Experiment gehören (sie sieht nur die Pipeline mo_python/cpp)."""
    return int(scalar(
        "SELECT COUNT(*) FROM omics_networks o JOIN biological_networks b ON b.network_id = o.network_id "
        "WHERE b.network_type <> %s", (EXPERIMENT_TYPE,)))


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
    Stellt die Implementierung für den nächsten Prozess-Pool ein.

    CSUBGRAPH_LIB_PATH wird über die Umgebung gesetzt (leer = Python); Umgebungsvariablen haben
    Vorrang vor der .env und werden von Worker-Prozessen geerbt. Für cpp und mo_python wird
    geprüft, dass wirklich die gewünschte Multi-Omics-Implementierung aufgelöst wurde (kein stiller
    Fallback von cpp auf Python). index und python verwenden nie die native Bibliothek.
    """
    os.environ["CSUBGRAPH_LIB_PATH"] = lib if backend == "cpp" else ""
    backend_config.reload_config()
    subgraph_executor.reset_backend()
    expected = EXPECTED_NAME.get(backend)
    if expected is None:
        return
    actual = subgraph_executor.get_multiomics_backend_name()
    if actual != expected:
        reason = subgraph_executor.get_multiomics_native_error()
        raise SystemExit(
            f"Implementierung '{backend}' angefordert, für Multi-Omics aufgelöst wurde '{actual}'."
            + (f"\nGrund: {reason}" if reason else ""))


def _probe_backend(_):
    """Läuft im Worker-Prozess: welche Multi-Omics-Implementierung wird dort verwendet?"""
    return os.getpid(), subgraph_executor.get_multiomics_backend_name()


def start_pool(workers, backend):
    """Pool neu erzeugen, Worker vorab starten und deren Implementierung prüfen (index braucht keinen Pool)."""
    subgraph_executor.shutdown_executor()
    if backend == "index":
        return []
    executor = subgraph_executor.get_executor(workers)
    seen = set(executor.map(_probe_backend, range(workers * 4)))
    expected = EXPECTED_NAME.get(backend)
    wrong = {name for _, name in seen if expected is not None and name != expected}
    if wrong:
        raise SystemExit(f"Worker verwenden {sorted(wrong)} statt '{expected}'.")
    return sorted(pid for pid, _ in seen)


def prepare_backend(ctx, backend, workers):
    """Implementierung wählen und Pool starten; gibt die Prozess-IDs der Worker zurück."""
    configure_backend(backend, ctx.lib)
    return start_pool(workers, backend)


# ---------------------------------------------------------------------------
# Messung einer Suche
# ---------------------------------------------------------------------------

class CompareTimer:
    """Misst Laden und Vergleichsphase (crud.compare_many_multiomics) einer Multi-Omics-Suche."""

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


class IndexTimer:
    """Misst Laden (bis zum ersten Vergleich) und Vergleichszeit von crud.search_universal."""

    def __init__(self):
        self.start = 0.0
        self.reset()

    def reset(self):
        self.fetch_s = None
        self.compare_s = 0.0
        self.calls = 0

    def wrap(self, function):
        def timed(*args, **kwargs):
            now = time.perf_counter()
            if self.fetch_s is None:
                self.fetch_s = now - self.start
            self.calls += 1
            try:
                return function(*args, **kwargs)
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
    timer, index_timer, failures = CompareTimer(), IndexTimer(), FailureCapture()
    crud_logger = logging.getLogger("backend.crud")
    old_level, old_propagate = crud_logger.level, crud_logger.propagate
    original_many, original_stacks = crud.compare_many_multiomics, crud.compare_stacks
    crud_logger.addHandler(failures)
    crud_logger.setLevel(logging.INFO)
    crud_logger.propagate = False  # Konsole nicht mit Log-Zeilen fluten
    crud.compare_many_multiomics = timer.wrap(original_many)
    crud.compare_stacks = index_timer.wrap(original_stacks)
    try:
        yield timer, index_timer, failures
    finally:
        crud.compare_many_multiomics = original_many
        crud.compare_stacks = original_stacks
        crud_logger.removeHandler(failures)
        crud_logger.setLevel(old_level)
        crud_logger.propagate = old_propagate
        subgraph_executor.shutdown_executor()


class Context:
    """Gemeinsamer Zustand eines Messlaufs."""

    def __init__(self, args, data, lib, json_path, timers, failures, specs, schema):
        self.args, self.data, self.lib, self.json_path = args, data, lib, json_path
        self.timer, self.index_timer = timers
        self.failures, self.specs, self.schema = failures, specs, schema
        self.names = schema_names(args)
        self.tag = population_tag(args)
        self.schema_id = None
        self.chunksize = None
        self.last_save = 0.0

    def set_chunksize(self, value):
        self.chunksize = value
        self.timer.chunksize = value


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


LOAD_STACKS_SQL = """
    SELECT us.network_id, us.layers
    FROM universal_structures us
    WHERE us.schema_id = %s AND us.length >= %s
    ORDER BY us.network_id
"""
MATCH_META_SQL = """
    SELECT network_id, name, network_type, organism, node_count, edge_count
    FROM biological_networks WHERE network_id = ANY(%s)
    ORDER BY node_count ASC, network_id ASC
"""


def pairwise_search(ctx, spec, mode):
    """
    Einzelvergleiche in Python ohne Index: alle gespeicherten Stapel des Schemas mit Länge >= Länge
    der Anfrage laden (Entsprechung des Knotenzahl-Vorfilters der Multi-Omics-Pipeline) und mit
    universal_core.compare_stacks im Prozess-Pool vergleichen. Gibt (IDs, exakte Treffer, Fehler,
    Laden, Vergleichen) zurück.
    """
    start = time.perf_counter()
    with crud.get_db_connection() as conn:
        cursor = crud.get_db_cursor(conn)
        cursor.execute(LOAD_STACKS_SQL, (ctx.schema_id, spec["nodes"]))
        rows = cursor.fetchall()
        ids = [int(row["network_id"]) for row in rows]
        stacks = [universal_core.Stack.of(row["layers"]) for row in rows]
        fetch_s = time.perf_counter() - start

        mark = time.perf_counter()
        outcomes = subgraph_executor.compare_many_universal(
            spec["stack_u"], stacks, mode, list(spec["active"]),
            chunksize=ctx.chunksize or subgraph_executor.DEFAULT_CHUNKSIZE)
        compare_s = time.perf_counter() - mark

        failed = sum(1 for _, error in outcomes if error)
        found = [(network_id, result) for network_id, (result, error) in zip(ids, outcomes)
                 if not error and result in crud.MATCH_RESULTS]
        if found:  # Metadaten der Treffer laden, wie crud.search_universal
            cursor.execute(MATCH_META_SQL, ([network_id for network_id, _ in found],))
            cursor.fetchall()
    exact = sum(1 for _, result in found if result.startswith("equal_"))
    return [network_id for network_id, _ in found], exact, failed, fetch_s, compare_s, len(ids)


def run_search(ctx, spec, mode, backend, keep_ids=True):
    """Eine Suche mit der gewählten Variante ausführen; gibt die Messwerte als dict zurück."""
    timer, index_timer, failures = ctx.timer, ctx.index_timer, ctx.failures
    timer.reset()
    index_timer.reset()
    failures.failed = 0
    start = time.perf_counter()
    timer.start = index_timer.start = start

    if backend == "index":
        matches = crud.search_universal(ctx.schema.name, spec["labels"], spec["relations"], mode,
                                        schema_version=ctx.schema.version)
        total = time.perf_counter() - start
        ids = sorted(int(m.network_id) for m in matches)
        exact = sum(1 for m in matches if m.match_type == "exact")
        fetch_s, compare_s, candidates, failed = (
            index_timer.fetch_s, index_timer.compare_s, index_timer.calls, 0)
    elif backend == "python":
        found, exact, failed, fetch_s, compare_s, candidates = pairwise_search(ctx, spec, mode)
        total = time.perf_counter() - start
        ids = sorted(found)
    else:
        matches = crud.search_multiomics(spec["names"], spec["matrices"], spec["labels"], mode)
        total = time.perf_counter() - start
        # Fremde Multi-Omics-Netzwerke (nicht Teil des Experiments) zählen nicht als Treffer
        own = [m for m in matches if m.network_type == EXPERIMENT_TYPE]
        ids = sorted(int(m.network_id) for m in own)
        exact = sum(1 for m in own if m.match_type == "exact")
        fetch_s, compare_s, candidates, failed = timer.fetch_s, timer.compare_s, timer.candidates, failures.failed

    fetch_s = fetch_s if fetch_s is not None else total
    expected = set(spec["expected"][mode])
    return {
        "query": spec["index"], "kind": spec["kind"], "layers": spec["layers"], "nodes": spec["nodes"],
        "mode": mode, "candidates": candidates or 0, "matches": len(ids), "exact_matches": exact,
        "match_digest": hashlib.sha1(",".join(map(str, ids)).encode()).hexdigest()[:16],
        "match_ids": ids if keep_ids and len(ids) <= 2000 else None,
        "expected_total": len(expected), "expected_found": len(expected & set(ids)),
        "missing_ids": sorted(expected - set(ids))[:20],
        "failed": failed, "total_s": total, "fetch_s": fetch_s, "compare_s": compare_s,
        "build_s": max(0.0, total - fetch_s - compare_s),
    }


def save_json(ctx, final=False, force=False):
    """Schreibt die JSON-Datei atomar (höchstens alle 5 Sekunden, außer force oder final)."""
    now = time.perf_counter()
    if not (final or force) and now - ctx.last_save < 5.0:
        return
    ctx.last_save = now
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


def warm_up(ctx, backend, specs, count, mode="coherent"):
    for i in range(count):
        run_search(ctx, specs[i % len(specs)], mode, backend)  # verworfen (Caches, Pool)


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


def random_subset(rng, count):
    """Zufällige nichtleere Teilmenge der Schichtindizes 0..count-1 (aufsteigend)."""
    size = int(rng.integers(1, count + 1))
    return sorted(int(i) for i in rng.choice(count, size=size, replace=False))


def check_pairs(ctx, rng, native, violations, examples):
    """universal_core gegen multiomics_python (und C++) auf Paaren mit und ohne Schichtauswahl."""
    args = ctx.args
    kinds = ("random", "coherent", "independent", "exact", "reversed")
    by_kind = {k: {"comparisons": 0, "agree_mo": 0, "disagree_mo": 0, "agree_native": 0,
                   "disagree_native": 0, "errors": 0} for k in kinds}
    results = {mode: Counter() for mode in MODES}
    projection = {"checked": 0, "disagree": 0, "monotone_violations": 0}
    progress = Progress(args.correctness_pairs, "Korrektheit")

    for i in range(args.correctness_pairs):
        kind = kinds[i % len(kinds)]
        layers = int(rng.integers(1, min(4, len(ctx.names)) + 1))
        n_a = int(rng.integers(3, 21))
        n_b = int(rng.integers(n_a, 41))
        names = pick_names(rng, layers, ctx.names)
        x, y = make_pair(rng, kind, names, n_a, n_b)
        xl, yl = to_lists(x), to_lists(y)
        sx, sy = universal_core.stack_from_matrices(xl), universal_core.stack_from_matrices(yl)
        xa, ya = np.array(x, dtype=int), np.array(y, dtype=int)

        if universal_core.contained(sx, sy, "coherent") and not universal_core.contained(sx, sy, "independent"):
            violations["coherent_not_independent"] += 1

        for mode in MODES:
            reference = multiomics_python.compare_layered(xl, yl, mode)
            core = universal_core.compare_stacks(sx, sy, mode)
            swapped = universal_core.compare_stacks(sy, sx, mode)
            results[mode][core] += 1
            entry = by_kind[kind]
            entry["comparisons"] += 1
            if core == reference:
                entry["agree_mo"] += 1
            else:
                entry["disagree_mo"] += 1
                violations["core_disagrees_python"] += 1
                if len(examples) < 20:
                    examples.append({"type": "core_vs_python", "kind": kind, "mode": mode, "layers": layers,
                                     "n_a": n_a, "n_b": n_b, "core": core, "python": reference})
            if not is_symmetric(core, swapped):
                violations["symmetry"] += 1

            expected = None
            if kind in ("exact", "reversed") or kind == "coherent" or (kind == "independent" and mode == "independent"):
                expected = EXPECTED_RESULTS["coherent" if kind == "independent" else kind]
            if expected is not None and core not in expected:
                violations["expected_result"] += 1
                if len(examples) < 20:
                    examples.append({"type": "expected", "kind": kind, "mode": mode, "layers": layers,
                                     "n_a": n_a, "n_b": n_b, "core": core})

            if native is not None:
                result, error = native.compare(xa, ya, mode)
                if error:
                    entry["errors"] += 1
                    violations["native_error"] += 1
                elif result == core:
                    entry["agree_native"] += 1
                else:
                    entry["disagree_native"] += 1
                    violations["native_disagree"] += 1
                    if len(examples) < 20:
                        examples.append({"type": "core_vs_native", "kind": kind, "mode": mode,
                                         "layers": layers, "n_a": n_a, "n_b": n_b, "core": core, "cpp": result})

            # Schichtauswahl (Projektion): Kern mit layers=I gegen Referenz auf den gewählten Matrizen
            subset = random_subset(rng, layers)
            projected = universal_core.compare_stacks(sx, sy, mode, subset)
            projected_reference = multiomics_python.compare_layered(
                [xl[index] for index in subset], [yl[index] for index in subset], mode)
            projection["checked"] += 1
            if projected != projected_reference:
                projection["disagree"] += 1
                violations["projection_disagrees"] += 1
                if len(examples) < 20:
                    examples.append({"type": "projection", "kind": kind, "mode": mode, "subset": subset,
                                     "core": projected, "python": projected_reference})
            if universal_core.contained(sx, sy, mode) and not universal_core.contained(sx, sy, mode, subset):
                projection["monotone_violations"] += 1
                violations["projection_monotone"] += 1
        if (i + 1) % max(1, args.correctness_pairs // 10) == 0:
            progress.done = i
            progress.step(f"{i + 1} Paare, Verstöße {dict(violations)}")
    return by_kind, results, projection


def brute_search(database, query, mode, layers, direction):
    """Einzelvergleiche über alle gespeicherten Stapel (Reihenfolge des Einfügens)."""
    if direction == "contains":
        return [key for key, stack in database.items() if universal_core.contained(query, stack, mode, layers)]
    return [key for key, stack in database.items() if universal_core.contained(stack, query, mode, layers)]


def check_index(ctx, rng, violations, examples):
    """PairIndex gegen Einzelvergleiche über alle Stapel: Treffer, Gegenrichtung, Klassifikation, Pflege."""
    args = ctx.args
    layer_count = len(ctx.names)
    database, index = {}, universal_index.PairIndex(layer_count)
    for key in range(args.correctness_db):
        n = int(rng.integers(3, 11))
        stack = universal_core.stack_from_matrices(random_stack(rng, n, ctx.names))
        database[key] = stack
        index.add(key, stack)

    def make_query():
        if rng.random() < 0.5:  # Fenster eines gespeicherten Stapels: mindestens ein Treffer
            base = database[int(rng.integers(0, len(database)))]
            width = int(rng.integers(2, base.length + 1))
            first = int(rng.integers(0, base.length - width + 1))
            return universal_core.Stack(tuple(layer[first:first + width] for layer in base.layers))
        return universal_core.stack_from_matrices(random_stack(rng, int(rng.integers(2, 5)), ctx.names))

    def check_query(query, current, label):
        subset = None if rng.random() < 0.3 else random_subset(rng, layer_count)
        indices = list(range(layer_count)) if subset is None else subset
        found = {}
        for mode in MODES:
            for direction in universal_index.DIRECTIONS:
                got = index.search(query, mode, subset, direction).keys
                expected = brute_search(current, query, mode, subset, direction)
                counts["checks"] += 1
                found[(mode, direction)] = set(got)
                if got != expected:
                    counts["mismatch_search"] += 1
                    violations["index_search"] += 1
                    if len(examples) < 20:
                        examples.append({"type": "index_search", "phase": label, "mode": mode,
                                         "direction": direction, "layers": subset,
                                         "index": len(got), "single": len(expected)})
            # Klassifikation gegen compare_stacks
            expected_classes = {key: universal_core.compare_stacks(query, stack, mode, subset)
                                for key, stack in current.items()}
            expected_classes = {k: v for k, v in expected_classes.items() if v != "KEEP_BOTH"}
            counts["checks"] += 1
            if index.classify(query, mode, subset) != expected_classes:
                counts["mismatch_classify"] += 1
                violations["index_classify"] += 1
                if len(examples) < 20:
                    examples.append({"type": "index_classify", "phase": label, "mode": mode, "layers": subset})
        if not found[("coherent", "contains")] <= found[("independent", "contains")]:
            violations["index_coherent_not_independent"] += 1
        if len(indices) >= 2:  # weniger aktive Schichten => mehr Treffer
            smaller = indices[:-1]
            for mode in MODES:
                counts["checks"] += 1
                if not found[(mode, "contains")] <= set(index.search(query, mode, smaller, "contains").keys):
                    violations["index_projection_monotone"] += 1

    counts = Counter()
    for q in range(args.correctness_queries):
        check_query(make_query(), database, "static")
        counts["queries"] += 1

    # Pflege: einen Teil der Stapel entfernen (Treffer wie Einzelvergleiche über den Rest), dann wieder einfügen
    removed = sorted(rng.choice(len(database), size=max(1, len(database) // 5), replace=False).tolist())
    remaining = {key: stack for key, stack in database.items() if key not in removed}
    for key in removed:
        index.remove(key)
    for q in range(max(10, args.correctness_queries // 5)):
        check_query(make_query(), remaining, "removed")
        counts["queries"] += 1
    for key in removed:
        index.add(key, database[key])
    if len(index) != len(database) or index.entry_count() <= 0:
        violations["index_maintenance"] += 1
    counts["entries"] = index.entry_count()
    return {"database": len(database), "layers": layer_count, "queries": counts["queries"],
            "checks": counts["checks"], "mismatch_search": counts["mismatch_search"],
            "mismatch_classify": counts["mismatch_classify"], "entries": counts["entries"]}


def run_correctness(ctx):
    """universal_core gegen multiomics_python und C++, Invarianten, Index gegen Einzelvergleiche."""
    args = ctx.args
    rng = np.random.default_rng([args.seed, 21])
    native = None
    if "cpp" in args.backends:
        configure_backend("cpp", ctx.lib)
        native = subgraph_executor._get_native_omics()
    violations, examples = Counter(), []
    by_kind, results, projection = check_pairs(ctx, rng, native, violations, examples)
    index_result = check_index(ctx, rng, violations, examples)
    total = lambda field: sum(v[field] for v in by_kind.values())  # noqa: E731
    ctx.data["correctness"] = {
        "pairs": args.correctness_pairs, "native": native is not None,
        "comparisons": total("comparisons"), "agree_mo": total("agree_mo"), "disagree_mo": total("disagree_mo"),
        "agree_native": total("agree_native"), "disagree_native": total("disagree_native"),
        "errors": total("errors"), "by_kind": by_kind, "projection": projection,
        "results": {mode: dict(c) for mode, c in results.items()}, "index": index_result,
        "violations": dict(violations), "examples": examples,
    }
    save_json(ctx, force=True)


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


def prepare_micro(backend, pairs):
    """python vergleicht Stapel des Kerns (Umwandlung vor der Messung), die übrigen Matrixstapel."""
    if backend == "python":
        return [(universal_core.stack_from_matrices(a), universal_core.stack_from_matrices(b)) for a, b in pairs]
    return pairs


def micro_call(backend):
    """Der Aufruf im Worker: Kern (Stapel) oder Multi-Omics-Vergleich (Matrizen)."""
    if backend == "python":
        return subgraph_executor.execute_universal_comparison
    return subgraph_executor.execute_multiomics_comparison


def run_micro(ctx):
    """
    Zeit je Einzelvergleich über subgraph_executor.execute_universal_comparison (Kern) bzw.
    execute_multiomics_comparison (Python oder C++), also der Pfad im Worker ohne Prozess-Pool.
    Der Kern erhält fertige Stapel; bei den Multi-Omics-Aufrufen sind Umwandlung in numpy und
    Validierung Teil der Zeit.
    """
    args = ctx.args
    backends = [b for b in args.backends if b in MICRO_BACKENDS]
    cells = []
    cases = [(layers, n_b, kind) for layers in args.micro_layers for n_b in args.micro_sizes
             for kind in ("random", "embedded")]
    progress = Progress(len(cases) * len(backends), "Mikro")
    for backend in backends:
        configure_backend(backend, ctx.lib)
        call = micro_call(backend)
        for layers, n_b, kind in cases:
            n_a, raw = micro_pairs(args, layers, n_b, kind)
            pairs = prepare_micro(backend, raw)
            call(pairs[0][0], pairs[0][1], "coherent")  # Aufwärmen
            for mode in MODES:
                values, errors, hits = [], 0, 0
                for a, b in pairs:
                    start = time.perf_counter()
                    result, error = call(a, b, mode)
                    values.append((time.perf_counter() - start) * 1000)
                    errors += 1 if error else 0
                    hits += 1 if result in crud.MATCH_RESULTS else 0
                cells.append({"backend": backend, "mode": mode, "kind": kind, "layers": layers,
                              "n_a": n_a, "n_b": n_b, "pairs": len(pairs), "errors": errors,
                              "match_rate": hits / len(pairs), **time_stats(values)})
            progress.step(f"{SHORT[backend]} L={layers} n={n_b} {KIND_DISPLAY[kind]}")

        # Aufrufkosten: trivialer 1x1-Vergleich
        trivial = prepare_micro(backend, [([[[0]]], [[[0]]])])[0]
        values, errors = [], 0
        call(trivial[0], trivial[1], "coherent")
        for _ in range(max(200, args.micro_pairs * 5)):
            start = time.perf_counter()
            _, error = call(trivial[0], trivial[1], "coherent")
            values.append((time.perf_counter() - start) * 1000)
            errors += 1 if error else 0
        cells.append({"backend": backend, "mode": "coherent", "kind": "trivial", "layers": 1, "n_a": 1,
                      "n_b": 1, "pairs": len(values), "errors": errors, "match_rate": None,
                      **time_stats(values)})
        ctx.data["micro"] = cells
        save_json(ctx, force=True)


# ---------------------------------------------------------------------------
# Teilexperiment 3: Indexsuche im Speicher gegen lineare Suche (ohne Datenbank)
# ---------------------------------------------------------------------------

def run_memory(ctx):
    """
    PairIndex gegen lineare Suche mit Einzelvergleichen (universal_core.contained) über N
    gespeicherte Stapel: Aufbauzeit, Zahl der Listeneinträge, Anfragezeit, Trefferlast H.
    Die Datenbank besteht aus den ersten N Zufallsnetzwerken und allen eingebetteten Netzwerken.
    """
    args = ctx.args
    sizes = sorted(set(args.memory_sizes))
    print(f"  Erzeuge {sizes[-1]} Stapel im Speicher ...", flush=True)
    networks = [fast_stack(generate_random_network(ctx, i)["stack"]) for i in range(sizes[-1])]
    plants = [(f"p{spec['index']}_{plant['kind']}{plant['index']}", fast_stack(plant["stack"]))
              for spec in ctx.specs for plant in spec["plants"]]
    queries = pick_evenly(ctx.specs, args.memory_queries)
    build_rows, rows = [], []
    progress = Progress(len(sizes) * len(queries) * len(MODES), "Speicher")

    for size in sizes:
        items = [(i, networks[i]) for i in range(size)] + plants
        index = universal_index.PairIndex(len(ctx.names) + 1)
        start = time.perf_counter()
        for key, stack in items:
            index.add(key, stack)
        build_s = time.perf_counter() - start
        build_rows.append({
            "size": size, "stored": len(items), "build_s": build_s,
            "build_ms_per_structure": build_s / len(items) * 1000, "entries": index.entry_count(),
            "dictionary": int(sum(index.interner_sizes())),
            "entries_per_structure": index.entry_count() / len(items),
        })
        database = dict(items)
        for spec in queries:
            query, active = spec["stack_u"], spec["active"]
            for mode in MODES:
                times = []
                for _ in range(args.memory_reps):
                    start = time.perf_counter()
                    found = index.search(query, mode, active, "contains")
                    times.append((time.perf_counter() - start) * 1000)
                start = time.perf_counter()
                scan = brute_search(database, query, mode, active, "contains")
                scan_ms = (time.perf_counter() - start) * 1000
                rows.append({
                    "size": size, "stored": len(items), "query": spec["index"], "kind": spec["kind"],
                    "layers": spec["layers"], "nodes": spec["nodes"], "mode": mode,
                    "index_ms": statistics.median(times), "scan_ms": scan_ms,
                    "hit_load": found.hit_load, "candidates": found.candidates,
                    "matches": len(found.keys), "equal": found.keys == scan,
                })
                progress.step(f"N={size} q{spec['index']} {MODE_DISPLAY[mode]} Index {rows[-1]['index_ms']:.2f} ms, "
                              f"Einzelvergleiche {scan_ms:.0f} ms")
        ctx.data["memory"] = {"build": build_rows, "queries": rows}
        save_json(ctx, force=True)


# ---------------------------------------------------------------------------
# Teilexperiment 4: Ende-zu-Ende-Suche (Gitter)
# ---------------------------------------------------------------------------

def run_search_grid(ctx):
    """Anfragen x Modi x Varianten x Wiederholungen."""
    args, data = ctx.args, ctx.data
    backends = list(args.backends)
    progress = Progress(args.reps * len(backends) * len(MODES) * len(ctx.specs), "Suche")
    rows = data.setdefault("search", [])
    for rep in range(args.reps):
        queue = [(mode, spec) for mode in MODES for spec in ctx.specs]
        order = np.random.default_rng([args.seed, 31, rep]).permutation(len(queue))
        for backend in rotated(backends, rep):
            pids = prepare_backend(ctx, backend, args.workers)
            data["meta"].setdefault("worker_pids", {})[f"search/{backend}/rep{rep}"] = pids
            warm_up(ctx, backend, ctx.specs, args.warmup)
            for position in order:
                mode, spec = queue[int(position)]
                row = run_search(ctx, spec, mode, backend, keep_ids=(rep == 0))
                row.update(backend=backend, workers=args.workers, rep=rep)
                rows.append(row)
                save_json(ctx)
                progress.step(
                    f"{SHORT[backend]} {MODE_DISPLAY[mode]} q{spec['index']} L={spec['layers']} "
                    f"n={spec['nodes']} Kand.={row['candidates']} Treffer={row['matches']} "
                    f"{row['total_s']:.2f}s")


# ---------------------------------------------------------------------------
# Teilexperimente 5 bis 7: Worker, Chunk-Größe, Datenbankgröße
# ---------------------------------------------------------------------------

def subset_specs(ctx):
    return pick_evenly(ctx.specs, ctx.args.subset_queries)


def measure_subset(ctx, key, specs, backend, progress, **fields):
    """Suchen im Modus 'coherent' für die Teilmenge und Zeilen an data[key] anhängen."""
    rows = ctx.data.setdefault(key, [])
    for spec in specs:
        row = run_search(ctx, spec, "coherent", backend, keep_ids=False)
        row.update(backend=backend, **fields)
        rows.append(row)
        save_json(ctx)
        progress.step(f"{SHORT[backend]} q{spec['index']} {fields} {row['total_s']:.2f}s")


def pool_backends(args):
    return [b for b in args.backends if b in POOL_BACKENDS]


def run_workers(ctx):
    args = ctx.args
    specs, backends = subset_specs(ctx), pool_backends(args)
    if not backends:
        print("  keine Variante mit Prozess-Pool gewählt, übersprungen")
        return
    progress = Progress(args.worker_reps * len(backends) * len(args.worker_scaling) * len(specs), "Worker")
    for rep in range(args.worker_reps):
        for backend in rotated(backends, rep):
            configure_backend(backend, ctx.lib)
            for workers in args.worker_scaling:
                start_pool(workers, backend)
                warm_up(ctx, backend, specs, args.warmup)
                measure_subset(ctx, "workers", specs, backend, progress, workers=workers, rep=rep)


def run_chunksize(ctx):
    args = ctx.args
    specs, backends = subset_specs(ctx), pool_backends(args)
    if not backends:
        print("  keine Variante mit Prozess-Pool gewählt, übersprungen")
        return
    progress = Progress(args.worker_reps * len(backends) * len(args.chunksizes) * len(specs), "Chunk")
    try:
        for rep in range(args.worker_reps):
            for backend in rotated(backends, rep):
                configure_backend(backend, ctx.lib)
                start_pool(args.workers, backend)
                for chunksize in args.chunksizes:
                    ctx.set_chunksize(chunksize)
                    warm_up(ctx, backend, specs, args.warmup)
                    measure_subset(ctx, "chunksize", specs, backend, progress,
                                   workers=args.workers, chunksize=chunksize, rep=rep)
    finally:
        ctx.set_chunksize(None)


def run_dbsize(ctx):
    args = ctx.args
    specs, backends = subset_specs(ctx), list(args.backends)
    sizes = sorted(set(args.db_sizes))
    progress = Progress(len(sizes) * args.worker_reps * len(backends) * len(specs), "DB-Größe")
    storage = ctx.data.setdefault("storage", [])
    for size in sizes:
        print(f"\n=== Datenbank mit {size} Zufallsnetzwerken ===", flush=True)
        change = set_random_count(ctx, size, verbose=False)
        stats = storage_stats(ctx)
        stats.update(random_networks=size, universal_networks=stats["structures_rows"],
                     added=change["added"], insert_s=change["insert_s"],
                     insert_ms_per_network=(change["insert_s"] / change["added"] * 1000
                                            if change["insert_s"] and change["added"] else None))
        storage.append(stats)
        for rep in range(args.worker_reps):
            for backend in rotated(backends, rep):
                prepare_backend(ctx, backend, args.workers)
                warm_up(ctx, backend, specs, args.warmup)
                measure_subset(ctx, "dbsize", specs, backend, progress, workers=args.workers,
                               random_networks=size, universal_networks=stats["structures_rows"], rep=rep)
        save_json(ctx, force=True)
    set_random_count(ctx, args.networks, verbose=False)  # Ausgangszustand wiederherstellen


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
    ref = REFERENCE if REFERENCE in backends else backends[0]
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
            rep_sums = [sum(r["total_s"] for r in group) for group in group_rows(mine, ("rep",)).values()]
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

    # Selektivität: Kandidaten je Variante gegenüber allen Netzwerken des Schemas
    total = meta.get("structures_total") or 0
    prefilter = [{"backend": v["backend"], "layers": v["layers"], "nodes": v["nodes"], "kind": v["kind"],
                  "query": v["query"], "candidates": v["candidates"], "matches": v["matches"],
                  "share": v["candidates"] / total if total else None}
                 for v in sorted((e for e in entries if e["mode"] == modes[0]),
                                 key=lambda x: (x["backend"], x["query"]))]

    return {
        "reference": ref, "summary": summary, "recall": recall,
        "by_layers": aggregate(entries, ("backend", "mode", "kind", "layers")),
        "by_nodes": aggregate(entries, ("backend", "mode", "kind", "nodes")),
        "mode_check": {"checked": checked, "violations": violations},
        "prefilter": prefilter, "failed": sum(r["failed"] for r in rows),
        "queries": sorted({r["query"] for r in rows}),
    }


def analyze_scaling(rows, label):
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
    table = analyze_scaling(rows, "workers")
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
    table = analyze_scaling(rows, "chunksize")
    if not table:
        return None
    for backend in {t["backend"] for t in table}:
        items = [t for t in table if t["backend"] == backend]
        best = min(t["sum_total_s"] for t in items)
        for t in items:
            t["relative_to_best"] = t["sum_total_s"] / best if best > 0 else None
    return table


def analyze_dbsize(rows):
    """Summen je Variante und Datenbankgröße, Speedup gegen die Referenz, Anpassungen und Exponent."""
    table = analyze_scaling(rows, "random_networks")
    if not table:
        return None
    ref = REFERENCE if any(t["backend"] == REFERENCE for t in table) else table[0]["backend"]
    ref_totals = {t["random_networks"]: t["sum_total_s"] for t in table if t["backend"] == ref}
    networks = {r["random_networks"]: r["universal_networks"] for r in rows}
    for t in table:
        t["networks"] = networks.get(t["random_networks"])
        base = ref_totals.get(t["random_networks"])
        t["speedup"] = base / t["sum_total_s"] if base and t["sum_total_s"] > 0 else None
    fits = []
    for backend in sorted({r["backend"] for r in rows}):
        items = sorted((t for t in table if t["backend"] == backend), key=lambda t: t["networks"] or 0)
        xs = [t["networks"] for t in items]
        for field in ("sum_total_s", "sum_compare_s", "sum_fetch_s"):
            ys = [t[field] for t in items]
            slope, intercept, r2 = linear_fit(xs, ys)
            exponent, r2_log = loglog_fit(xs, ys)
            queries = items[0]["queries"] if items else 1
            fits.append({"backend": backend, "field": field,
                         "ms_per_network_and_query": slope * 1000 / queries if slope is not None else None,
                         "intercept_s": intercept, "r2": r2, "exponent": exponent, "r2_log": r2_log})
    return {"table": table, "fits": fits, "reference": ref}


def analyze_storage(storage):
    """Größe des Index in Abhängigkeit von der Zahl der Strukturen (Satz: O(sum_k L |M_k|) Einträge)."""
    if not storage:
        return None
    rows = sorted(storage, key=lambda s: s["universal_networks"])
    xs = [r["universal_networks"] for r in rows]
    pairs = linear_fit(xs, [r["pairs_rows"] for r in rows])
    components = linear_fit(xs, [r["components_rows"] for r in rows])
    return {"rows": rows, "pairs_per_network": pairs[0], "pairs_r2": pairs[2],
            "components_per_network": components[0], "components_r2": components[2]}


def analyze_memory(memory):
    """Indexsuche im Speicher gegen Einzelvergleiche: Tabelle je N, Anpassung an die Trefferlast, Exponenten."""
    if not memory or not memory.get("queries"):
        return None
    rows, build = memory["queries"], memory["build"]
    table = []
    for size in sorted({r["size"] for r in rows}):
        items = [r for r in rows if r["size"] == size]
        index_ms = statistics.fmean(r["index_ms"] for r in items)
        scan_ms = statistics.fmean(r["scan_ms"] for r in items)
        table.append({
            "size": size, "stored": items[0]["stored"], "queries": len(items),
            "index_ms": index_ms, "scan_ms": scan_ms, "speedup": scan_ms / index_ms if index_ms > 0 else None,
            "hit_load": statistics.fmean(r["hit_load"] for r in items),
            "candidates": statistics.fmean(r["candidates"] for r in items),
            "matches": statistics.fmean(r["matches"] for r in items),
            "equal_share": sum(1 for r in items if r["equal"]) / len(items),
        })
    stored = [t["stored"] for t in table]
    independent = [r for r in rows if r["mode"] == "independent"]
    fit_all = linear_fit([r["hit_load"] for r in rows], [r["index_ms"] for r in rows])
    fit_ind = linear_fit([r["hit_load"] for r in independent], [r["index_ms"] for r in independent])
    build_fit = linear_fit([b["stored"] for b in build], [b["build_s"] for b in build])
    return {
        "table": table, "build": build,
        "fit_hit_load": {"ms_per_entry": fit_all[0], "intercept_ms": fit_all[1], "r2": fit_all[2]},
        "fit_hit_load_independent": {"ms_per_entry": fit_ind[0], "intercept_ms": fit_ind[1], "r2": fit_ind[2]},
        "exponent_index": loglog_fit(stored, [t["index_ms"] for t in table]),
        "exponent_scan": loglog_fit(stored, [t["scan_ms"] for t in table]),
        "fit_build": {"s_per_structure": build_fit[0], "intercept_s": build_fit[1], "r2": build_fit[2]},
        "all_equal": all(r["equal"] for r in rows),
    }


def analyze_micro(cells):
    if not cells:
        return None
    index = {(c["backend"], c["mode"], c["kind"], c["layers"], c["n_b"]): c
             for c in cells if c["kind"] != "trivial"}
    speedups = []
    for key, base in index.items():
        if key[0] != REFERENCE:
            continue
        for other in ("mo_python", "cpp"):
            cell = index.get((other,) + key[1:])
            if cell is None or cell["median_ms"] <= 0:
                continue
            speedups.append({"versus": other, "mode": key[1], "kind": key[2], "layers": key[3], "n_b": key[4],
                             "core_median_ms": base["median_ms"], "other_median_ms": cell["median_ms"],
                             "speedup_median": base["median_ms"] / cell["median_ms"],
                             "speedup_mean": base["mean_ms"] / cell["mean_ms"] if cell["mean_ms"] > 0 else None})
    overall = []
    for (versus, mode, kind), items in sorted(group_rows(speedups, ("versus", "mode", "kind")).items()):
        overall.append({"versus": versus, "mode": mode, "kind": kind, "cells": len(items),
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
        "storage": analyze_storage(data.get("storage", [])),
        "micro": analyze_micro(data.get("micro", [])),
        "memory": analyze_memory(data.get("memory")),
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
    return f"{SHORT[backend]}, {MODE_DISPLAY[mode]}"


def draw_total(ax, ctx):
    search = ctx["s"]["search"]
    if not search:
        return no_data(ax, "Gesamtzeit und Speedup")
    summary = search["summary"]
    labels = [label_of(s["backend"], s["mode"]) for s in summary]
    values = [s["sum_s"] / 60 for s in summary]
    errors = [[(s["sum_s"] - (s["sum_s_ci"][0] if s["sum_s_ci"][0] is not None else s["sum_s"])) / 60 for s in summary],
              [((s["sum_s_ci"][1] if s["sum_s_ci"][1] is not None else s["sum_s"]) - s["sum_s"]) / 60 for s in summary]]
    bars = ax.bar(labels, values, color=[COLORS[s["backend"]] for s in summary], yerr=errors, capsize=4)
    for bar, s in zip(bars, summary):
        if s["speedup"] is not None and s["backend"] != search["reference"]:
            ax.annotate(f"{s['speedup']:.2f}x", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        ha="center", va="bottom", fontsize=9)
    ax.set_yscale("log")
    ax.set_ylabel("Gesamtzeit aller Anfragen [min] (log)")
    ax.set_title(f"Gesamtzeit (95-%-KI) und Speedup gegenüber {SHORT[search['reference']]}")
    ax.tick_params(axis="x", labelsize=7, rotation=30)
    ax.grid(alpha=0.3, axis="y", which="both")


def draw_distribution(ax, ctx):
    rows = ctx["data"].get("search", [])
    if not rows:
        return no_data(ax, "Verteilung der Antwortzeiten")
    groups = [(b, m) for m in MODES for b in BACKENDS if any(r["backend"] == b and r["mode"] == m for r in rows)]
    ax.boxplot([[r["total_s"] for r in rows if r["backend"] == b and r["mode"] == m] for b, m in groups],
               showmeans=True)
    ax.set_xticklabels([label_of(b, m) for b, m in groups], fontsize=7, rotation=30)
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
             ("compare_share", "Vergleichen", "#2ca02c"),
             ("build_share", "Rest (Umwandlung, Treffer)", "#ff7f0e")]
    bottom = np.zeros(len(summary))
    for field, name, color in parts:
        values = np.array([(s[field] or 0) * s["sum_s"] / s["queries"] for s in summary])
        ax.bar(labels, values, bottom=bottom, label=name, color=color)
        bottom += values
    ax.set_yscale("log")
    ax.legend(fontsize=8)
    ax.tick_params(axis="x", labelsize=7, rotation=30)
    ax.set_ylabel("Mittlere Zeit pro Anfrage [s] (log)")
    ax.set_title("Zeit je Phase")
    ax.grid(alpha=0.3, axis="y", which="both")


def draw_scaling_candidates(ax, ctx):
    rows = ctx["data"].get("search", [])
    if not rows:
        return no_data(ax, "Zeit gegen Kandidatenzahl")
    for (backend, mode), items in group_rows(per_query_means(rows), ("backend", "mode")).items():
        points = [(v["candidates"], v["total_s"]) for v in items if v["candidates"] > 0 and v["total_s"] > 0]
        if points:
            xs, ys = zip(*points)
            ax.scatter(xs, ys, s=18, alpha=0.7, color=COLORS[backend],
                       marker="o" if mode == "coherent" else "s", label=label_of(backend, mode))
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.legend(fontsize=7)
    ax.set_xlabel("Kandidaten (Index: Listen-Schnitt, sonst nach SQL-Vorauswahl)")
    ax.set_ylabel("Gesamtzeit pro Anfrage [s]")
    ax.set_title("Zeit gegen Kandidatenzahl")
    ax.grid(alpha=0.3, which="both")


def _draw_by(ax, ctx, key, xlabel, title):
    search = ctx["s"]["search"]
    if not search:
        return no_data(ax, title)
    for backend in BACKENDS:
        for mode in MODES:
            items = [a for a in search[f"by_{key}"] if a["backend"] == backend and a["mode"] == mode
                     and a["kind"] == "random"]
            if items:
                ax.plot([a[key] for a in items], [a["mean_total_s"] for a in items],
                        label=label_of(backend, mode), markersize=4, **style(backend, mode))
    ax.set_yscale("log")
    ax.legend(fontsize=7)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Mittlere Gesamtzeit pro Anfrage [s] (log)")
    ax.set_title(title)
    ax.grid(alpha=0.3, which="both")


def draw_layers(ax, ctx):
    _draw_by(ax, ctx, "layers", "Schichten der Anfrage", "Einfluss der Schichtzahl (Zufallsanfragen)")


def draw_nodes(ax, ctx):
    _draw_by(ax, ctx, "nodes", "Knoten der Anfrage", "Einfluss der Knotenzahl (Zufallsanfragen)")


def draw_selectivity(ax, ctx):
    search = ctx["s"]["search"]
    if not search:
        return no_data(ax, "Selektivität")
    for backend in BACKENDS:
        items = [p for p in search["prefilter"] if p["backend"] == backend and p["kind"] == "random"
                 and p["share"] is not None]
        if not items:
            continue
        nodes = sorted({p["nodes"] for p in items})
        shares = [100 * statistics.fmean(p["share"] for p in items if p["nodes"] == n) for n in nodes]
        ax.plot(nodes, [max(s, 1e-4) for s in shares], color=COLORS[backend], marker="o",
                label=f"Kandidaten {SHORT[backend]}")
    reference = [p for p in search["prefilter"] if p["backend"] == search["reference"] and p["kind"] == "random"]
    if reference:
        nodes = sorted({p["nodes"] for p in reference})
        ax2 = ax.twinx()
        ax2.plot(nodes, [max(statistics.fmean(p["matches"] for p in reference if p["nodes"] == n), 0.5)
                         for n in nodes], color="black", linestyle=":", marker=".", label="Treffer (rechts)")
        ax2.set_yscale("log")
        ax2.set_ylabel("Treffer je Zufallsanfrage (log, min. 0,5)")
    ax.set_yscale("log")
    ax.set_xlabel("Knoten der Anfrage")
    ax.set_ylabel("Kandidaten [% aller Netzwerke] (log)")
    ax.legend(fontsize=7)
    ax.set_title("Selektivität: Kandidaten und Treffer")
    ax.grid(alpha=0.3, which="both")


def draw_modes(ax, ctx):
    search = ctx["s"]["search"]
    if not search:
        return no_data(ax, "Modi im Vergleich")
    backends = [b for b in BACKENDS if any(s["backend"] == b for s in search["summary"])]
    width = 0.8 / len(MODES)
    for i, mode in enumerate(MODES):
        values = []
        for backend in backends:
            entry = next((s for s in search["summary"] if s["backend"] == backend and s["mode"] == mode), None)
            values.append(entry["mean_s"] if entry else 0)
        bars = ax.bar(np.arange(len(backends)) + (i - 0.5 * (len(MODES) - 1)) * width, values, width,
                      label=MODE_DISPLAY[mode])
        for bar, value in zip(bars, values):
            ax.annotate(f"{value:.2f}", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        ha="center", va="bottom", fontsize=7)
    ax.set_xticks(np.arange(len(backends)))
    ax.set_xticklabels([SHORT[b] for b in backends])
    ax.set_yscale("log")
    ax.set_ylabel("Mittlere Zeit pro Anfrage [s] (log)")
    ax.set_title("Kohärenter gegen unabhängigen Modus")
    ax.legend()
    ax.grid(alpha=0.3, axis="y", which="both")


def draw_micro_time(ax, ctx):
    cells = [c for c in ctx["data"].get("micro", []) if c["kind"] == "random" and c["mode"] == "coherent"]
    if not cells:
        return no_data(ax, "Mikro: Zeit je Einzelvergleich")
    layers = sorted({c["layers"] for c in cells})
    cmap = ctx["plt"].get_cmap("viridis")
    marker = {"python": "o", "mo_python": "s", "cpp": "^"}
    for index, layer in enumerate(layers):
        for backend in MICRO_BACKENDS:
            items = sorted((c for c in cells if c["backend"] == backend and c["layers"] == layer),
                           key=lambda c: c["n_b"])
            if items:
                ax.plot([c["n_b"] for c in items], [c["median_ms"] for c in items], marker=marker[backend],
                        markersize=3, linestyle="-" if backend == "python" else "--",
                        color=cmap(index / max(1, len(layers) - 1)), label=f"{SHORT[backend]}, L={layer}")
    ax.set_yscale("log")
    ax.legend(fontsize=5, ncol=3)
    ax.set_xlabel("Knoten des Kandidaten n_B")
    ax.set_ylabel("Median je Einzelvergleich [ms] (log)")
    ax.set_title("Mikro: Zeit je Einzelvergleich (Zufallspaare, kohärent)")
    ax.grid(alpha=0.3, which="both")


def _draw_heat(ax, ctx, kind, title):
    micro = ctx["s"]["micro"]
    speedups = micro["speedups"] if micro else []
    versus = "cpp" if any(s["versus"] == "cpp" for s in speedups) else "mo_python"
    items = [s for s in speedups if s["mode"] == "coherent" and s["kind"] == kind and s["versus"] == versus]
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
    ax.figure.colorbar(image, ax=ax, label=f"Speedup (Median) gegenüber Kern, {SHORT[versus]}")
    ax.set_xlabel("Knoten des Kandidaten n_B")
    ax.set_ylabel("Schichten")
    ax.set_title(title)


def draw_micro_heat_random(ax, ctx):
    _draw_heat(ax, ctx, "random", "Mikro: Einzelvergleich gegenüber Kern, Zufallspaare")


def draw_micro_heat_embedded(ax, ctx):
    _draw_heat(ax, ctx, "embedded", "Mikro: Einzelvergleich gegenüber Kern, eingebettet")


def draw_correctness(ax, ctx):
    result = ctx["s"]["correctness"]
    if not result:
        return no_data(ax, "Korrektheit")
    kinds = list(result["by_kind"])
    labels = [PLANT_DISPLAY.get(k, "Zufall") for k in kinds]
    positions = np.arange(len(kinds))
    shares_mo = [100 * v["agree_mo"] / v["comparisons"] if v["comparisons"] else 0 for v in result["by_kind"].values()]
    width = 0.4 if result["native"] else 0.6
    ax.bar(positions - (width / 2 if result["native"] else 0), shares_mo, width, color="#1f77b4",
           label="Kern = multiomics_python")
    if result["native"]:
        shares_native = [100 * v["agree_native"] / v["comparisons"] if v["comparisons"] else 0
                         for v in result["by_kind"].values()]
        ax.bar(positions + width / 2, shares_native, width, color="#d62728", label="Kern = C++")
    ax.set_xticks(positions)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 112)
    ax.set_ylabel("Übereinstimmung [%]")
    violations = sum(result["violations"].values())
    index = result.get("index") or {}
    ax.set_title(f"Korrektheit: {result['agree_mo']}/{result['comparisons']} Vergleiche identisch")
    ax.text(0.5, 0.06, f"Verstöße gegen Invarianten, Erwartung und Index: {violations}\n"
                       f"Index gegen Einzelvergleiche: {index.get('checks', 0)} Prüfungen, "
                       f"Abweichungen {index.get('mismatch_search', 0) + index.get('mismatch_classify', 0)}",
            transform=ax.transAxes, ha="center", fontsize=8, bbox={"facecolor": "white", "alpha": 0.8})
    ax.legend(fontsize=8, loc="lower left")
    ax.grid(alpha=0.3, axis="y")


def draw_memory_time(ax, ctx):
    memory = ctx["s"]["memory"]
    if not memory:
        return no_data(ax, "Indexsuche im Speicher")
    table = memory["table"]
    xs = [t["stored"] for t in table]
    for key, name, color in (("index_ms", "Paarindex", COLORS["index"]), ("scan_ms", "Einzelvergleiche", COLORS["python"])):
        exponent = memory["exponent_index" if key == "index_ms" else "exponent_scan"][0]
        suffix = f", t ~ N^{exponent:.2f}" if exponent is not None else ""
        ax.plot(xs, [t[key] for t in table], marker="o", color=color, label=f"{name}{suffix}")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.legend(fontsize=8)
    ax.set_xlabel("gespeicherte Stapel N")
    ax.set_ylabel("Mittlere Zeit je Anfrage [ms] (log)")
    ax.set_title("Im Speicher: Index gegen Einzelvergleiche")
    ax.grid(alpha=0.3, which="both")


def draw_memory_hits(ax, ctx):
    memory = ctx["s"]["memory"]
    rows = ctx["data"].get("memory", {}).get("queries", [])
    if not memory or not rows:
        return no_data(ax, "Anfragezeit gegen Trefferlast")
    for mode in MODES:
        items = [r for r in rows if r["mode"] == mode and r["hit_load"] > 0]
        if items:
            ax.scatter([r["hit_load"] for r in items], [r["index_ms"] for r in items], s=14, alpha=0.6,
                       marker="o" if mode == "coherent" else "s", label=MODE_DISPLAY[mode])
    fit = memory["fit_hit_load_independent"]
    if fit["ms_per_entry"] is not None:
        top = max(r["hit_load"] for r in rows)
        grid = np.linspace(0, top, 50)
        ax.plot(grid, fit["ms_per_entry"] * grid + fit["intercept_ms"], color="black", linestyle=":",
                label=f"Fit unabhängig: R² = {fit['r2']:.3f}" if fit["r2"] is not None else "Fit unabhängig")
    ax.set_xscale("symlog")
    ax.set_yscale("log")
    ax.legend(fontsize=8)
    ax.set_xlabel("Trefferlast H (gelesene Listeneinträge)")
    ax.set_ylabel("Anfragezeit des Index [ms] (log)")
    ax.set_title("Anfragezeit gegen Trefferlast")
    ax.grid(alpha=0.3, which="both")


def draw_dbsize(ax, ctx):
    result = ctx["s"]["dbsize"]
    if not result:
        return no_data(ax, "Skalierung mit der Datenbankgröße")
    for backend in BACKENDS:
        items = sorted((t for t in result["table"] if t["backend"] == backend), key=lambda t: t["networks"] or 0)
        if not items:
            continue
        fit = next((f for f in result["fits"] if f["backend"] == backend and f["field"] == "sum_total_s"), None)
        suffix = f", t ~ N^{fit['exponent']:.2f}" if fit and fit["exponent"] is not None else ""
        ax.plot([t["networks"] for t in items], [t["sum_total_s"] for t in items], marker="o",
                color=COLORS[backend], label=f"{SHORT[backend]}{suffix}")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.legend(fontsize=8)
    ax.set_xlabel("Netzwerke im Schema")
    ax.set_ylabel("Summe über die Anfragen [s] (log)")
    ax.set_title("Skalierung mit der Datenbankgröße (kohärent)")
    ax.grid(alpha=0.3, which="both")


def draw_storage(ax, ctx):
    storage = ctx["s"]["storage"]
    if not storage:
        return no_data(ax, "Speicherbedarf des Index")
    rows = storage["rows"]
    xs = [r["universal_networks"] for r in rows]
    ax.plot(xs, [r["pairs_rows"] / 1e6 for r in rows], marker="o", color=COLORS["index"], label="Zeilen in universal_pairs [Mio.]")
    ax.plot(xs, [r["components_rows"] / 1e6 for r in rows], marker="s", color="#8c564b", label="Wörterbuch [Mio.]")
    ax.set_xlabel("Netzwerke im Schema")
    ax.set_ylabel("Zeilen [Mio.]")
    inserts = [(r["universal_networks"], r["insert_ms_per_network"]) for r in rows if r["insert_ms_per_network"]]
    if inserts:
        ax2 = ax.twinx()
        ax2.plot(*zip(*inserts), marker="^", linestyle="--", color="gray", label="Einfügen [ms je Netzwerk]")
        ax2.set_ylabel("Einfügezeit [ms je Netzwerk]")
        handles = ax.get_legend_handles_labels()
        handles2 = ax2.get_legend_handles_labels()
        ax.legend(handles[0] + handles2[0], handles[1] + handles2[1], fontsize=7)
    else:
        ax.legend(fontsize=7)
    ax.set_title("Speicherbedarf und Einfügezeit des Index")
    ax.grid(alpha=0.3)


def draw_workers(ax, ctx):
    table = ctx["s"]["workers"]
    if not table:
        return no_data(ax, "Skalierung mit Workern")
    maximum = max(t["workers"] for t in table)
    base = min(t["workers"] for t in table)
    ax.plot([base, maximum], [1, maximum / base], color="gray", linestyle=":", label="ideal")
    for backend in POOL_BACKENDS:
        items = [t for t in table if t["backend"] == backend]
        if items:
            ax.plot([t["workers"] for t in items], [t["speedup_compare"] for t in items], marker="o",
                    color=COLORS[backend], label=f"{SHORT[backend]}, Vergleichsphase")
            ax.plot([t["workers"] for t in items], [t["speedup_total"] for t in items], marker="s",
                    linestyle="--", color=COLORS[backend], label=f"{SHORT[backend]}, gesamt")
    ax.legend(fontsize=7)
    ax.set_xlabel("Worker")
    ax.set_ylabel(f"Speedup gegenüber {base} Worker(n)")
    ax.set_title("Skalierung mit der Worker-Anzahl (Index braucht keinen Pool)")
    ax.grid(alpha=0.3)


def draw_chunksize(ax, ctx):
    table = ctx["s"]["chunksize"]
    if not table:
        return no_data(ax, "Einfluss der Chunk-Größe")
    for backend in POOL_BACKENDS:
        items = sorted((t for t in table if t["backend"] == backend), key=lambda t: t["chunksize"])
        if items:
            ax.plot([t["chunksize"] for t in items], [t["sum_total_s"] for t in items], marker="o",
                    color=COLORS[backend], label=f"{SHORT[backend]}, gesamt")
            ax.plot([t["chunksize"] for t in items], [t["sum_compare_s"] for t in items], marker="s",
                    linestyle="--", color=COLORS[backend], label=f"{SHORT[backend]}, Vergleichsphase")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.legend(fontsize=7)
    ax.set_xlabel("Chunk-Größe (Vergleiche je Task)")
    ax.set_ylabel("Summe über die Anfragen [s]")
    ax.set_title("Einfluss der Chunk-Größe")
    ax.grid(alpha=0.3, which="both")


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
                    ha="center", va="bottom", fontsize=7)
    ax.set_ylim(0, 125)
    ax.tick_params(axis="x", labelsize=7, rotation=30)
    ax.set_ylabel("Gefundene eingebettete Netzwerke [%]")
    ax.set_title("Trefferquote gegen Ground Truth")
    ax.grid(alpha=0.3, axis="y")


DRAWERS = {
    "gesamtzeit_speedup": draw_total, "verteilung_antwortzeiten": draw_distribution,
    "phasen": draw_phases, "skalierung_kandidaten": draw_scaling_candidates,
    "schichten": draw_layers, "knoten": draw_nodes, "selektivitaet": draw_selectivity, "modi": draw_modes,
    "mikro_zeit": draw_micro_time, "mikro_speedup_zufall": draw_micro_heat_random,
    "mikro_speedup_eingebettet": draw_micro_heat_embedded, "korrektheit": draw_correctness,
    "memory_zeit": draw_memory_time, "memory_trefferlast": draw_memory_hits,
    "dbsize": draw_dbsize, "speicher": draw_storage,
    "workers": draw_workers, "chunksize": draw_chunksize, "treffer_erwartet": draw_expected,
}
PAGES = [
    ["gesamtzeit_speedup", "verteilung_antwortzeiten", "phasen", "skalierung_kandidaten"],
    ["schichten", "knoten", "selektivitaet", "modi"],
    ["mikro_zeit", "mikro_speedup_zufall", "mikro_speedup_eingebettet", "korrektheit"],
    ["memory_zeit", "memory_trefferlast", "dbsize", "speicher"],
    ["workers", "chunksize", "treffer_erwartet"],
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
            fig.suptitle(f"Universelle Kodierung: Index gegen Einzelvergleiche, Seite {number}/{len(PAGES)}{status}",
                         fontsize=13)
            for ax, name in zip(axes.flat, page):
                try:
                    DRAWERS[name](ax, ctx)
                except Exception as error:  # noqa: BLE001
                    no_data(ax, name, f"Fehler: {error}")
            for ax in list(axes.flat)[len(page):]:
                ax.axis("off")
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
    lines = ["Experiment Universelle Kodierung: Index gegen Einzelvergleiche", "=" * 70,
             f"Messlauf: {meta.get('created', '?')}, Seed {meta.get('seed', '?')}, "
             f"Plattform {meta.get('platform', '?')}, {meta.get('logical_cpus', '?')} logische CPUs",
             f"Schema: {meta.get('schema', '?')} ({meta.get('schema_layers', '?')} Schichten), "
             f"Strukturen im Schema: {meta.get('structures_total', '?')} "
             f"(Zufallsnetzwerke: {meta.get('random_networks', '?')}), C++-Bibliothek: {meta.get('csubgraph_lib')}",
             f"Wiederholungen: {meta.get('reps', '?')}, Worker: {meta.get('workers', '?')}"]
    if meta.get("foreign_omics_networks"):
        lines.append(f"WARNUNG: {meta['foreign_omics_networks']} fremde Multi-Omics-Netzwerke in der Datenbank "
                     "(nur mo_python und cpp sehen sie; Zeiten dieser Varianten sind dadurch höher).")
    lines.append("")

    correctness = summary.get("correctness")
    if correctness:
        lines += ["--- Korrektheit ---",
                  f"Paare {correctness['pairs']}, Vergleiche {correctness['comparisons']}, "
                  f"Kern = multiomics_python: {correctness['agree_mo']} identisch, {correctness['disagree_mo']} abweichend; "
                  f"C++ geprüft: {'ja' if correctness['native'] else 'nein'}, identisch {correctness['agree_native']}, "
                  f"abweichend {correctness['disagree_native']}, Fehler {correctness['errors']}",
                  f"Schichtauswahl: {correctness['projection']['checked']} Prüfungen, "
                  f"abweichend {correctness['projection']['disagree']}, "
                  f"Monotonie verletzt {correctness['projection']['monotone_violations']}",
                  f"Verstöße: {correctness['violations'] or 'keine'}"]
        for kind, v in correctness["by_kind"].items():
            lines.append(f"  {PLANT_DISPLAY.get(kind, 'Zufall'):<12} Vergleiche {v['comparisons']:>6} "
                         f"= Python {v['agree_mo']:>6} (abw. {v['disagree_mo']:>4}) "
                         f"= C++ {v['agree_native']:>6} (abw. {v['disagree_native']:>4}) Fehler {v['errors']:>4}")
        index = correctness.get("index")
        if index:
            lines.append(f"  PairIndex: {index['database']} Stapel, {index['queries']} Anfragen, {index['checks']} Prüfungen, "
                         f"abweichende Suchergebnisse {index['mismatch_search']}, Klassifikationen {index['mismatch_classify']}, "
                         f"Listeneinträge {index['entries']}")
        for example in correctness["examples"][:5]:
            lines.append(f"  Beispiel: {example}")
        lines.append("")

    micro = summary.get("micro")
    if micro:
        lines.append("--- Mikro-Benchmark (Median je Einzelvergleich; Speedup = Zeit Kern / Zeit Variante) ---")
        for o in micro["overall"]:
            lines.append(f"  {SHORT[o['versus']]:<9} {MODE_DISPLAY[o['mode']]:<11} {KIND_DISPLAY.get(o['kind'], o['kind']):<12} "
                         f"Zellen {o['cells']:>3} Speedup geom. {_txt(o['speedup_geomean'])} "
                         f"(min {_txt(o['speedup_min'])}, max {_txt(o['speedup_max'])})")
        for c in micro["overhead"]:
            lines.append(f"  Aufrufkosten {SHORT[c['backend']]} (trivial 1x1): Median {_txt(c['median_ms'], 4)} ms, "
                         f"Mittel {_txt(c['mean_ms'], 4)} ms")
        lines.append("")

    memory = summary.get("memory")
    if memory:
        lines.append("--- Indexsuche im Speicher ---")
        for t in memory["table"]:
            lines.append(f"  N={t['stored']:>6}: Index {_txt(t['index_ms'], 3)} ms, Einzelvergleiche {_txt(t['scan_ms'], 1)} ms, "
                         f"Speedup {_txt(t['speedup'], 1)}, Trefferlast {_txt(t['hit_load'], 1)}, "
                         f"Kandidaten {_txt(t['candidates'], 1)}, Treffer {_txt(t['matches'], 1)}, "
                         f"Ergebnisse gleich {_txt(100 * t['equal_share'], 0)} %")
        lines.append(f"  Exponent t ~ N^b: Index {_txt(memory['exponent_index'][0], 2)} "
                     f"(R^2 {_txt(memory['exponent_index'][1], 3)}), Einzelvergleiche {_txt(memory['exponent_scan'][0], 2)} "
                     f"(R^2 {_txt(memory['exponent_scan'][1], 3)})")
        for key, name in (("fit_hit_load", "alle Modi"), ("fit_hit_load_independent", "unabhängig")):
            f = memory[key]
            lines.append(f"  Anfragezeit gegen Trefferlast ({name}): {_txt(f['ms_per_entry'], 6)} ms je Eintrag, "
                         f"Achsenabschnitt {_txt(f['intercept_ms'], 3)} ms, R^2 {_txt(f['r2'], 3)}")
        b = memory["fit_build"]
        lines.append(f"  Aufbau: {_txt((b['s_per_structure'] or 0) * 1000, 3)} ms je Stapel, R^2 {_txt(b['r2'], 3)}; "
                     f"alle Ergebnisse gleich: {'ja' if memory['all_equal'] else 'NEIN'}")
        lines.append("")

    search = summary.get("search")
    if search:
        lines += ["--- Suche (Ende-zu-Ende) ---",
                  f"{'Impl.':>9} {'Modus':>11} {'Summe[s]':>9} {'Mittel[s]':>9} {'Median':>8} {'p95':>8} "
                  f"{'Speedup':>8} {'geom.':>14} {'ms/Kand.':>9} {'Laden%':>7} {'Vergl.%':>8} {'Rest%':>7} "
                  f"{'Fehler':>6} {'Treffer=':>8}"]
        for s in search["summary"]:
            ci = s["speedup_geomean_ci"]
            geo = (f"{_txt(s['speedup_geomean'])} [{_txt(ci[0])},{_txt(ci[1])}]"
                   if ci[0] is not None else _txt(s["speedup_geomean"]))
            lines.append(
                f"{SHORT[s['backend']]:>9} {MODE_DISPLAY[s['mode']]:>11} {s['sum_s']:>9.1f} {s['mean_s']:>9.2f} "
                f"{s['median_s']:>8.2f} {s['p95_s']:>8.2f} {_txt(s['speedup'], 2, 8)} {geo:>14} "
                f"{_txt(s['ms_per_candidate'], 4, 9)} {_txt((s['fetch_share'] or 0) * 100, 0, 7)} "
                f"{_txt((s['compare_share'] or 0) * 100, 0, 8)} {_txt((s['build_share'] or 0) * 100, 0, 7)} "
                f"{s['failed']:>6} {'ja' if s['matches_equal'] else 'NEIN':>8}")
        lines += [f"Speedup = Gesamtzeit {SHORT[search['reference']]} / Gesamtzeit der Zeile; geom. = geometrischer "
                  "Mittelwert der Speedups je Anfrage mit 95-%-Bootstrap-Intervall; Treffer= : Treffer-IDs "
                  "stimmen mit der Referenz überein.",
                  f"Kohärent => unabhängig geprüft an {search['mode_check']['checked']} Messungen, Verstöße: "
                  f"{search['mode_check']['violations']}. Fehlgeschlagene Vergleiche insgesamt: {search['failed']}.",
                  "", "Trefferquote eingebetteter Netzwerke (Ground Truth):"]
        for r in search["recall"]:
            if r["expected"]:
                lines.append(f"  {label_of(r['backend'], r['mode']):<22} {r['found']}/{r['expected']} "
                             f"({_txt(100 * r['recall'], 1)} %), weitere Treffer {r['other_matches']}")
        lines.append("")

    workers = summary.get("workers")
    if workers:
        lines.append("--- Worker-Skalierung ---")
        for t in workers:
            lines.append(f"  {SHORT[t['backend']]:>9} {t['workers']:>2} Worker: gesamt {t['sum_total_s']:>8.1f} s "
                         f"(Speedup {_txt(t['speedup_total'])}), Vergleichen {t['sum_compare_s']:>8.1f} s "
                         f"(Speedup {_txt(t['speedup_compare'])}, Effizienz {_txt(t['efficiency_compare'])}), "
                         f"serieller Anteil (Amdahl) {_txt((t['amdahl'].get('total') or 0) * 100, 1)} %")
        lines.append("")

    chunk = summary.get("chunksize")
    if chunk:
        lines.append("--- Chunk-Größe ---")
        for t in chunk:
            lines.append(f"  {SHORT[t['backend']]:>9} Chunk {t['chunksize']:>5}: gesamt {t['sum_total_s']:>8.1f} s, "
                         f"Vergleichen {t['sum_compare_s']:>8.1f} s, relativ zum Besten {_txt(t['relative_to_best'])}")
        lines.append("")

    dbsize = summary.get("dbsize")
    if dbsize:
        lines.append("--- Datenbankgröße ---")
        for t in dbsize["table"]:
            lines.append(f"  {SHORT[t['backend']]:>9} {t['networks']} Netzwerke: gesamt {t['sum_total_s']:>8.1f} s, "
                         f"Laden {t['sum_fetch_s']:>8.1f} s, Vergleichen {t['sum_compare_s']:>8.1f} s, "
                         f"Kandidaten {t['candidates']}, Speedup {_txt(t['speedup'])}")
        for f in dbsize["fits"]:
            lines.append(f"  Fit {SHORT[f['backend']]:>9} {f['field']}: {_txt(f['ms_per_network_and_query'], 5)} ms je Netzwerk "
                         f"und Anfrage, Achsenabschnitt {_txt(f['intercept_s'], 2)} s, R^2 {_txt(f['r2'], 3)}, "
                         f"Exponent b {_txt(f['exponent'], 2)} (R^2 {_txt(f['r2_log'], 3)})")
        lines.append("")

    storage = summary.get("storage")
    if storage:
        lines.append("--- Speicherbedarf und Einfügen des Index ---")
        for r in storage["rows"]:
            lines.append(f"  {r['universal_networks']:>7} Netzwerke: universal_pairs {r['pairs_rows']:>9} Zeilen "
                         f"({_txt(r['pairs_bytes'] / 2**20, 1)} MiB), Wörterbuch {r['components_rows']:>8} Zeilen "
                         f"({_txt(r['components_bytes'] / 2**20, 1)} MiB), Einfügen {_txt(r['insert_ms_per_network'], 2)} ms je Netzwerk")
        lines.append(f"  Paare je Netzwerk (Anstieg): {_txt(storage['pairs_per_network'], 1)}, R^2 {_txt(storage['pairs_r2'], 3)}; "
                     f"Wörterbuch je Netzwerk: {_txt(storage['components_per_network'], 1)}, R^2 {_txt(storage['components_r2'], 3)}")
        lines.append("  Tabellengrößen umfassen die ganze Tabelle inklusive Indizes; das Wörterbuch enthält nach "
                     "dem Verkleinern auch nicht mehr verwendete Einträge.")
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
    lines = ["% Automatisch erzeugt von src/experiment_search_universal.py -- nicht von Hand ändern.",
             f"% Messlauf: {meta.get('created', '?')}, Seed {meta.get('seed', '?')}", ""]

    search = summary.get("search")
    if search:
        rows = []
        for s in search["summary"]:
            rows.append([SHORT[s["backend"]], MODE_DISPLAY[s["mode"]], _num(s["sum_s"], 1), _num(s["mean_s"], 2),
                         _num(s["median_s"], 2), _num(s["speedup"], 2), _num(s["speedup_geomean"], 2),
                         _num(s["ms_per_candidate"], 4), _num((s["fetch_share"] or 0) * 100, 0),
                         "ja" if s["matches_equal"] else "nein"])
        lines += _table(
            f"Kennzahlen der Suche mit Indexsuche und Einzelvergleichen ({search['summary'][0]['queries']} Anfragen je Zeile, "
            f"Speedup relativ zu {SHORT[search['reference']]}).",
            "tab:uc_summary", "llrrrrrrrl",
            ["Variante", "Modus", "$T$ [s]", "Mittel [s]", "Median [s]", "$S$", "$\\bar S_{\\mathrm{geo}}$",
             "$\\kappa$ [ms]", "Laden [\\%]", "Treffer gleich"], rows)
        recall_rows = [[SHORT[r["backend"]], MODE_DISPLAY[r["mode"]], r["found"], r["expected"],
                        _num(100 * r["recall"], 1), r["other_matches"]]
                       for r in search["recall"] if r["expected"] and r["kind"] == "embedded"]
        if recall_rows:
            lines += _table("Trefferquote der eingebetteten Netzwerke (Ground Truth) und weitere Treffer.",
                            "tab:uc_recall", "llrrrr",
                            ["Variante", "Modus", "gefunden", "erwartet", "Quote [\\%]", "weitere"], recall_rows)

    micro = summary.get("micro")
    if micro:
        rows = [[SHORT[o["versus"]], MODE_DISPLAY[o["mode"]], KIND_DISPLAY.get(o["kind"], o["kind"]), o["cells"],
                 _num(o["speedup_geomean"], 1), _num(o["speedup_min"], 1), _num(o["speedup_max"], 1)]
                for o in micro["overall"]]
        lines += _table("Mikro-Benchmark: Zeit des Kerns (Python) geteilt durch die Zeit der Variante je Einzelvergleich "
                        "(Median, geometrisches Mittel über Zellen).", "tab:uc_micro", "lllrrrr",
                        ["Variante", "Modus", "Paare", "Zellen", "geom.", "min.", "max."], rows)
        rows = [[SHORT[c["backend"]], _num(c["median_ms"], 4), _num(c["mean_ms"], 4), _num(c["max_ms"], 4)]
                for c in micro["overhead"]]
        if rows:
            lines += _table("Aufrufkosten: trivialer $1\\times1$-Vergleich.", "tab:uc_overhead", "lrrr",
                            ["Variante", "Median [ms]", "Mittel [ms]", "Max. [ms]"], rows)

    memory = summary.get("memory")
    if memory:
        rows = [[t["stored"], _num(t["index_ms"], 3), _num(t["scan_ms"], 1), _num(t["speedup"], 1),
                 _num(t["hit_load"], 1), _num(t["candidates"], 1), _num(t["matches"], 1)] for t in memory["table"]]
        lines += _table("Indexsuche im Speicher gegen Einzelvergleiche in Abhängigkeit von der Zahl $N$ gespeicherter Stapel "
                        "(Mittel über Anfragen und Modi, $H$ Trefferlast).", "tab:uc_memory", "rrrrrrr",
                        ["$N$", "Index [ms]", "Einzeln [ms]", "$S$", "$H$", "Kandidaten", "Treffer"], rows)

    workers = summary.get("workers")
    if workers:
        rows = [[SHORT[t["backend"]], t["workers"], _num(t["sum_total_s"], 1), _num(t["speedup_total"], 2),
                 _num(t["sum_compare_s"], 1), _num(t["speedup_compare"], 2), _num(t["efficiency_compare"], 2)]
                for t in workers]
        lines += _table("Skalierung mit der Worker-Anzahl (Modus kohärent).", "tab:uc_workers", "lrrrrrr",
                        ["Variante", "$p$", "$T$ [s]", "$S$", "$T_{\\mathrm{cmp}}$ [s]", "$S_{\\mathrm{cmp}}$",
                         "$E_{\\mathrm{cmp}}$"], rows)

    chunk = summary.get("chunksize")
    if chunk:
        rows = [[SHORT[t["backend"]], t["chunksize"], _num(t["sum_total_s"], 1), _num(t["sum_compare_s"], 1),
                 _num(t["relative_to_best"], 2)] for t in chunk]
        lines += _table("Einfluss der Chunk-Größe (Modus kohärent).", "tab:uc_chunksize", "lrrrr",
                        ["Variante", "Chunk", "$T$ [s]", "$T_{\\mathrm{cmp}}$ [s]", "relativ"], rows)

    dbsize = summary.get("dbsize")
    if dbsize:
        rows = [[SHORT[t["backend"]], t["networks"], t["candidates"], _num(t["sum_total_s"], 1),
                 _num(t["sum_fetch_s"], 1), _num(t["sum_compare_s"], 1), _num(t["speedup"], 2)]
                for t in dbsize["table"]]
        lines += _table("Skalierung mit der Datenbankgröße (Modus kohärent).", "tab:uc_dbsize", "lrrrrrr",
                        ["Variante", "Netzwerke", "Kandidaten", "$T$ [s]", "Laden [s]", "$T_{\\mathrm{cmp}}$ [s]", "$S$"], rows)
        rows = [[SHORT[f["backend"]], _num(f["exponent"], 2), _num(f["r2_log"], 3),
                 _num(f["ms_per_network_and_query"], 5), _num(f["r2"], 3)]
                for f in dbsize["fits"] if f["field"] == "sum_total_s"]
        lines += _table("Anpassung der Gesamtzeit an die Datenbankgröße: Exponent $b$ in $t\\sim N^b$ und lineare Steigung.",
                        "tab:uc_dbfit", "lrrrr",
                        ["Variante", "$b$", "$R^2$ (log)", "ms je Netzwerk und Anfrage", "$R^2$ (linear)"], rows)

    storage = summary.get("storage")
    if storage:
        rows = [[r["universal_networks"], r["pairs_rows"], _num(r["pairs_bytes"] / 2 ** 20, 1), r["components_rows"],
                 _num(r["insert_ms_per_network"], 2)] for r in storage["rows"]]
        lines += _table("Speicherbedarf des Paarindex und Einfügezeit je Netzwerk.", "tab:uc_storage", "rrrrr",
                        ["Netzwerke", "Paarzeilen", "Paartabelle [MiB]", "Wörterbuch", "Einfügen [ms]"], rows)

    correctness = summary.get("correctness")
    if correctness:
        rows = [[PLANT_DISPLAY.get(k, "Zufall"), v["comparisons"], v["agree_mo"], v["disagree_mo"],
                 v["agree_native"], v["disagree_native"]] for k, v in correctness["by_kind"].items()]
        lines += _table("Korrektheit: Kern gegen multiomics\\_python und C++ je Paartyp.", "tab:uc_correctness", "lrrrrr",
                        ["Paartyp", "Vergleiche", "= Python", "abw.", "= C++", "abw."], rows)
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
    "correctness_pairs": 300, "correctness_db": 80, "correctness_queries": 60,
    "micro_pairs": 20, "micro_layers": [1, 3], "micro_sizes": [8, 24],
    "memory_sizes": [250, 1000], "memory_queries": 4, "memory_reps": 3,
    "worker_scaling": [1, 2], "worker_reps": 1, "chunksizes": [16, 256], "subset_queries": 3,
    "max_nodes": 30,
}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add = parser.add_argument
    add("--only", nargs="+", choices=PHASES, default=list(PHASES), help="nur diese Teilexperimente ausführen")
    add("--backends", nargs="+", choices=BACKENDS, default=list(BACKENDS), help="Varianten")
    add("--csubgraph-lib-path", default=None,
        help="Pfad zu libsubgraphlib.a (Datei oder Ordner); Standard: CSUBGRAPH_LIB_PATH aus .env")
    add("--workers", type=int, default=2, help="Worker für Suche, Chunk-Größe und Datenbankgröße (Standard 2)")
    add("--worker-scaling", type=int, nargs="+", default=[1, 2, 3, 4], help="Worker-Anzahlen für 'workers'")
    add("--reps", type=int, default=3, help="Wiederholungen der Suchen (Standard 3)")
    add("--worker-reps", type=int, default=2, help="Wiederholungen für workers/chunksize/dbsize (Standard 2)")
    add("--warmup", type=int, default=1, help="Verworfene Aufwärm-Suchen je Messreihe")
    add("--seed", type=int, default=42)
    add("--schema-layers", type=int, default=5,
        help=f"Schichten des Schemas (die ersten aus {', '.join(POOL_NAMES)}; Standard 5)")
    add("--networks", type=int, default=20000, help="Zufallsnetzwerke in der Datenbank (Standard 20000)")
    add("--min-nodes", type=int, default=4, help="Mindestknotenzahl der Zufallsnetzwerke")
    add("--max-nodes", type=int, default=40, help="Höchstknotenzahl der Zufallsnetzwerke (höchstens 63)")
    add("--query-sizes", type=int, nargs="+", default=[4, 6, 8, 12, 16, 24, 32], help="Knotenzahlen der Anfragen")
    add("--query-layers", type=int, nargs="+", default=[1, 2, 3, 4], help="Schichtzahlen der Anfragen")
    add("--plants", type=int, default=3, help="eingebettete Netzwerke je Art (kohärent/unabhängig) und Anfrage")
    add("--plant-extra-nodes", type=int, default=12,
        help="höchstens so viele zusätzliche Knoten bei eingebetteten Netzwerken")
    add("--correctness-pairs", type=int, default=5000, help="Paare der Korrektheitsprüfung (0 = überspringen)")
    add("--correctness-db", type=int, default=150, help="gespeicherte Stapel der Indexprüfung im Speicher")
    add("--correctness-queries", type=int, default=200, help="Anfragen der Indexprüfung im Speicher")
    add("--micro-pairs", type=int, default=100, help="Paare je Zelle im Mikro-Benchmark")
    add("--micro-layers", type=int, nargs="+", default=[1, 2, 3, 4, 6, 8], help="Schichtzahlen im Mikro-Benchmark")
    add("--micro-sizes", type=int, nargs="+", default=[8, 16, 24, 32, 48, 63], help="n_B im Mikro-Benchmark")
    add("--memory-sizes", type=int, nargs="+", default=[250, 500, 1000, 2000, 5000],
        help="Zahl gespeicherter Stapel N im Speicherexperiment")
    add("--memory-queries", type=int, default=8, help="Anfragen im Speicherexperiment (gleichmäßig ausgewählt)")
    add("--memory-reps", type=int, default=5, help="Wiederholungen der Indexabfrage im Speicherexperiment")
    add("--chunksizes", type=int, nargs="+", default=[1, 8, 32, 128, 256, 1024, 4096], help="Chunk-Größen")
    add("--db-sizes", type=int, nargs="+", default=None,
        help="Zufallsnetzwerke je Stufe für 'dbsize' (Standard: 10, 25, 50, 100 %% von --networks)")
    add("--subset-queries", type=int, default=6, help="Anfragen für workers/chunksize/dbsize (Standard 6)")
    add("--results-dir", default=str(DEFAULT_RESULTS_DIR), help="Zielverzeichnis (Standard: src/results)")
    add("--plot-from", metavar="JSON", help="Nur PDF, Diagramme, Tabellen und Bericht aus einer JSON-Datei erzeugen")
    add("--rebuild-data", action="store_true", help="Experiment-Netzwerke vorab löschen und neu erzeugen")
    add("--cleanup", action="store_true", help="Experiment-Netzwerke und -Schemata am Ende löschen")
    add("--cleanup-only", action="store_true", help="Nur die Experiment-Netzwerke und -Schemata löschen und beenden")
    add("--quick", action="store_true", help="Kleiner Vorabtest (wenige Anfragen, kleine Datenbank)")
    return parser


def validate_args(parser, args):
    if args.min_nodes < 4 or args.max_nodes > MAX_NODES or args.max_nodes < args.min_nodes:
        parser.error(f"--min-nodes >= 4, --max-nodes <= {MAX_NODES} und min <= max erforderlich")
    if not 1 <= args.schema_layers <= len(POOL_NAMES):
        parser.error(f"--schema-layers zwischen 1 und {len(POOL_NAMES)}")
    if any(n < 4 or n + args.plant_extra_nodes > MAX_NODES for n in args.query_sizes):
        parser.error(f"--query-sizes: Werte >= 4 und (Wert + --plant-extra-nodes) <= {MAX_NODES}")
    if any(not 1 <= layers <= args.schema_layers for layers in args.query_layers):
        parser.error("--query-layers: Werte zwischen 1 und --schema-layers")
    if any(not 1 <= n <= MAX_NODES for n in args.micro_sizes) or any(l < 1 for l in args.micro_layers):
        parser.error(f"--micro-sizes zwischen 1 und {MAX_NODES}, --micro-layers >= 1")
    if len(set(args.backends)) != len(args.backends):
        parser.error("--backends enthält eine Variante doppelt")
    if args.reps < 1 or args.worker_reps < 1 or args.networks < 0 or args.memory_reps < 1:
        parser.error("--reps, --worker-reps, --memory-reps >= 1 und --networks >= 0")
    if args.correctness_db < 10 or args.memory_queries < 1 or any(n < 1 for n in args.memory_sizes):
        parser.error("--correctness-db >= 10, --memory-queries >= 1 und --memory-sizes >= 1 erforderlich")
    if args.db_sizes is None:
        args.db_sizes = sorted({max(1, int(args.networks * f)) for f in (0.1, 0.25, 0.5, 1.0)})


def main():
    parser = build_parser()
    args = parser.parse_args()
    results_dir = Path(args.results_dir)

    if args.plot_from:
        stem = Path(args.plot_from).stem
        written, _ = write_outputs(args.plot_from, results_dir / f"{stem}.pdf", results_dir)
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
        print(f"{delete_schemas()} Experiment-Schemata gelöscht.")
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
            "oder --backends ohne cpp wählen. Ein stiller Fallback auf Python würde den Vergleich verfälschen.")
    if "cpp" in args.backends:
        configure_backend("cpp", lib)  # bricht mit Grund ab, wenn die Bibliothek MultiOmics nicht enthält

    schema = make_schema(args)
    sanity_check_encoding(args, schema)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = results_dir / f"search_universal_{stamp}.json"
    pdf_path = results_dir / f"search_universal_{stamp}.pdf"

    specs = build_query_specs(args, schema)
    print(f"Experiment Universelle Kodierung: Teilexperimente {phases}, Varianten {args.backends}, "
          f"{len(specs)} Anfragen, Schema {schema.name} ({schema.layer_count} Schichten), "
          f"Wiederholungen {args.reps}, Worker {args.workers}, Seed {args.seed}")
    if lib:
        print(f"csubgraph: {lib}")

    meta = {
        "created": datetime.now().isoformat(timespec="seconds"), "seed": args.seed, "phases": phases,
        "backends": args.backends, "workers": args.workers, "worker_scaling": args.worker_scaling,
        "reps": args.reps, "worker_reps": args.worker_reps, "warmup": args.warmup,
        "schema": schema.name, "schema_layers": args.schema_layers, "layer_names": schema_names(args),
        "stack_layers": schema.layer_count, "random_networks": args.networks,
        "node_range": [args.min_nodes, args.max_nodes], "query_sizes": args.query_sizes,
        "query_layers": args.query_layers, "plants_per_kind": args.plants, "chunksizes": args.chunksizes,
        "db_sizes": args.db_sizes, "memory_sizes": args.memory_sizes,
        "default_chunksize": subgraph_executor.DEFAULT_CHUNKSIZE, "csubgraph_lib": lib,
        "csubgraph_lib_sha256": hashlib.sha256(Path(lib).read_bytes()).hexdigest() if lib else None,
        "logical_cpus": os.cpu_count(), "python": platform.python_version(), "numpy": np.__version__,
        "platform": platform.platform(), "arguments": vars(args), "complete": False,
    }
    data = {"meta": meta}

    with instrumented() as (timer, index_timer, failures):
        ctx = Context(args, data, lib, json_path, (timer, index_timer), failures, specs, schema)
        try:
            if needs_db:
                print("\nDatenbank vorbereiten ...", flush=True)
                meta["structures_total"] = prepare_population(ctx)
                meta["postgres"] = scalar("SELECT version()")
                meta["foreign_omics_networks"] = foreign_omics_networks()
                data["queries"] = [public_spec(s) for s in specs]
                print(f"  {meta['structures_total']} Strukturen im Schema {schema.name}", flush=True)
                if meta["foreign_omics_networks"]:
                    print(f"  WARNUNG: {meta['foreign_omics_networks']} fremde Multi-Omics-Netzwerke; sie verlangsamen "
                          "mo_python und cpp (z. B. python src/experiment_search_multiomics.py --cleanup-only).")
            save_json(ctx, force=True)

            runners = {"correctness": run_correctness, "micro": run_micro, "memory": run_memory,
                       "search": run_search_grid, "workers": run_workers, "chunksize": run_chunksize,
                       "dbsize": run_dbsize}
            for phase in phases:
                print(f"\n=== Teilexperiment: {phase} ===", flush=True)
                started = time.perf_counter()
                runners[phase](ctx)
                meta.setdefault("phase_seconds", {})[phase] = time.perf_counter() - started
                if phase == "dbsize":
                    meta["structures_total"] = count_structures(ctx)
                save_json(ctx, force=True)
        finally:
            save_json(ctx, force=True)
        save_json(ctx, final=True)

    print(f"\nJSON: {json_path}")
    written, summary = write_outputs(json_path, pdf_path, results_dir)
    for path in written:
        print(f"geschrieben: {path}")
    print()
    print(format_report(data, summary))

    if args.cleanup and needs_db:
        print(f"{delete_experiment('TRUE', ())} Experiment-Netzwerke gelöscht (--cleanup).")
        print(f"{delete_schemas()} Experiment-Schemata gelöscht (--cleanup).")
        analyze_tables()


if __name__ == "__main__":
    main()
