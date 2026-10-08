# gen-db

Biological Network Database mit PostgreSQL-Backend, FastAPI-REST-API und Web-Frontend zur Analyse biologischer Netzwerke mittels Subgraph Algorithmus.

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/Tests-309%20passed-4c1)](tests/)
[![Test Coverage](https://img.shields.io/badge/Test%20Coverage-95%25-brightgreen)](doc/coverage/index.html)
[![scicov](https://img.shields.io/badge/scicov-10-ff69b4)](doc/coverage/index.html)

## Inhaltsverzeichnis

- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Abhängigkeiten](#abhängigkeiten)
- [SQL-Struktur](#sql-strutkur)
- [1.000.000 Netzwerke](#1000000-netzwerke)
- [Starten](#starten)
- [Suchen](#suchen)
- [Testen](#testen)
- [Erwerb](#erwerb)

## Voraussetzungen

Damit das Projekt lokal korrekt gestartet werden kann, werden eine aktuelle Python-Version und eine PostgreSQL-Instanz benötigt.

- Python 3.12
- PostgreSQL (lokal, portable von https://www.enterprisedb.com/download-postgresql-binaries oder via Docker)

## Installation

Mit den folgenden Schritten wird die lokale Datenbank für das Projekt vorbereitet und das Schema initialisiert.

Befehle:
```bash
# 1. Mit UTF-8 neu initialisieren
mkdir C:\Users\Internet\Downloads\postgresql-18.6-5-windows-x64-binaries\pgsql\data

C:\Users\Internet\Downloads\postgresql-18.6-5-windows-x64-binaries\pgsql\bin\initdb.exe `
  -D C:\Users\Internet\Downloads\postgresql-18.6-5-windows-x64-binaries\pgsql\data `
  -U postgres `
  -A trust `
  --encoding=UTF8 `
  --locale=C

# 2. Server starten
C:\Users\Internet\Downloads\postgresql-18.6-5-windows-x64-binaries\pgsql\bin\pg_ctl.exe -D C:\Users\Internet\Downloads\postgresql-18.6-5-windows-x64-binaries\pgsql\data -l C:\Users\Internet\Downloads\postgresql-18.6-5-windows-x64-binaries\pgsql\logfile.log start

# 3. Datenbank mit UTF-8 erstellen
C:\Users\Internet\Downloads\postgresql-18.6-5-windows-x64-binaries\pgsql\bin\psql.exe -U postgres -h localhost -c "CREATE DATABASE gendb WITH ENCODING='UTF8' LC_COLLATE='C' LC_CTYPE='C';"

# 4. Schema initialisieren
cd C:\Users\sepp5\Git\gen-db
C:\Users\Internet\Downloads\postgresql-18.6-5-windows-x64-binaries\pgsql\bin\psql.exe -U postgres -h localhost -d gendb -f init-db.sql
```

## Abhängigkeiten

Für die Netzwerkanalyse wird zusätzlich der Subgraph-Algorithmus installiert, der über die Projektabhängigkeiten eingebunden wird:

```bash
pip install -e ".[dev]"
```
Es wird die API des Subgraph Algorithmus genutzt mit `Subgraph().compare_graphs(A, B)`.

### Optional: C++-Implementierung (csubgraph)

Die Suche nutzt die C++-Implementierung aus dem Repository `csubgraph` als Bibliothek, wenn in der `.env` der Pfad zu `libsubgraphlib.a` gesetzt ist. Ist `CSUBGRAPH_LIB_PATH` nicht gesetzt (leer oder auskommentiert), wird die Python-Implementierung verwendet.

```env
# Datei libsubgraphlib.a oder Projekt-/Build-Ordner von csubgraph; leer = Python
CSUBGRAPH_LIB_PATH=C:/Users/<name>/Git/csubgraph/build/libsubgraphlib.a
```

Der Pfad darf direkt auf `libsubgraphlib.a` zeigen oder auf einen Ordner, in dem sie liegt (Projektordner, `build/`, `build/Release`). Eine statische Bibliothek kann Python nicht direkt laden. Beim ersten Gebrauch linkt Gen-DB sie deshalb mit einem kleinen C-Wrapper (`src/backend/native/csubgraph_shim.cpp`) zu einer DLL/`.so` und ruft sie per `ctypes` direkt im Worker-Prozess auf, ohne Prozessstart und ohne JSON je Vergleich. Voraussetzungen:

- ein C++-Compiler im `PATH` (oder über die Umgebungsvariable `CXX`), unter Windows derselbe MinGW-w64 `g++`, mit dem `libsubgraphlib.a` gebaut wurde
- die Bibliothek muss mit diesem Compiler gebaut sein; der Header `SubgraphAlgorithm.h` wird neben der Bibliothek (Projektordner) gesucht, sonst wird die mitgelieferte Kopie in `src/backend/native/` verwendet

Die gelinkte Wrapper-Bibliothek liegt im Cache-Ordner `<temp>/gen-db-csubgraph` (änderbar mit `GENDB_NATIVE_CACHE`) und wird nur neu gebaut, wenn sich `libsubgraphlib.a`, der Wrapper oder der Header ändern. Der Build läuft einmalig beim Start, bevor die Worker-Prozesse erzeugt werden. Ist die Bibliothek nicht auffindbar oder nicht nutzbar (kein Compiler, Link- oder Ladefehler), steht der Grund als Warnung im Log und es wird die Python-Implementierung verwendet. Beim Start steht im Log, welcher Algorithmus verwendet wird. Die Ergebnisse der C++-Version werden auf die Python-Werte abgebildet (`KEEP_B` → `keep_B`, `IDENTICAL` → `equal_keep_A`/`equal_keep_B`), sodass die Suche in `crud.py` unverändert bleibt. Im Docker-Image ist csubgraph nicht enthalten; dort läuft die Python-Implementierung.

Hinweis: Das CMake-Projekt von csubgraph baut die Bibliothek mit `--coverage` (gcov). Das wird beim Linken erkannt und berücksichtigt, die Bibliothek schreibt dann beim Prozessende `.gcda`-Dateien. Für den Produktivbetrieb und für Messungen ist eine Bibliothek ohne Coverage-Instrumentierung etwas schneller.

#### Backend-Experiment

Der Vergleich von Python und C++ lässt sich mit derselben Datenbank und denselben Queries ausführen:

```powershell
python src/experiment_search_backends.py
```

Das Experiment verwendet standardmäßig sechs mit Seed `42` ausgewählte Queries mit mindestens 15 Knoten und zwei Worker je Backend. Es prüft, welches Backend tatsächlich in den Workern aktiv ist, vergleicht die Treffer-IDs und zählt fehlgeschlagene Vergleiche. Die Laufzeit umfasst die vollständige Suche einschließlich Datenbankzugriff, Worker-Kommunikation und Ergebnisaufbau. Ein separater Mikrobenchmark vergleicht 200 identische Zufallsgraphpaare und misst zusätzlich einen trivialen Library-Aufruf.

Im abgeschlossenen Messlauf vom 7. Oktober 2026 durchliefen beide Backends jeweils `931.899` Kandidaten. Python benötigte insgesamt `1.180,28 s`, die C++-Library `185,62 s`; das entspricht einem Ende-zu-Ende-Speedup von `6,36×`. Für jede der sechs Queries war die C++-Suche schneller, die Treffer-IDs waren identisch und es traten keine fehlgeschlagenen Vergleiche auf. Im Mikrobenchmark betrug die mittlere Zeit je Einzelvergleich `2,694 ms` für Python und `0,074 ms` für C++; ein trivialer `1×1`-Library-Aufruf lag bei `0,018 ms`.

Diese Messwerte gelten für sechs einzelne Suchläufe auf synthetischen Daten unter Windows 11 mit zwei Workern. Sie sind ein Ergebnis dieses Versuchsaufbaus, keine allgemeine Leistungsgarantie; insbesondere fehlen Wiederholungen, Konfidenzintervalle, reale biologische Daten und Messungen auf weiteren Plattformen. Ältere Messungen über die C++-CLI verwendeten einen anderen Aufrufpfad mit Prozessstart und JSON je Vergleich und sind nicht mit dem hier beschriebenen Library-Ergebnis gleichzusetzen.

Die Resultate werden unter `src/results/` mit Zeitstempel abgelegt. Die vorhandene JSON-Datei kann ohne erneuten Suchlauf für neue Diagramme und LaTeX-Tabellen verwendet werden:

```powershell
python src/experiment_search_backends.py --plot-from src/results/search_backends_20261007_104804.json
```

Mit `--queries 2` kann vor einer längeren Messung ein kleiner Vorabtest ausgeführt werden. Während des Experiments sollte der API-Server beendet sein, damit er nicht mit den Worker-Prozessen um Ressourcen konkurriert.

### Multi-Omics

Ein Multi-Omics-Netzwerk besteht aus mehreren Schichten (z. B. Transkriptom, Proteom, Metabolom) über denselben Knoten. Jede Schicht ist eine eigene Adjazenzmatrix, alle Schichten teilen sich die `node_labels`. Gespeichert wird es in den Tabellen `omics_networks` und `omics_layers`; die Metadaten stehen wie bei jedem Netzwerk in `biological_networks` (`edge_count` ist die Summe über alle Schichten, Löschen entfernt per `CASCADE` auch die Schichten). Die Zeilenkomponenten je Schicht liegen als `BIGINT[]` vor und passen bis 63 Knoten hinein.

| Endpoint | Zweck |
|---|---|
| `POST /api/multiomics` | Netzwerk mit Schichten anlegen (`layers`: Liste aus `layer_name` und `adjacency_matrix`) |
| `GET /api/multiomics/{network_id}` | Netzwerk mit allen Schichten lesen |
| `POST /api/multiomics/search` | Suche: Query-Schichten (nach Name) in allen Netzwerken, die diese Schichten besitzen |

Die Suche kennt zwei Modi (`mode`): `coherent` (Standard) verlangt, dass alle Schichten der Query an derselben Position des Kandidaten übereinstimmen, `independent` erlaubt je Schicht eine eigene Position. `coherent` ist strenger; jeder kohärente Treffer ist auch ein unabhängiger Treffer. Ungültige Eingaben (doppelte Schichtnamen, nicht quadratische oder nicht binäre Matrizen, mehr als 63 Knoten, falsche Zahl an Labels) liefern `422`.

Der Algorithmus wird **genauso wie der Subgraph Algorithmus über die `.env`** ausgewählt, es gibt keine neue Einstellung: Zeigt `CSUBGRAPH_LIB_PATH` auf eine `libsubgraphlib.a`, die `MultiOmics` enthält (csubgraph mit `MultiOmics.cpp`), läuft die Suche über die C++-Klasse `MultiOmics`. Dafür wird ein zweiter C-Wrapper (`src/backend/native/csubgraph_omics_shim.cpp`) mit derselben Bibliothek gelinkt und per `ctypes` im Worker-Prozess aufgerufen, gebaut und gecacht wie der Wrapper für den Einzelvergleich. Ist der Pfad nicht gesetzt oder die Bibliothek nicht nutzbar, steht der Grund als Warnung im Log und es läuft die Python-Implementierung (`src/backend/multiomics_python.py`). Eine ältere `libsubgraphlib.a` ohne `MultiOmics` betrifft nur Multi-Omics: der Einzelvergleich bleibt bei C++, Multi-Omics nutzt Python. Nach dem Aktualisieren von csubgraph muss die Bibliothek neu gebaut werden. Beim Start steht im Log, welcher Algorithmus für Multi-Omics gewählt wurde.

#### Multi-Omics-Experiment

Das Experiment `src/experiment_search_multiomics.py` vergleicht die Python- und die C++-Implementierung der Multi-Omics-Suche und besteht aus sechs Teilexperimenten: Korrektheit (ohne Datenbank, inklusive Invarianten), Mikro-Benchmark je Einzelvergleich (Schichtzahl, Knotenzahl, Modus), Ende-zu-Ende-Suche (Anfragengitter, Wiederholungen, Phasen, Speedup mit Konfidenzintervall, Trefferquote gegen bekannte Lösungen), Worker-Skalierung, Chunk-Größe und Datenbankgröße.

```powershell
python src/experiment_search_multiomics.py --quick      # kleiner Vorabtest
python src/experiment_search_multiomics.py              # vollständig (mehrere Stunden)
python src/experiment_search_multiomics.py --only correctness micro
python src/experiment_search_multiomics.py --plot-from src/results/search_multiomics_<zeit>.json
python src/experiment_search_multiomics.py --cleanup-only
```

Das Experiment legt synthetische Netzwerke mit dem Typ `multi_omics_experiment` in der Datenbank an (Zufallsnetzwerke und je eingebetteter Anfrage Netzwerke mit bekannter Lösung); andere Netzwerke bleiben unverändert. `--cleanup` entfernt die Experiment-Netzwerke am Ende, `--rebuild-data` erzeugt sie neu. Die Ergebnisse (JSON, PDF, Textbericht, LaTeX-Tabellen, `plot11_…` bis `plot26_…`) liegen unter `src/results/`. Das Skript ist in `pyproject.toml` unter `omit` eingetragen und zählt nicht zur Testabdeckung.

Die Kandidaten werden nur nach der Knotenzahl (`node_count >= n_Query`) und dem Vorhandensein aller Query-Schichten vorgefiltert. Eine Vorauswahl nach der Kantenzahl gibt es hier bewusst nicht: Mit der Relation des Algorithmus kann ein Graph mit mehr Kanten in einem Graphen mit weniger Kanten enthalten sein (Beispiel in `tests/test_multiomics_python.py::test_edge_count_is_not_monotone`).

Die Datenbank-Tabellen für Multi-Omics stehen in `init-db.sql`; bei einer bestehenden Datenbank genügt es, die beiden neuen `CREATE TABLE`-Anweisungen und den Index auszuführen. Das Web-Frontend nutzt die Multi-Omics-Endpoints noch nicht.

## SQL-Strutkur

Die Datenbankstruktur wird durch `init-db.sql` definiert und ist bewusst einfach, aber für die Suche nach biologischen Netzwerken effizient aufgebaut. Das Schema besteht aus zwei zentralen Tabellen, die zusammen den eigentlichen Netzwerkinhalt und die zugehörigen Metadaten modellieren.

### 1) `biological_networks`

Diese Tabelle enthält die allgemeinen Informationen zu jedem biologischen Netzwerk.

```sql
CREATE TABLE IF NOT EXISTS biological_networks (
    network_id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    network_type VARCHAR(50),
    organism VARCHAR(100),
    description TEXT,
    node_count INTEGER NOT NULL,
    edge_count INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

Wichtige Spalten:

- `network_id`: eindeutiger Primärschlüssel, automatisch hochgezählt (`SERIAL`)
- `name`: Name des Netzwerks, z. B. "Glycolysis" oder "DNA_Damage_Response"
- `network_type`: Typ des Netzwerkes, z. B. `metabolic` oder `protein`
- `organism`: biologische Spezies, z. B. `Homo sapiens`
- `description`: frei formulierte Beschreibung des Netzwerkes
- `node_count` / `edge_count`: Anzahl der Knoten und Verbindungen
- `created_at`: Erstellungszeitpunkt, per `NOW()` gesetzt

Diese Tabelle ist der Zugriffspunkt für Listen, Filterung und Überblickabfragen. Über sie lassen sich zum Beispiel alle metabolischen Netzwerke eines Organismus oder alle Netzwerke mit einer gewissen Größe schnell abrufen.

### 2) `network_matrices`

Diese Tabelle speichert den eigentlichen mathematischen Repräsentationssatz eines Netzwerks. Jede Zeile entspricht genau einem Netzwerk und ist über `network_id` mit `biological_networks` verknüpft.

```sql
CREATE TABLE IF NOT EXISTS network_matrices (
    network_id INTEGER PRIMARY KEY REFERENCES biological_networks(network_id) ON DELETE CASCADE,
    node_labels TEXT[] NOT NULL,
    adjacency_matrix INTEGER[][] NOT NULL,
    signature_array BIGINT[] NOT NULL,
    signature_hash VARCHAR(64)
);
```

Wichtige Spalten:

- `network_id`: Primärschlüssel der Matrix-Tabelle und Fremdschlüssel auf `biological_networks`
- `node_labels`: Array mit den Namen der Knoten, z. B. `ARRAY['Glucose', 'G6P', 'Pyruvate']`
- `adjacency_matrix`: zweidimensionales Integer-Array für die Nachbarschaftsstruktur
- `signature_array`: numerische Signatur des Netzwerks als Array aus `BIGINT`
- `signature_hash`: optionaler Hashwert zur schnellen Identifikation bzw. Vergleichbarkeit

`node_labels` und `adjacency_matrix` sind gemeinsam die eigentliche Repräsentation des Graphen. Das Adjazenzmatrix-Format erlaubt schnelle algorithmische Verarbeitung, etwa für Subgraph-Vergleiche oder Suchvorgänge. Die `signature_array` ist für eine komprimierte, numerische Beschreibung des Netzwerks gedacht, die ebenfalls für schnelle Vergleiche genutzt werden kann.

### Beziehung zwischen den Tabellen

Es gibt ein 1:1-Verhältnis zwischen `biological_networks` und `network_matrices`:

- Ein Eintrag in `biological_networks` beschreibt ein Netzwerk metadata-seitig.
- Der dazugehörige Eintrag in `network_matrices` enthält die eigentliche Struktur.
- `ON DELETE CASCADE` sorgt dafür, dass zugehörige Matrixdaten automatisch gelöscht werden, wenn das Netzwerk entfernt wird.

Das ist sinnvoll, weil die Matrixdaten ohne das Netzwerk keine eigene Bedeutung haben und deshalb immer zusammen behandelt werden.

### Indizes für Performance

Die SQL-Datei legt einige Indizes an, damit typische Filter- und Suchfragen performant bleiben:

```sql
CREATE INDEX IF NOT EXISTS idx_networks_type ON biological_networks(network_type);
CREATE INDEX IF NOT EXISTS idx_networks_organism ON biological_networks(organism);
CREATE INDEX IF NOT EXISTS idx_networks_node_count ON biological_networks(node_count);
CREATE INDEX IF NOT EXISTS idx_matrices_hash ON network_matrices(signature_hash);
```

Diese Indizes unterstützen insbesondere:

- Suche nach Netzwerktyp (`network_type`)
- Filterung nach Organismus (`organism`)
- Auswahl nach Größe (`node_count`)
- Schnelle Identifikation bzw. Wiederverwendung von Matrix-Signaturen (`signature_hash`)

Ohne Indexe würden solche Abfragen bei großen Datenmengen deutlich langsamer werden.

### Beispiel-Daten

In `init-db.sql` werden bereits zwei Beispielnetzwerke eingefügt:

1. `Glycolysis`
   - Typ: `metabolic`
   - Organismus: `Homo sapiens`
   - Knoten: 7
   - Kanten: 6

2. `DNA_Damage_Response`
   - Typ: `protein`
   - Organismus: `Homo sapiens`
   - Knoten: 5
   - Kanten: 6

Jedes dieser Beispiele enthält ebenfalls eine passende Matrix-Definition mit:

- `node_labels`
- `adjacency_matrix`
- `signature_array`
- `signature_hash`

Damit ist das Schema sofort nutzbar und kann direkt als Grundlage für Analysen und Vergleiche dienen.

### Typische Nutzung

Die Struktur ist so aufgebaut, dass typische Abfragen möglichst einfach sind:

```sql
SELECT *
FROM biological_networks
WHERE organism = 'Homo sapiens';
```

```sql
SELECT n.name, n.network_type, m.signature_hash
FROM biological_networks n
JOIN network_matrices m ON m.network_id = n.network_id
WHERE n.network_type = 'metabolic';
```

Diese Abfragen liefern Metadaten bzw. Matrix-Referenzen, auf denen anschließend die eigentliche Graph-Analyse oder Subgraph-Suche aufbauen kann.

### Warum diese Struktur?

Die Trennung in zwei Tabellen ist bewusst gewählt:

- `biological_networks` hält die Business- und Suchinformationen.
- `network_matrices` hält die hochdimensionale, strukturbezogene Datenrepräsentation.

Diese Aufteilung macht das System leicht erweiterbar: Wenn später weitere Netzwerk-Typen, Zusatzinformationen oder Analysestufen hinzukommen, kann man das Schema ohne größere Umbauten an die vorhandene Struktur anpassen.

Insgesamt bildet `init-db.sql` damit eine robuste Grundlage für das Speichern, Suchen und Vergleichen biologischer Netzwerke in PostgreSQL.

## 1.000.000 Netzwerke

Mit diesem Schritt werden eine Million synthetische biologische Netzwerke erzeugt, um umfangreiche Such- und Vergleichsanalysen mit realistischer Datenmenge zu ermöglichen.

Befehl:
```bash
python .\db-populate.py
```

## Starten

Der lokale Server wird mit einem kurzen Uvicorn-Befehl gestartet und anschließend über die Standard-URL erreichbar gemacht:

Befehl:
```bash
python -m uvicorn src.backend.app:app --reload
```

URL:
```bash
http://127.0.0.1:8000
```


Ausgabe:
```bash
(venv) PS C:\Users\Internet\Git\gen-db> python -m uvicorn src.backend.app:app --reload
INFO:     Will watch for changes in these directories: ['C:\\Users\\Internet\\Git\\gen-db']
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [4128] using WatchFiles
2026-10-07 10:46:19 [INFO] Configuration loaded (ENV=development)
INFO:     Started server process [7012]
INFO:     Waiting for application startup.
2026-10-07 10:46:19 [INFO] Starting Gen API - Environment: development
2026-10-07 10:46:19 [INFO] Subgraph algorithm selected: csubgraph (C++)
2026-10-07 10:46:19 [INFO] ProcessPoolExecutor ready for Subgraph Executor
INFO:     Application startup complete.
2026-10-07 10:46:52 [INFO] GET / - Serving frontend
INFO:     127.0.0.1:51928 - "GET / HTTP/1.1" 200 OK
2026-10-07 10:46:53 [INFO] GET /api/networks limit=33 random=True
2026-10-07 10:46:53 [INFO] get_all_networks: limit=33 random_sample=True
2026-10-07 10:46:58 [INFO] get_all_networks: Fetched 33 records
2026-10-07 10:46:58 [INFO] GET /api/networks - Returned 33 networks
INFO:     127.0.0.1:51928 - "GET /api/networks?limit=33&random=true HTTP/1.1" 200 OK
INFO:     127.0.0.1:57531 - "GET /favicon.ico HTTP/1.1" 204 No Content
```

## Suchen

Die Suche läuft über das Web-Frontend und ermöglicht den Vergleich biologischer Netzwerke über die Subgraph-Suche direkt im Browser.

Ausgabe:
```bash
(venv) PS C:\Users\Internet\Git\gen-db> python -m uvicorn src.backend.app:app --reload
INFO:     Will watch for changes in these directories: ['C:\\Users\\Internet\\Git\\gen-db']
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [4128] using WatchFiles
2026-10-07 10:46:19 [INFO] Configuration loaded (ENV=development)
INFO:     Started server process [7012]
INFO:     Waiting for application startup.
2026-10-07 10:46:19 [INFO] Starting Gen API - Environment: development
2026-10-07 10:46:19 [INFO] Subgraph algorithm selected: csubgraph (C++)
2026-10-07 10:46:19 [INFO] ProcessPoolExecutor ready for Subgraph Executor
INFO:     Application startup complete.
2026-10-07 10:46:52 [INFO] GET / - Serving frontend
INFO:     127.0.0.1:51928 - "GET / HTTP/1.1" 200 OK
2026-10-07 10:46:53 [INFO] GET /api/networks limit=33 random=True
2026-10-07 10:46:53 [INFO] get_all_networks: limit=33 random_sample=True
2026-10-07 10:46:58 [INFO] get_all_networks: Fetched 33 records
2026-10-07 10:46:58 [INFO] GET /api/networks - Returned 33 networks
INFO:     127.0.0.1:51928 - "GET /api/networks?limit=33&random=true HTTP/1.1" 200 OK
INFO:     127.0.0.1:57531 - "GET /favicon.ico HTTP/1.1" 204 No Content
2026-10-07 10:47:03 [INFO] GET /api/networks/205670
2026-10-07 10:47:03 [INFO] get_network_by_id: network_id=205670
2026-10-07 10:47:03 [INFO] get_network_by_id: Found network 'gene_regulation_E._coli_205670'
2026-10-07 10:47:03 [INFO] GET /api/networks/205670 - Found: gene_regulation_E._coli_205670
INFO:     127.0.0.1:51928 - "GET /api/networks/205670 HTTP/1.1" 200 OK
2026-10-07 10:47:07 [INFO] GET /api/networks/718195
2026-10-07 10:47:07 [INFO] get_network_by_id: network_id=718195
2026-10-07 10:47:08 [INFO] get_network_by_id: Found network 'protein_Homo_sapiens_718195'
2026-10-07 10:47:08 [INFO] GET /api/networks/718195 - Found: protein_Homo_sapiens_718195
INFO:     127.0.0.1:51928 - "GET /api/networks/718195 HTTP/1.1" 200 OK
2026-10-07 10:47:10 [INFO] POST /api/networks/search - nodes=16
2026-10-07 10:47:10 [INFO] search_subgraph: Starting search for subgraph with 16 nodes
2026-10-07 10:47:45 [INFO] search_subgraph: 277270 candidates for query (n=16, e=58)
2026-10-07 10:47:45 [INFO] ProcessPoolExecutor initialized with 2 workers
2026-10-07 10:48:01 [INFO] search_subgraph: Found 4 matches
2026-10-07 10:48:02 [INFO] POST /api/networks/search - Found 4 matches
INFO:     127.0.0.1:51928 - "POST /api/networks/search HTTP/1.1" 200 OK
```

## Testen

Die automatisierten Tests laufen gegen eine separate Test-Datenbank, damit die Validierung der Funktionalität ohne Einfluss auf die lokale Entwicklungsumgebung erfolgt.

```bash
pytest
```
Der Coverage-Report wird automatisch generiert nach `doc/coverage/index.html`.

## Erwerb

Der Preis für diese Software beträgt 3.745.000,00 EUR.

### Zahlungsinformationen

Name: Stephan Epp  
IBAN: DE24 5003 1900 0012 5603 20
BIC: BBVADEFFXXX