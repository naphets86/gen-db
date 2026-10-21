# gen-db

Biological Network Database mit PostgreSQL-Backend, FastAPI-REST-API und Web-Frontend zur Analyse biologischer Netzwerke. Neben der klassischen Subgraph-Suche unterstützt das Projekt Multi-Omics-Daten und eine schemaabhängige universelle Kodierung mit SQL-Paarindex.

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/Tests-743%20passed-4c1)](tests/)
[![Test Coverage](https://img.shields.io/badge/Test%20Coverage-97%25-brightgreen)](doc/coverage/index.html)
[![scicov](https://img.shields.io/badge/scicov-10-ff69b4)](doc/coverage/index.html)

## Inhaltsverzeichnis

- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Abhängigkeiten](#abhängigkeiten)
  - [Optional: C++-Implementierung (csubgraph)](#optional-c-implementierung-csubgraph)
    - [Aufbau der Brücke](#aufbau-der-brücke)
    - [Voraussetzungen](#voraussetzungen-1)
    - [Wo die Bibliothek gesucht wird](#wo-die-bibliothek-gesucht-wird)
    - [Bibliotheksdatei je Plattform](#bibliotheksdatei-je-plattform)
    - [Zwischenspeicher und Neuaufbau](#zwischenspeicher-und-neuaufbau)
    - [Umgebungsvariablen und Optionen](#umgebungsvariablen-und-optionen)
    - [Verhalten bei Fehlern](#verhalten-bei-fehlern)
    - [Fehlersuche](#fehlersuche)
    - [Ausblick: Plattformneutrales Laden](#ausblick-plattformneutrales-laden)
  - [Multi-Omics](#multi-omics)
- [Universelle Kodierung](#universelle-kodierung-universal-coding)
  - [Universal-API](#universal-api)
- [SQL-Struktur](#sql-struktur)
- [1.000.000 Netzwerke](#1000000-netzwerke)
- [Server starten](#server-starten)
- [Netzwerke suchen](#netzwerke-suchen)
- [Multi-Omics-API](#multi-omics-api)
- [Automatisch testen](#automatisch-testen)
- [UML mit Pyreverse](#uml-mit-pyreverse)
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

Für die Netzwerkanalyse wird zusätzlich der Subgraph Algorithmus installiert, der über die Projektabhängigkeiten eingebunden wird:

```bash
pip install -e ".[dev]"
```
Es wird die API des Subgraph Algorithmus genutzt mit `Subgraph().compare_graphs(A, B)`.

### Optional: C++-Implementierung (csubgraph)

Die Suche kann die C++-Implementierung aus dem Repository `csubgraph` als Bibliothek nutzen. Aktiviert wird sie über die `.env`; ohne Einstellung läuft die Python-Implementierung.

```env
# Datei libsubgraphlib.a oder Projekt-/Build-Ordner von csubgraph; leer = Python
CSUBGRAPH_LIB_PATH=C:/Users/<name>/Git/csubgraph/build/libsubgraphlib.a   # Windows
# CSUBGRAPH_LIB_PATH=/home/<name>/git/csubgraph/build/libsubgraphlib.a     # Linux, macOS
```

#### Aufbau der Brücke

```
Suche (crud.py) → subgraph_executor → csubgraph_native.py (ctypes) → C-Wrapper (DLL/.so/.dylib) → libsubgraphlib.a (C++)
                                                                      csubgraph_shim.cpp / csubgraph_omics_shim.cpp
```

| Schicht | Aufgabe |
|---------|---------|
| `csubgraph_native.py` | Findet die Bibliothek, baut und lädt den Wrapper per `ctypes`, prüft die Schnittstellenversion und bildet die Ergebnisse auf die Python-Werte ab |
| `native/csubgraph_shim.cpp` | C-Schnittstelle für den Einzelvergleich (`csub_compare`, `csub_abi_version`) |
| `native/csubgraph_omics_shim.cpp` | C-Schnittstelle für Multi-Omics (`csub_omics_compare`, `csub_omics_abi_version`) |
| `libsubgraphlib.a` | Statische C++-Bibliothek aus dem Repository `csubgraph` |

Eine statische Bibliothek kann Python nicht direkt laden: `ctypes` öffnet nur dynamische Bibliotheken mit C-Funktionen. Beim ersten Gebrauch linkt Gen-DB deshalb `libsubgraphlib.a` mit dem passenden C-Wrapper zu einer dynamischen Bibliothek und ruft sie per `ctypes` direkt im Worker-Prozess auf, ohne Prozessstart und ohne JSON je Vergleich.

Dass Gen-DB diesen Schritt **automatisch** ausführt, ist eine bewusste Entscheidung: Gen-DB ist eine Anwendung mit einem klar definierten Start. Der Build läuft einmalig dort, bevor die Worker-Prozesse erzeugt werden, und das Ergebnis wird zwischengespeichert. Das Python-Paket [`subgraph-sat-solver-econ`](https://github.com/naphets86/subgraph-sat-solver-econ) geht den entgegengesetzten Weg und baut seine Bibliothek ausdrücklich vorab, weil es als Bibliothek und für reproduzierbare Messungen gedacht ist.

#### Voraussetzungen

- ein C++-Compiler im `PATH` (oder über die Umgebungsvariable `CXX`). Gesucht wird in der Reihenfolge `$CXX`, `g++`, `c++`, `clang++`. Unter Windows derselbe MinGW-w64 `g++`, mit dem `libsubgraphlib.a` gebaut wurde
- die Bibliothek muss mit diesem Compiler gebaut sein und als `libsubgraphlib.a` vorliegen (Format von GCC/MinGW/Clang); eine MSVC-`.lib` wird nicht gefunden
- der Header `SubgraphAlgorithm.h` (für Multi-Omics zusätzlich `MultiOmics.h`) wird neben der Bibliothek gesucht (Projektordner, Ordner darüber, `include/`), sonst wird die mitgelieferte Kopie in `src/backend/native/` verwendet

#### Wo die Bibliothek gesucht wird

`CSUBGRAPH_LIB_PATH` darf direkt auf `libsubgraphlib.a` zeigen oder auf einen Ordner. Im Ordner wird in dieser Reihenfolge gesucht: der Ordner selbst, `build/`, `build/Release`, `Release`. Ist die Einstellung leer oder die Datei nicht auffindbar, wird die Python-Implementierung verwendet.

#### Bibliotheksdatei je Plattform

Die eingelesene Bibliothek heißt auf allen Plattformen `libsubgraphlib.a`. Der daraus gelinkte Wrapper erhält den Dateityp des Betriebssystems und liegt im Cache-Ordner:

| Plattform | Wrapper-Datei im Cache | Besonderheiten beim Linken |
|-----------|------------------------|----------------------------|
| Windows (MinGW) | `csubgraph_shim_<hash>.dll` | C++-Laufzeit statisch gelinkt (`-static`), damit keine `libstdc++-6.dll` nachgeladen werden muss |
| Linux | `csubgraph_shim_<hash>.so` | `-fPIC`, gesamter Archivinhalt über `--whole-archive` |
| macOS | `csubgraph_shim_<hash>.dylib` | gesamter Archivinhalt über `-force_load` |

Für Multi-Omics entsteht zusätzlich `csubgraph_omics_shim_<hash>.<Endung>`. Das sind drei Binärformate mit eigenen Lademechanismen des Betriebssystems; alle plattformabhängigen Teile (Dateiendung, Linker-Optionen, Export-Markierung im Wrapper) sind in `csubgraph_native.py` und `src/backend/native/` gebündelt.

#### Zwischenspeicher und Neuaufbau

Der gelinkte Wrapper liegt im Cache-Ordner `<temp>/gen-db-csubgraph` (änderbar mit `GENDB_NATIVE_CACHE`). Der Dateiname enthält einen Hash über `libsubgraphlib.a`, den Wrapper, die Header und die Schnittstellenversion. Er wird nur neu gebaut, wenn sich eines davon ändert. Der Build schreibt zuerst in eine temporäre Datei und benennt sie atomar um, damit parallel startende Worker keine halbfertige Datei laden. Nach dem Aktualisieren von csubgraph muss `libsubgraphlib.a` neu gebaut werden; Gen-DB erkennt die Änderung am Hash.

#### Umgebungsvariablen und Optionen

| Einstellung | Wirkung | Standard |
|-------------|---------|----------|
| `CSUBGRAPH_LIB_PATH` (`.env`) | `libsubgraphlib.a` oder Ordner, der sie enthält | leer = Python |
| `CXX` | Zu verwendender C++-Compiler | `g++`, `c++`, `clang++` im `PATH` |
| `GENDB_NATIVE_CACHE` | Cache-Ordner für die gelinkten Wrapper | `<temp>/gen-db-csubgraph` |
| `--csubgraph-lib-path` | Überschreibt `CSUBGRAPH_LIB_PATH` in den Experimenten (z. B. `experiment_search_universal.py`) | Wert aus der `.env` |

#### Verhalten bei Fehlern

Ist die Bibliothek nicht auffindbar oder nicht nutzbar (kein Compiler, Link- oder Ladefehler), steht der Grund als Warnung im Log und es wird die Python-Implementierung verwendet. Beim Start steht im Log, welcher Algorithmus verwendet wird. Eine ältere `libsubgraphlib.a` ohne `MultiOmics` betrifft nur Multi-Omics: der Einzelvergleich bleibt bei C++, Multi-Omics nutzt Python. Die Experimente dagegen prüfen, dass kein stiller Rückfall stattfindet. Im Docker-Image ist csubgraph nicht enthalten; dort läuft die Python-Implementierung.

Die Ergebnisse der C++-Version werden auf die Python-Werte abgebildet (`KEEP_B` → `keep_B`, `IDENTICAL` → `equal_keep_A`/`equal_keep_B`), sodass die Suche in `crud.py` unverändert bleibt.

#### Fehlersuche

| Meldung im Log | Wahrscheinliche Ursache | Abhilfe |
|----------------|-------------------------|---------|
| `libsubgraphlib.a nicht gefunden (CSUBGRAPH_LIB_PATH=…)` | Pfad falsch, Bibliothek nicht gebaut oder MSVC-Format | Pfad prüfen, csubgraph mit GCC/MinGW bauen |
| `kein C++-Compiler gefunden (g++ in den PATH legen oder Umgebungsvariable CXX setzen)` | Compiler fehlt oder liegt nicht im `PATH` | Compiler installieren, `PATH` oder `CXX` setzen |
| `Build der Wrapper-Bibliothek fehlgeschlagen (…)` | Compiler und der Compiler der Bibliothek passen nicht zusammen, Header fehlen | Mit demselben Compiler wie csubgraph bauen; Ausgabe in der Meldung lesen |
| `Build der Wrapper-Bibliothek nicht möglich` | Compiler nicht startbar oder Zeitlimit des Builds überschritten | Compiler direkt aufrufen und prüfen |
| `Wrapper-Bibliothek nicht ladbar` | Architektur passt nicht (32 gegen 64 Bit), Cache-Datei beschädigt | Cache-Ordner löschen, Python und Compiler mit gleicher Architektur nutzen |
| `Wrapper-Version … statt …` | Cache stammt aus einem anderen Stand | Cache-Ordner löschen |
| `… enthält keine MultiOmics-Klasse (csubgraph mit MultiOmics.cpp neu bauen)` | Ältere `libsubgraphlib.a` | csubgraph neu bauen |

Hinweis: Das CMake-Projekt von csubgraph baut die Bibliothek mit `--coverage` (gcov). Das wird beim Linken erkannt und berücksichtigt (`-lgcov`), die Bibliothek schreibt dann beim Prozessende `.gcda`-Dateien. Für den Produktivbetrieb und für Messungen ist eine Bibliothek ohne Coverage-Instrumentierung etwas schneller.

#### Ausblick: Plattformneutrales Laden

Die oben beschriebenen Plattformunterschiede (Dateiendung, Linker-Optionen, Export-Markierung, Laufzeitbibliotheken, Fehlermeldungen) betreffen nicht dieses Projekt allein. Der Vorschlag [A Unified Shared Library Format (`.sl`) with a Standardized Loading Procedure](https://github.com/naphets86/blog/blob/main/unified-shared-library-proposal.md) beschreibt, wie ein einheitliches Format und vor allem ein standardisiertes, betriebssystemunabhängiges Ladeverfahren (eine Suchreihenfolge, ein Fehlermodell, ein Lebenszyklus) diese Teile aus jedem Projekt entfernen könnten.

Das ist ein Diskussionsvorschlag. In diesem Repository ist er **nicht umgesetzt**; es gilt der in diesem Abschnitt beschriebene Stand mit `.dll`, `.so` und `.dylib`.

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

#### Parallelisierungsexperiment

`src/experiment_search_workers.py` vergleicht dieselben Datenbankanfragen mit unterschiedlich vielen Prozess-Workern. Der Messwert umfasst die vollständige Suche einschließlich Laden der Kandidaten und Aufbau der Trefferliste; Warm-up-Läufe werden verworfen.

```powershell
python src/experiment_search_workers.py --queries 6 --workers 1 2 3 --seed 42
```

Im abgeschlossenen Lauf vom 5. Oktober 2026 wurden sechs mit Seed `42` aus der Datenbank ausgewählte Anfragen mit mindestens 15 Knoten verwendet. Auf dem Messsystem (Linux, Python 3.13.16, zwei logische CPUs) ergaben sich:

| Worker | Gesamtzeit | Mittlere Zeit je Anfrage | Speedup gegenüber 1 Worker |
|---:|---:|---:|---:|
| 1 | 1.604,17 s | 267,4 s | 1,00× |
| 2 | 843,09 s | 140,5 s | 1,90× |
| 3 | 907,64 s | 151,3 s | 1,77× |

Zwei Worker senkten die Gesamtzeit in diesem Lauf um rund 47 %; drei Worker waren rund 7,7 % langsamer als zwei. Das ist mit den zwei logischen CPUs und dem zusätzlichen Prozess- und Koordinationsaufwand vereinbar, belegt aber keine allgemeine optimale Worker-Zahl. Der Test umfasst nur sechs Anfragen und einen Messlauf; die Werte sind daher ein systemspezifischer Anhaltspunkt, keine Leistungsgarantie. Die Ergebnisse und Einzelmessungen liegen in [`search_workers_20261005_071729.json`](src/results/search_workers_20261005_071729.json); der Textbericht steht in [`experiment_log.txt`](src/results/experiment_log.txt).

In der Arbeit werden die sechs Queries einzeln gepaart ausgewertet: Mit zwei Workern liegt ihr Speedup jeweils zwischen `1,87×` und `1,93×`; mit drei Workern zwischen `1,70×` und `1,84×`. Die Kandidatenzahlen reichen von `62.064` bis `325.964` (insgesamt `1.249.054`). Für diese Stichprobe korreliert die Suchzeit mit mindestens `0,99` mit der Kandidatenzahl. Das stützt die lineare Abhängigkeit von der Zahl tatsächlich verglichener Kandidaten, nicht aber eine von der Datenbankgröße unabhängige Laufzeit: Ohne Kandidatenlimit wächst die Kandidatenmenge bei gleichbleibender Selektivität mit der Datenbank und damit auch die Suchzeit. Die Messreihe durchsuchte alle Kandidaten; die längste Query benötigte `403,2 s` mit einem und `212,0 s` mit zwei Workern.

Nur die Kandidatenvergleiche laufen parallel. SQL-Laden, Übergabe/Serialisierung und Aufbau der Trefferliste bleiben im Hauptprozess. Aus dem Speedup von `1,90×` lässt sich für diesen Lauf ein serieller Anteil von ungefähr `5 %` abschätzen; da keine Phasenzeiten geloggt wurden, ist das keine direkte Phasenmessung und keine feste Systemeigenschaft. Die Arbeit beweist unter der angenommenen Reinheit der Vergleichsfunktion, dass die parallele Suche unabhängig von Worker-Zahl, Chunk-Größe und Fertigstellungsreihenfolge dieselbe sortierte Trefferliste wie die sequentielle Suche liefert. Die Zuordnung der Resultate zur ursprünglichen Kandidatenreihenfolge ist dafür wesentlich.

Die drei Worker waren langsamer als zwei. Zur Hardware gibt es allerdings eine Abweichung zwischen den Quellen: Das Kapitel `science/gen-db.tex` verortet diese Messreihe auf einem Rechner mit vier logischen Prozessoren, die Metadaten der zugehörigen JSON-Datei nennen Linux und `logical_cpus=2`. Diese Diskrepanz sollte vor einer weitergehenden Interpretation geklärt werden. Unabhängig davon belegen sechs Queries und ein Lauf je Konfiguration weder eine allgemeine Obergrenze noch eine feste optimale Worker-Zahl. Worker-Zahl und Suchlast sollten auf dem Zielsystem gemessen werden; Parallelisierung senkt die Antwortzeit, ersetzt aber keinen selektiveren Vorfilter oder ein Kandidatenlimit.

Die universelle Suche besitzt zusätzlich eigene Teilexperimente für Worker-Skalierung und Chunk-Größe. Für den derzeit gespeicherten Universal-Lauf liegen dazu noch keine abgeschlossenen Ergebnisse vor; siehe [Universal-Experiment](#universal-experiment-indexsuche-gegen-einzelvergleiche).

### Multi-Omics

Ein Multi-Omics-Netzwerk besteht aus mehreren Schichten (z. B. Transkriptom, Proteom, Metabolom) über denselben Knoten. Jede Schicht ist eine eigene Adjazenzmatrix, alle Schichten teilen sich die `node_labels`. Gespeichert wird es in den Tabellen `omics_networks` und `omics_layers`; die Metadaten stehen wie bei jedem Netzwerk in `biological_networks` (`edge_count` ist die Summe über alle Schichten, Löschen entfernt per `CASCADE` auch die Schichten). Die Zeilenkomponenten je Schicht liegen als `BIGINT[]` vor und passen bis 63 Knoten hinein.

| Endpoint | Zweck |
|---|---|
| `POST /api/multiomics` | Netzwerk mit Schichten anlegen (`layers`: Liste aus `layer_name` und `adjacency_matrix`) |
| `GET /api/multiomics/{network_id}` | Netzwerk mit allen Schichten lesen |
| `POST /api/multiomics/search` | Suche: Query-Schichten (nach Name) in allen Netzwerken, die diese Schichten besitzen |

Die Suche kennt zwei Modi (`mode`): `coherent` (Standard) verlangt, dass alle Schichten der Query an derselben Position des Kandidaten übereinstimmen, `independent` erlaubt je Schicht eine eigene Position. `coherent` ist strenger; jeder kohärente Treffer ist auch ein unabhängiger Treffer. Ungültige Eingaben (doppelte Schichtnamen, nicht quadratische oder nicht binäre Matrizen, mehr als 63 Knoten, falsche Zahl an Labels) liefern `422`.

Der Algorithmus wird **genauso wie der Subgraph Algorithmus über die `.env`** ausgewählt, es gibt keine neue Einstellung: Zeigt `CSUBGRAPH_LIB_PATH` auf eine `libsubgraphlib.a`, die `MultiOmics` enthält (csubgraph mit `MultiOmics.cpp`), läuft die Suche über die C++-Klasse `MultiOmics`. Dafür wird ein zweiter C-Wrapper (`src/backend/native/csubgraph_omics_shim.cpp`) mit derselben Bibliothek gelinkt und per `ctypes` im Worker-Prozess aufgerufen, gebaut und gecacht wie der Wrapper für den Einzelvergleich (Details unter [Optional: C++-Implementierung](#optional-c-implementierung-csubgraph)). Ist der Pfad nicht gesetzt oder die Bibliothek nicht nutzbar, steht der Grund als Warnung im Log und es läuft die Python-Implementierung (`src/backend/multiomics_python.py`). Eine ältere `libsubgraphlib.a` ohne `MultiOmics` betrifft nur Multi-Omics: der Einzelvergleich bleibt bei C++, Multi-Omics nutzt Python. Nach dem Aktualisieren von csubgraph muss die Bibliothek neu gebaut werden. Beim Start steht im Log, welcher Algorithmus für Multi-Omics gewählt wurde.

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

##### Ergebnisse der Parallelisierungs- und Chunk-Reihen

Die Arbeit wertet die abgeschlossenen Worker- und Chunk-Reihen des Multi-Omics-Experiments getrennt für Python und C++ aus. Die Messungen stammen von einem Rechner mit vier physischen/logischen Prozessoren (Intel Core i3-8100T), Windows 11, Python 3.14.8 und 7,87 GB RAM. Je Reihe wurden dieselben sechs Queries zweimal gemessen.

| Worker | Python Gesamtzeit | Python Speedup | C++ Gesamtzeit | C++ Speedup |
|---:|---:|---:|---:|---:|
| 1 | 74,73 s | 1,00× | 24,08 s | 1,00× |
| 2 | 50,31 s | 1,49× | 19,69 s | 1,22× |
| 3 | 39,14 s | 1,91× | 20,08 s | 1,20× |
| 4 | 35,55 s | 2,10× | 18,68 s | 1,29× |

Python profitiert in dieser Reihe mit wachsender Worker-Zahl bis vier; C++ skaliert deutlich schwächer und der Unterschied zwischen zwei und vier Workern bleibt klein. Die Arbeit ordnet dies als Effekt der nach Beschleunigung des Vergleichskerns relativ stärker ins Gewicht fallenden Lade- und Übergabekosten ein. Bei vier Workern wird der serielle Anteil mit etwa `19,7 %` für Python und `58,9 %` für C++ abgeschätzt. Der schnellere Kern senkt also nicht nur die Gesamtzeit, sondern verschiebt den Engpass: Weitere Worker oder eine noch schnellere Vergleichsfunktion können die seriellen Phasen nicht im gleichen Verhältnis beschleunigen.

Bei zwei Workern ergab sich für die Chunk-Größe folgende aufsummierte Laufzeit der sechs Queries in zwei Wiederholungen:

| Chunk-Größe | Python | C++ |
|---:|---:|---:|
| 1 | 58,39 s | 33,71 s |
| 8 | 48,13 s | 18,58 s |
| 32 | 42,50 s | 18,03 s |
| 128 | 41,14 s | 18,33 s |
| 256 (Standard) | 45,54 s | 18,80 s |
| 1.024 | 51,46 s | 20,25 s |
| 4.096 | 64,26 s | 23,74 s |

Die beste beobachtete Chunk-Größe war `128` für Python und `32` für C++; gegenüber dem Standard `256` waren die Gesamtlaufzeiten um rund `9,7 %` beziehungsweise `4,1 %` niedriger. Sehr kleine Chunks erhöhen den Aufgaben- und Übergabeaufwand, sehr große Chunks können die Lastverteilung verschlechtern. Mit sechs Queries und zwei Wiederholungen sind dies jedoch keine universellen optimalen Einstellungen: Sie hängen vom Backend, der Hardware und der Arbeitslast ab und sollten auf dem Zielsystem kalibriert werden. Die Datenbankgrößenreihe des Experiments wurde abgebrochen; daraus wird keine Skalierungsaussage abgeleitet.

Die detaillierte formale Einordnung, darunter die Schranke für dynamische Blockplanung und ihre Annahmen, steht in [science/gen-db.tex](science/gen-db.tex). Die Rohdaten der Multi-Omics-Messreihe sind in [`search_multiomics_20261008_115430.json`](src/results/search_multiomics_20261008_115430.json) und [`search_multiomics_20261008_115430.txt`](src/results/search_multiomics_20261008_115430.txt) abgelegt.

Die Kandidaten werden nur nach der Knotenzahl (`node_count >= n_Query`) und dem Vorhandensein aller Query-Schichten vorgefiltert. Eine Vorauswahl nach der Kantenzahl gibt es hier bewusst nicht: Mit der Relation des Algorithmus kann ein Graph mit mehr Kanten in einem Graphen mit weniger Kanten enthalten sein (Beispiel in `tests/test_multiomics_python.py::test_edge_count_is_not_monotone`).

Die Datenbank-Tabellen für Multi-Omics stehen in `init-db.sql`; bei einer bestehenden Datenbank genügt es, die beiden neuen `CREATE TABLE`-Anweisungen und den Index auszuführen. Das Web-Frontend nutzt die Multi-Omics-Endpoints noch nicht.

## Universelle Kodierung (Universal Coding)

Die universelle Kodierung stellt eine gemeinsame, schemaabhängige Repräsentation für biologische Strukturen bereit. Der Kern ist nicht auf einfache Graphen oder Multi-Omics beschränkt: Knoten können Merkmale tragen; Relationen können verschiedene Namen, Stelligkeiten und Gewichtsstufen haben. Ein Schema legt diese Eigenschaften und damit die Reihenfolge der Kodierungsschichten fest. Änderungen an dieser Schichtanordnung benötigen eine neue Schema-Version.

### Datenmodell und Kodierung

- Ein `Schema` definiert Knotenmerkmale sowie Relationstypen mit Stelligkeit und Gewichtsstufen.
- Eine `Structure` enthält die Entitäten, ihre Merkmale und die typisierten Relationstupel.
- `SchemaEncoder` kodiert eine Struktur verlustfrei als Stapel von Schichten; jede Spalte repräsentiert entweder eine Entität oder, bei Relationen mit mehr als zwei Argumenten, ein Relationstupel. Die Schichten kodieren Existenz, Merkmale, binäre Relationen, Inzidenzen und Gewichte.
- `decode` rekonstruiert die Struktur und prüft abschließend, dass die Eingabe tatsächlich im Bild der Kodierung liegt (`encode(decode(stapel)) == stapel`). Fehlerhafte oder schemafremde Stapel werden zurückgewiesen.
- Die Koordinatenstrategie gehört zum Schema: `register` vergibt stabile globale Entitätskoordinaten; `local` verwendet die Position innerhalb einer Struktur. Abfragen lesen das Register nur und vergeben für unbekannte Entitäten keine dauerhaft verwendbaren Trefferkoordinaten.

Der strukturunabhängige Vergleich arbeitet auf Mengenfolgen und kennt die Modi `independent` und `coherent`. Im unabhängigen Modus darf jede aktive Schicht ihr passendes Nachbarpaar an einer eigenen Position finden. Im kohärenten Modus müssen die aktiven Schichten dasselbe Positionspaar gemeinsam belegen. Aktive Schichten können explizit per Index oder Name gewählt werden; ohne Auswahl werden standardmäßig die nichtleeren Schichten der Query außer der Existenzschicht verwendet.

### Speicherung und Suche

Die universellen Tabellen in `init-db.sql` ergänzen `biological_networks`:

| Tabelle | Zweck |
|---|---|
| `universal_schemas` | Versionierte Schema-Definitionen |
| `entity_register` | Stabile globale Koordinaten für Entitäten im Register-Modus |
| `universal_structures` | Kodierter Stapel und Entitätsreihenfolge je Netzwerk |
| `universal_components` | Wörterbuch der Mengenkomponenten je Schema und Schicht |
| `universal_pairs` | Invertierter Index zyklischer und linearer Komponentenpaare |

Beim Einfügen erzeugt `crud.create_universal_structure` die Metadaten, den Stapel, die Komponenten und die Paarindexeinträge in einer Transaktion. `crud.search_universal` kodiert die Query und schneidet die passenden Posting-Listen über die aktiven Schichten. Für die Richtung „gespeicherte Struktur enthält Query“ werden zyklische Kandidatenpaare mit linearen Query-Paaren abgeglichen. Der Modus `independent` benötigt danach keinen Einzelvergleich; `coherent` verifiziert die Kandidaten zusätzlich mit der kohärenten Relation. Für diese Relation gibt es absichtlich keinen Ausschlussfilter anhand von Knoten- oder Kantenzahl.

Für reine Mehrschicht-Adjazenzmatrizen gibt es `matrix_schema`, `encode_matrices` und `matrix_search_layers`. Jede Matrixschicht wird dabei als eigener zweistelliger Relationstyp kodiert. Das kann Multi-Omics-Strukturen im universellen Modell abbilden; es ist jedoch nicht mit der bestehenden Multi-Omics-Speicherung in `omics_networks` und `omics_layers` gleichzusetzen.

### Universal-API

Die universelle Kodierung kann über die REST-API verwendet werden:

- `POST /api/universal/schemas` registriert ein versioniertes Schema mit `name`, `version`,
  `coordinates` (`register` oder `local`), `features` und `relations` (jeweils `name`, `arity`,
  `levels`). `GET /api/universal/schemas/{schema_name}?version=...` liest das Schema zurück.
- `POST /api/universal` legt eine Struktur für ein registriertes Schema an. `entities` ist
  entweder eine Liste von Entitätsnamen oder eine Zuordnung von Entitätsnamen zu Merkmalen.
  `relations` ordnet Relationstypen Listen von `{ "entities": [...], "weight": 1 }`-Tupeln zu.
- `GET /api/universal/{network_id}` liefert die dekodierte Struktur einschließlich Merkmalen
  und gewichteten Relationen.
- `POST /api/universal/search` verwendet dieselbe Query-Form wie das Anlegen und unterstützt
  `schema_version`, `mode` (`coherent` oder `independent`), aktive `layers` als Namen oder
  Indizes sowie `include_existence`.

Beispiel für ein Matrixschema mit zwei lokalen Relationsschichten:

```json
{
  "name": "expression-layers",
  "version": 1,
  "coordinates": "local",
  "relations": [
    {"name": "transcriptome", "arity": 2, "levels": 1},
    {"name": "proteome", "arity": 2, "levels": 1}
  ]
}
```

Die API-Endpunkte sind unabhängig von den bestehenden `/api/networks`- und
`/api/multiomics`-Speicherpfaden. Die Datenbank muss zuvor mit den universellen Tabellen aus
`init-db.sql` initialisiert worden sein.

### Aktueller Integrationsstand

Die universelle Kodierung ist auf Kern-, Schema-, CRUD- und HTTP-API-Ebene implementiert und wird durch Universal-Tests geprüft. Die API stellt einen eigenständigen HTTP-Suchweg bereit:

- `/api/networks/search` ruft `crud.search_subgraph` auf und sucht in `network_matrices` mit dem bisherigen Subgraph Algorithmus.
- `/api/multiomics/search` ruft `crud.search_multiomics` auf und sucht in `omics_networks` und `omics_layers` mit dem Multi-Omics-Algorithmus.
- `/api/universal/search` ruft `crud.search_universal` auf und sucht im SQL-Paarindex. Die Universal-API ist noch nicht in das Web-Frontend eingebunden.
- `db-populate.py` erzeugt standardmäßig 1.000.000 klassische Einzelnetzwerke und 1.000 Multi-Omics-Datensätze. Die Befüllung schreibt jeweils sowohl in die bisherigen Tabellen als auch in `universal_structures`, `universal_components` und `universal_pairs`; sie verwendet dafür die versionierten Schemata `gen-db-populated-graph` und `gen-db-populated-multiomics`. Die Universal-Stapel und Paarlisten werden batchweise in derselben Transaktion wie die jeweiligen klassischen Zeilen geschrieben. Das Skript setzt voraus, dass `init-db.sql` einschließlich der universellen Tabellen ausgeführt wurde. Im Repository heißt das Skript `db-populate.py`; eine Datei `db-populate.sql` gibt es nicht.
- Der Populate-Dual-Write erzwingt Universal Coding für diese erzeugten Datensätze, stellt aber keine automatische Migration vorhandener Netzwerke dar. Die normalen HTTP-Erstellungsrouten schreiben weiterhin nur ihre klassischen Tabellen; die Universal-API erstellt unabhängig davon universelle Strukturen.

Der Populate-Pfad schreibt bewusst in beide Repräsentationen, sodass die bestehenden Endpoints ihre bisherigen Daten weiterhin finden. Eine automatische Migration vorhandener Datensätze und die Integration der Universal-Suche in die bestehenden Routen sind nicht Teil dieser API.

### Universal-Experiment: Indexsuche gegen Einzelvergleiche

Das Experiment `src/experiment_search_universal.py` ist der experimentelle Teil des Kapitels „Universelle Kodierung“ (`science/gen-db-universelle-kodierung.tex`, Abschnitt „Vorbereitung des zweiten Schritts“). Bei gleichen Anfragen und gleichen Daten vergleicht es die Suche über den SQL-Paarindex mit Einzelvergleichen in Python und mit der nativen Bibliothek. Aufbau und Auswertung folgen den Experimenten `experiment_search_workers.py`, `experiment_search_backends.py` und `experiment_search_multiomics.py`.

**Verglichene Varianten** (`--backends` wählt aus; Referenz für Speedups ist `python`):

| Variante | Beschreibung |
|---|---|
| `index` | `crud.search_universal`: Suche über den SQL-Paarindex (`universal_pairs`), ohne Prozess-Pool. Im Modus `independent` ist das Ergebnis der Schnitt der Trefferlisten, im Modus `coherent` werden die Kandidaten verifiziert. |
| `python` | Einzelvergleiche mit `universal_core.compare_stacks` (`subgraph_executor.compare_many_universal`, Prozess-Pool): alle gespeicherten Stapel des Schemas mit ausreichender Länge werden geladen und einzeln verglichen, ohne Index. |
| `mo_python` | bisherige Multi-Omics-Pipeline (`crud.search_multiomics`) mit `multiomics_python` (Vorfilter über Schichtnamen und Knotenzahl, Einzelvergleiche im Pool). |
| `cpp` | dieselbe Pipeline mit der nativen Bibliothek (`MultiOmics` aus csubgraph über `CSUBGRAPH_LIB_PATH`). Es wird geprüft, dass kein stiller Fallback auf Python stattfindet. |

**Teilexperimente** (`--only` wählt einzelne aus):

| Teilexperiment | Inhalt |
|---|---|
| `correctness` | Korrektheit ohne Datenbank: `universal_core` gegen `multiomics_python` (und C++) auf Zufallspaaren sowie eingebetteten, identischen und umgekehrten Paaren, beide Modi, auch auf Schichtauswahlen. Invarianten: Symmetrie, kohärent ⇒ unabhängig, Monotonie unter Projektion. Zusätzlich im Speicher: `PairIndex` gegen Einzelvergleiche, auch nach Löschen und erneutem Einfügen. |
| `micro` | Mikro-Benchmark ohne Datenbank: Zeit je Einzelvergleich nach Schichtzahl, Knotenzahl, Modus und Paartyp, dazu die Aufrufkosten. |
| `memory` | Indexsuche im Speicher (`PairIndex`) gegen lineare Suche in Abhängigkeit von der Zahl gespeicherter Stapel; Aufbau- und Anfragezeit, Trefferlast, lineare Anpassung und Skalierungsexponent in N. |
| `search` | Ende-zu-Ende-Suche mit allen Varianten: Anfragengitter (Schichtzahl × Knotenzahl × Typ), Modi, Wiederholungen, Phasen (Laden, Vergleichen, Rest), Kandidaten, Treffer, Speedup mit Konfidenzintervall, Übereinstimmung der Treffer aller Varianten, Trefferquote gegen bekannte Lösungen. |
| `workers` | Skalierung mit 1, 2, 3, … Workern (nur Varianten mit Prozess-Pool). |
| `chunksize` | Einfluss der Chunk-Größe der parallelen Einzelvergleiche. |
| `dbsize` | Skalierung mit der Datenbankgröße, Exponent `t ~ N^b` je Variante, dazu Speicherbedarf und Einfügezeit des Index. |

**Versuchsaufbau**

- Alle Varianten arbeiten auf derselben Datenbasis: ein Matrixschema (`universal_schema.matrix_schema`, lokale Koordinaten) mit `--schema-layers` Schichten (Genom, Transkriptom, Proteom, Metabolom, Epigenom, Lipidom). Jedes Netzwerk wird gleichzeitig als universelle Struktur (`universal_structures`, Wörterbuch, Paarindex) und als Multi-Omics-Netzwerk (`omics_*`) abgelegt.
- Die Daten sind synthetisch (Typ `universal_experiment`): Zufallsnetzwerke `uc_exp_rand_…` (Anzahl `--networks`, deterministisch aus `--seed`) und je eingebetteter Anfrage Netzwerke mit bekannter Lösung `uc_exp_plant_…` (identische Kopie, kohärent eingebettet, nur unabhängig eingebettet). Damit gibt es neben dem Variantenvergleich eine Ground Truth. Andere Netzwerke bleiben unverändert.
- Treffer sind Anfrage ⊆ gespeicherte Struktur (`keep_B`, `equal_keep_A`, `equal_keep_B`). Anfragen haben mindestens vier Knoten.
- Jede Messung wird `--reps` mal wiederholt; die Reihenfolge der Varianten wechselt je Wiederholung, die der Anfragen wird zufällig gemischt; Aufwärmanfragen werden verworfen. Gemessen wird die Wanduhrzeit der gesamten Suche.
- Der API-Server darf während des Experiments nicht laufen. Fremde Multi-Omics-Netzwerke in der Datenbank verlangsamen die Varianten `mo_python` und `cpp` und werden im Bericht als Warnung vermerkt; vorher am besten `python src/experiment_search_multiomics.py --cleanup-only` ausführen.
- Beim Löschen vieler Netzwerke legt das Skript kurzzeitig den Hilfsindex `idx_exp_universal_pairs_network` auf `universal_pairs(network_id)` an und entfernt ihn danach wieder.

**Aufruf** (im Projektordner, damit die `.env` gefunden wird):

```powershell
python src/experiment_search_universal.py                  # vollständig, dauert Stunden
python src/experiment_search_universal.py --quick          # kleiner Vorabtest
python src/experiment_search_universal.py --only correctness micro memory
python src/experiment_search_universal.py --backends index python --networks 5000
python src/experiment_search_universal.py --csubgraph-lib-path C:\...\libsubgraphlib.a
python src/experiment_search_universal.py --cleanup-only   # Experiment-Netzwerke und -Schemata löschen
```

Wichtige Optionen (Standardwerte): `--networks 20000`, `--schema-layers 5`, `--min-nodes 4`, `--max-nodes 40` (höchstens 63), `--workers 2`, `--worker-scaling 1 2 3 4`, `--reps 3`, `--warmup 1`, `--seed 42`, `--query-sizes 4 6 8 12 16 24 32`, `--query-layers 1 2 3 4`, `--plants 3`, `--results-dir src/results`. `--rebuild-data` erzeugt die Experiment-Netzwerke neu, `--cleanup` entfernt sie am Ende (sonst bleiben sie für einen schnellen Neustart in der Datenbank). `python src/experiment_search_universal.py --help` listet alle Optionen.

**Ergebnisse** (`src/results/`, Dateiname mit Zeitstempel):

- `search_universal_<zeit>.json`: Metadaten, Anfragen, alle Einzelmessungen, Auswertung (wird während der Messung regelmäßig gespeichert)
- `search_universal_<zeit>.pdf`: Diagramme auf mehreren Seiten
- `search_universal_<zeit>.txt`: Textbericht
- `search_universal_<zeit>_tabellen.tex`: Tabellen für `gen-db.tex` (`\input{...}`)
- `plot27_universal_…` bis `plot45_universal_…`: Einzeldiagramme für `\includegraphics`

Aus einer vorhandenen JSON-Datei lassen sich PDF, Diagramme, Tabellen und Bericht ohne neuen Messlauf erzeugen:

```powershell
python src/experiment_search_universal.py --plot-from src/results/search_universal_<zeit>.json
```

#### Ergebnisse des gespeicherten Laufs

Der Lauf vom 10. Oktober 2026 verwendete Seed `42`, 20.000 synthetische Zufallsnetzwerke sowie eingebettete Testnetzwerke und fünf benannte Schichten (zusätzlich zur Existenzschicht des kodierten Stapels). Das JSON enthält Messungen unter Windows 11, Python 3.15.0 und PostgreSQL 18.6. Es wurde mit zwei Workern und drei geplanten Wiederholungen konfiguriert.

| Teilmessung | Ergebnis |
|---|---|
| Korrektheit des Vergleichs | 5.000 Paare, verglichen in beiden Modi: 10.000 Übereinstimmungen mit `multiomics_python` und 10.000 mit C++; keine Abweichungen oder Fehler. Zusätzlich 10.000 Projektionsprüfungen ohne Abweichung oder Monotonieverletzung. |
| Korrektheit des `PairIndex` | Auf 150 Strukturen und fünf Schichten wurden 240 Queries und 1.840 Prüfungen ausgeführt; keine Abweichungen bei Suche oder Klassifikation. Der Index enthielt 8.516 Paareinträge. |
| In-Memory-Skalierung | Fünf Größenstufen von 425 bis 5.175 gespeicherten Strukturen (5.000 Zufallsstrukturen plus 175 bekannte Treffer im größten Lauf). Bei 5.175 Strukturen war das Medianverhältnis aus linearer Suche zu Indexsuche über acht Queries `215×` im Modus `independent` und `293×` im Modus `coherent`; die Trefferlisten stimmten jeweils überein. Diese Messung isoliert den In-Memory-Index und schließt Datenbankzugriff und Laden aus. |
| Vorläufiger Ende-zu-Ende-Vergleich | Für alle 56 Queries und beide Modi liegen je eine Messung für `index` und `python` vor. Die Ergebnis-IDs stimmten in allen 112 Query-Modus-Paaren überein. Mittlere Zeit: `index` 0,150 s (`independent`) und 0,226 s (`coherent`); `python` 14,324 s bzw. 15,838 s. Das entspricht in diesem einzelnen Durchlauf etwa `95,5×` bzw. `70,1×`. |

**Wichtige Einschränkung:** Dieser Messlauf ist ausdrücklich unvollständig (`complete=false`). Obwohl drei Wiederholungen konfiguriert waren, enthält der gespeicherte Ende-zu-Ende-Vergleich nur `rep=0` für `index` und `python`. Die Ende-zu-Ende-Messungen für `mo_python` und `cpp` sowie die Teilexperimente `workers`, `chunksize` und `dbsize` wurden nicht abgeschlossen. Beim Eintritt in die Worker-Messung erkannte das Skript `csubgraph` statt des erwarteten `python`-Backends und brach ab. Die Ende-zu-Ende-Zahlen sind deshalb vorläufig und nicht als abgeschlossener Vier-Varianten-Vergleich zu verstehen.

Die Messwerte gelten nur für den genannten synthetischen Versuchsaufbau. Insbesondere ist der In-Memory-Speedup nicht mit dem Ende-zu-Ende-Speedup gleichzusetzen; der SQL-Zugriff, die Kandidatenmenge, Prozesskommunikation und das Ergebnisbauen beeinflussen die tatsächliche Suchzeit. Eine vollständige Wiederholung mit den vorgesehenen Backends, Wiederholungen und Worker-/Chunk-Größen ist erforderlich, bevor belastbare Aussagen über deren Skalierung getroffen werden können.

Der JSON-Rohdatensatz ist [`search_universal_20261010_103804.json`](src/results/search_universal_20261010_103804.json); der Laufbericht ist [`search_universal_20261010_103804.txt`](src/results/search_universal_20261010_103804.txt). Das Skript speichert die Rohdaten auch für unvollständige Läufe, wodurch die tatsächlich beendeten Teilmessungen nachvollziehbar bleiben.

Für die Diagramme wird `matplotlib` benötigt, für die Variante `cpp` eine `libsubgraphlib.a` mit `MultiOmics`. Das Skript ist in `pyproject.toml` unter `omit` eingetragen und zählt nicht zur Testabdeckung.

Die Experimente messen die Suche auf Funktionsebene (`crud.search_universal`). Die HTTP- und Frontend-Suchwege nutzen die universelle Suche weiterhin nicht (siehe [Aktueller Integrationsstand](#aktueller-integrationsstand)); vorrangig bleiben ein durchgängiger Schreib- und Suchpfad über die API sowie Korrektheitstests, die dieselben Strukturen über direkte Universal-CRUD-Aufrufe und die API abgleichen.

## SQL-Struktur

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

## Server starten

Der lokale Server wird mit einem kurzen Uvicorn-Befehl gestartet und anschließend über die Standard-URL erreichbar gemacht:

Befehl:
```bash
python -m uvicorn src.backend.app:app
```

URL:
```bash
http://127.0.0.1:8000
```


Ausgabe:
```bash
(venv) PS C:\Users\Internet\Git\gen-db> python -m uvicorn src.backend.app:app
INFO:     Will watch for changes in these directories: ['C:\\Users\\Internet\\Git\\gen-db']
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [6400] using WatchFiles
2026-10-09 16:40:02 [INFO] Configuration loaded (ENV=development)
INFO:     Started server process [13572]
INFO:     Waiting for application startup.
2026-10-09 16:40:03 [INFO] Starting Gen API - Environment: development
2026-10-09 16:40:03 [INFO] Subgraph algorithm selected: csubgraph (C++)
2026-10-09 16:40:03 [INFO] Multi-omics algorithm selected: csubgraph (C++)
2026-10-09 16:40:03 [INFO] ProcessPoolExecutor ready for Subgraph Executor
INFO:     Application startup complete.
2026-10-09 16:40:15 [INFO] GET / - Serving frontend
INFO:     127.0.0.1:53369 - "GET / HTTP/1.1" 200 OK
2026-10-09 16:40:15 [INFO] GET /api/networks limit=33 random=True
2026-10-09 16:40:15 [INFO] get_all_networks: limit=33 random_sample=True
2026-10-09 16:40:21 [INFO] get_all_networks: Fetched 33 records
2026-10-09 16:40:21 [INFO] GET /api/networks - Returned 33 networks
INFO:     127.0.0.1:53369 - "GET /api/networks?limit=33&random=true HTTP/1.1" 200 OK
INFO:     127.0.0.1:51969 - "GET /favicon.ico HTTP/1.1" 204 No Content
```

## Netzwerke suchen

Die Suche läuft über das Web-Frontend und ermöglicht den Vergleich biologischer Netzwerke über die Subgraph-Suche direkt im Browser.

Ausgabe:
```bash
...
2026-10-09 16:40:36 [INFO] POST /api/networks/search - nodes=15
2026-10-09 16:40:36 [INFO] search_subgraph: Starting search for subgraph with 15 nodes
2026-10-09 16:41:03 [INFO] search_subgraph: 302116 candidates for query (n=15, e=63)
2026-10-09 16:41:03 [INFO] ProcessPoolExecutor initialized with 2 workers
2026-10-09 16:41:19 [INFO] search_subgraph: Found 2 matches
2026-10-09 16:41:20 [INFO] POST /api/networks/search - Found 2 matches
INFO:     127.0.0.1:51974 - "POST /api/networks/search HTTP/1.1" 200 OK
...
```

## Multi-Omics-API

Biologische Prozesse spielen sich selten auf nur einer Ebene ab: Ein Gen wird transkribiert, sein Protein geht Wechselwirkungen ein, Metabolite werden umgesetzt. Die Multi-Omics-API bildet das ab. Ein **Multi-Omics-Netzwerk** besteht aus mehreren **Schichten** (z. B. `transcriptome`, `proteome`, `metabolome`) über **denselben Knoten**. Gesucht wird nicht nur nach der Struktur in einer Schicht, sondern nach einem Muster, das **gleichzeitig in mehreren Schichten** vorkommt.

| | |
|---|---|
| **Basis-URL** | `http://127.0.0.1:8000` |
| **Format** | JSON (`Content-Type: application/json`) |
| **Interaktive Doku** | `/docs` (Swagger UI) und `/redoc`, jeweils unter dem Tag **Multi-Omics** |
| **Endpoints** | 3 (anlegen, lesen, suchen) |
| **Limit** | höchstens **63 Knoten** je Netzwerk, Schichten nur mit `0`/`1` |

> Das Web-Frontend bietet derzeit nur die Suche nach einzelnen Netzwerken. Multi-Omics wird bisher ausschließlich über die REST-API genutzt.

### Konzept

```text
          Knoten (gemeinsam für alle Schichten):  TP53   MDM2   CDKN1A
                                                   0      1      2

 Schicht "transcriptome"        Schicht "proteome"
      0 ──▶ 1                        0 ◀──▶ 1
      0 ──▶ 2
```

- **Knoten** sind für alle Schichten gleich. `node_labels` gibt ihnen Namen, die Reihenfolge entspricht den Zeilen und Spalten jeder Matrix.
- **Jede Schicht** ist eine quadratische Adjazenzmatrix (`n × n`) mit den Werten `0` und `1`. Der Eintrag in Zeile `i`, Spalte `j` beschreibt die Kante zwischen Knoten `i` und `j`.
- **Schichten werden über ihren Namen identifiziert.** Ein Netzwerk darf jeden Namen nur einmal verwenden.
- **Gespeichert** wird in `biological_networks` (Metadaten), `omics_networks` (Knoten-Labels) und `omics_layers` (eine Zeile je Schicht, siehe [SQL-Struktur](#sql-struktur) und `init-db.sql`). `edge_count` ist die Summe über alle Schichten.

### Schnellstart in drei Schritten

Server starten (siehe [Starten](#server-starten)) und dann in PowerShell:

**1. Netzwerk anlegen**

```powershell
$body = @'
{
  "name": "TP53 Multi-Omics",
  "organism": "Human",
  "description": "Transkriptom- und Proteom-Schicht",
  "node_labels": ["TP53", "MDM2", "CDKN1A"],
  "layers": [
    {"layer_name": "transcriptome", "adjacency_matrix": [[0,1,1],[0,0,0],[0,0,0]]},
    {"layer_name": "proteome",      "adjacency_matrix": [[0,1,0],[1,0,0],[0,0,0]]}
  ]
}
'@
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/multiomics `
  -ContentType "application/json" -Body $body
```

**2. Es suchen**

```powershell
$query = @'
{
  "node_labels": ["A", "B"],
  "layers": [
    {"layer_name": "transcriptome", "adjacency_matrix": [[0,1],[0,0]]},
    {"layer_name": "proteome",      "adjacency_matrix": [[0,1],[1,0]]}
  ],
  "mode": "coherent"
}
'@
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/multiomics/search `
  -ContentType "application/json" -Body $query | ConvertTo-Json -Depth 6
```

**3. Ergebnis lesen**

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/multiomics/<network_id> | ConvertTo-Json -Depth 6
```

### Endpoints im Überblick

| Methode | Pfad | Zweck | Erfolg | Fehler |
|---|---|---|---|---|
| `POST` | `/api/multiomics` | Netzwerk mit mehreren Schichten anlegen | `200` | `422`, `500` |
| `GET` | `/api/multiomics/{network_id}` | Netzwerk mit allen Schichten lesen | `200` | `404`, `422`, `500` |
| `POST` | `/api/multiomics/search` | Query-Schichten in allen passenden Netzwerken suchen | `200` | `422`, `500` |

Alle Antworten haben dieselbe Hülle: `{"success": true, "data": ...}`.

### POST /api/multiomics – Netzwerk anlegen

**Request**

| Feld | Typ | Pflicht | Beschreibung |
|---|---|---|---|
| `name` | string (1–255) | ja | Name des Netzwerks |
| `organism` | string | ja | Organismus, z. B. `Human` |
| `node_labels` | string[] | ja | Namen der Knoten, Anzahl = Kantenlänge der Matrizen |
| `layers` | Objekt[] (mind. 1) | ja | Schichten, siehe unten |
| `network_type` | string | nein | Standard: `multi_omics` |
| `description` | string (max. 1000) | nein | Standard: leer |

Jede Schicht in `layers`:

| Feld | Typ | Beschreibung |
|---|---|---|
| `layer_name` | string (1–100) | Eindeutiger Name der Schicht, z. B. `proteome` |
| `adjacency_matrix` | int[][] | Quadratische `n × n`-Matrix mit `0`/`1`; `n` = Anzahl `node_labels` |

**Response** (Beispiel, die ID ist von der Datenbank vergeben)

```json
{
  "success": true,
  "data": {
    "network_id": 1000003,
    "name": "TP53 Multi-Omics",
    "network_type": "multi_omics",
    "organism": "Human",
    "description": "Transkriptom- und Proteom-Schicht",
    "node_count": 3,
    "edge_count": 4,
    "layer_names": ["transcriptome", "proteome"]
  }
}
```

`edge_count` ist die Summe aller Kanten über alle Schichten (hier 2 + 2).

### GET /api/multiomics/{network_id} – Netzwerk lesen

Liefert Metadaten, Knoten-Labels und alle Schichten mit Adjazenzmatrix und Kantenzahl je Schicht. Eine unbekannte ID, auch die eines normalen Netzwerks ohne Schichten, liefert `404`.

```json
{
  "success": true,
  "data": {
    "network_id": 1000003,
    "name": "TP53 Multi-Omics",
    "network_type": "multi_omics",
    "organism": "Human",
    "description": "Transkriptom- und Proteom-Schicht",
    "node_labels": ["TP53", "MDM2", "CDKN1A"],
    "node_count": 3,
    "edge_count": 4,
    "layers": [
      {"layer_name": "transcriptome", "adjacency_matrix": [[0,1,1],[0,0,0],[0,0,0]], "edge_count": 2},
      {"layer_name": "proteome",      "adjacency_matrix": [[0,1,0],[1,0,0],[0,0,0]], "edge_count": 2}
    ],
    "created_at": "2026-10-08T11:54:30"
  }
}
```

### POST /api/multiomics/search – Netzwerke suchen

Gesucht werden alle Netzwerke, in denen das Query-Muster **in jeder** genannten Schicht enthalten ist.

**Request**

| Feld | Typ | Pflicht | Beschreibung |
|---|---|---|---|
| `node_labels` | string[] | ja | Labels der Query-Knoten (Anzahl muss zur Matrixgröße passen) |
| `layers` | Objekt[] (mind. 1) | ja | Query-Schichten (`layer_name`, `adjacency_matrix`) wie beim Anlegen |
| `mode` | `coherent` \| `independent` | nein | Standard: `coherent`, siehe [Suchmodi](#die-zwei-suchmodi-coherent-und-independent) |

**So läuft die Suche ab**

```mermaid
flowchart LR
    Q[Query mit Schichten] --> V[Eingabe prüfen]
    V --> F["Vorfilter in SQL:<br/>alle Schichtnamen vorhanden<br/>node_count ≥ Query-Knoten"]
    F --> P["Parallel vergleichen<br/>(ProcessPool, Worker)"]
    P --> M[Treffer mit match_type]
```

1. Die Eingabe wird validiert (siehe [Fehlerbehandlung](#fehlerbehandlung)).
2. In der Datenbank bleiben nur Netzwerke übrig, die **alle** Schichtnamen der Query besitzen und mindestens so viele Knoten haben. Weitere, nicht abgefragte Schichten des Netzwerks sind erlaubt.
3. Die Kandidaten werden in Chunks auf die Worker-Prozesse verteilt und mit dem Multi-Omics-Algorithmus verglichen (C++ oder Python, siehe [Multi-Omics-Algorithmus](#multi-omics)).
4. Zurück kommen die Treffer, sortiert nach Knotenzahl (aufsteigend), dann nach `network_id`.

Eine Vorauswahl nach der Kantenzahl gibt es bewusst nicht, weil nach der Relation des Algorithmus ein Graph mit mehr Kanten in einem Graphen mit weniger Kanten enthalten sein kann.

**Beispiel**: Das Muster „Kante `0→1` im Transkriptom, Wechselwirkung `0↔1` im Proteom“ wird im oben angelegten Netzwerk gefunden.

```json
{
  "success": true,
  "data": [
    {
      "network_id": 1000003,
      "name": "TP53 Multi-Omics",
      "network_type": "multi_omics",
      "organism": "Human",
      "node_labels": ["TP53", "MDM2", "CDKN1A"],
      "node_count": 3,
      "edge_count": 4,
      "layer_names": ["transcriptome", "proteome"],
      "mode": "coherent",
      "match_type": "subgraph"
    }
  ]
}
```

**Felder eines Treffers**

| Feld | Bedeutung |
|---|---|
| `network_id`, `name`, `network_type`, `organism` | Metadaten des gefundenen Netzwerks |
| `node_labels`, `node_count` | Knoten des gefundenen Netzwerks |
| `edge_count` | Kanten über **alle** Schichten des gefundenen Netzwerks (auch über nicht abgefragte) |
| `layer_names` | Die verglichenen Schichten (die der Query) |
| `mode` | Der verwendete Suchmodus |
| `match_type` | `subgraph`: die Query ist im Netzwerk enthalten. `exact`: Query und Netzwerk sind gleich (gleiche Knotenzahl, gegenseitig enthalten) |

Findet die Suche nichts, kommt `{"success": true, "data": []}`.

### Die zwei Suchmodi: coherent und independent

| Modus | Bedeutung | Wann nutzen? |
|---|---|---|
| `coherent` (Standard) | Alle Query-Schichten müssen **an derselben Position** des Netzwerks übereinstimmen | Das Muster soll wirklich **gemeinsam** auftreten, z. B. dieselben Gene regulieren auf Transkript- **und** Proteinebene |
| `independent` | Jede Schicht darf **an einer eigenen Position** übereinstimmen | Nur wissen, ob jede Schicht für sich das Muster enthält |

`coherent` ist strenger: Jeder kohärente Treffer ist auch ein unabhängiger Treffer, umgekehrt gilt das nicht.

**Beispiel für den Unterschied.** Das Netzwerk „Kaskade“ hat 3 Knoten, im Transkriptom die Kanten `0→1` und `0→2`, im Proteom nur `0→2`:

```json
{
  "name": "Kaskade", "organism": "Human",
  "node_labels": ["A", "B", "C"],
  "layers": [
    {"layer_name": "transcriptome", "adjacency_matrix": [[0,1,1],[0,0,0],[0,0,0]]},
    {"layer_name": "proteome",      "adjacency_matrix": [[0,0,1],[0,0,0],[0,0,0]]}
  ]
}
```

Die Query verlangt in beiden Schichten eine Kante `0→1`:

```json
{
  "node_labels": ["X", "Y"],
  "layers": [
    {"layer_name": "transcriptome", "adjacency_matrix": [[0,1],[0,0]]},
    {"layer_name": "proteome",      "adjacency_matrix": [[0,1],[0,0]]}
  ],
  "mode": "independent"
}
```

- `"mode": "independent"` findet „Kaskade“: Im Transkriptom steckt die Kante an Position `0→1`, im Proteom an Position `0→2`.
- `"mode": "coherent"` findet „Kaskade“ **nicht**: Es gibt keine Position, an der beide Schichten das Muster gleichzeitig zeigen.

### Fehlerbehandlung

Fehler kommen als `{"detail": "..."}` mit passendem Statuscode.

| Status | Ursache | Beispiel für `detail` |
|---|---|---|
| `422` | Inhaltlich ungültige Eingabe | `layer names must be unique` |
| `422` | Matrix nicht quadratisch oder Schichten verschieden groß | `layers: layer 0 must be a square 2x2 matrix` |
| `422` | Matrix enthält andere Werte als `0`/`1` | `layers: layer 0 must contain only 0 and 1` |
| `422` | Mehr als 63 Knoten | `layers has 64 nodes, at most 63 are supported` |
| `422` | Anzahl `node_labels` passt nicht zur Matrixgröße | `number of node labels must equal the size of the adjacency matrices` |
| `422` | Pflichtfeld fehlt, falscher Typ oder ungültiger `mode` | Standardmeldung von FastAPI/Pydantic (Liste mit `loc` und `msg`) |
| `404` | Netzwerk existiert nicht (nur `GET`) | `Multi-omics network not found` |
| `500` | Datenbank- oder Verarbeitungsfehler | Fehlertext, Details im Server-Log |

### Netzwerke löschen

Multi-Omics-Netzwerke stehen auch in `biological_networks` und werden mit dem normalen Endpoint entfernt. `ON DELETE CASCADE` löscht automatisch alle Schichten mit:

```powershell
Invoke-RestMethod -Method Delete http://127.0.0.1:8000/api/networks/<network_id>
```

### Python-Client

```python
import requests

BASE = "http://127.0.0.1:8000"

# 1. Netzwerk anlegen
created = requests.post(f"{BASE}/api/multiomics", json={
    "name": "TP53 Multi-Omics",
    "organism": "Human",
    "node_labels": ["TP53", "MDM2", "CDKN1A"],
    "layers": [
        {"layer_name": "transcriptome", "adjacency_matrix": [[0, 1, 1], [0, 0, 0], [0, 0, 0]]},
        {"layer_name": "proteome",      "adjacency_matrix": [[0, 1, 0], [1, 0, 0], [0, 0, 0]]},
    ],
})
created.raise_for_status()
network_id = created.json()["data"]["network_id"]

# 2. Suchen
result = requests.post(f"{BASE}/api/multiomics/search", json={
    "node_labels": ["A", "B"],
    "layers": [
        {"layer_name": "transcriptome", "adjacency_matrix": [[0, 1], [0, 0]]},
        {"layer_name": "proteome",      "adjacency_matrix": [[0, 1], [1, 0]]},
    ],
    "mode": "coherent",
})
result.raise_for_status()
for match in result.json()["data"]:
    print(match["network_id"], match["name"], match["match_type"])

# 3. Aufräumen
requests.delete(f"{BASE}/api/networks/{network_id}")
```

### Hinweise und Grenzen

- **Struktur statt Namen:** Der Vergleich arbeitet auf den Matrizen. Die `node_labels` der Query werden nur auf die richtige Anzahl geprüft, nicht mit den Labels des Netzwerks abgeglichen.
- **Schichten nach Name:** Die Reihenfolge der Schichten in der Query spielt keine Rolle, aber jeder Query-Schichtname muss im Kandidaten vorkommen.
- **Gleiche Schichtzahl:** Innerhalb einer Query müssen alle Schichten dieselbe Größe `n` haben.
- **Maximal 63 Knoten:** Die Zeilenkomponenten je Schicht werden als `BIGINT[]` gespeichert.
- **Suchdauer:** Sie wächst mit der Zahl der Kandidaten. Mit `CSUBGRAPH_LIB_PATH` läuft der Vergleich in C++ und deutlich schneller als in Python (Messungen siehe [Multi-Omics-Experiment](#multi-omics-experiment)).
- **Bestehende Datenbank:** Die Tabellen `omics_networks` und `omics_layers` samt Index stehen in `init-db.sql` und lassen sich dort nachträglich ausführen.

## Automatisch testen

Die automatisierten Tests laufen gegen eine separate Test-Datenbank, damit die Validierung der Funktionalität ohne Einfluss auf die lokale Entwicklungsumgebung erfolgt.

Den `CSUBGRAPH_LIB_PATH` setzen:
```bash
$env:CSUBGRAPH_LIB_PATH="C:\Users\Internet\Git\csubgraph\build\libsubgraphlib.a"
```

Automatische Tests ausführen:
```bash
pytest
```
Der Coverage-Report wird automatisch generiert nach `doc/coverage/index.html`.

## UML mit Pyreverse

Die Wahrheit steht immer im Code.

```bash
(venv) PS C:\Users\Internet\Git\gen-db> pyreverse -o dot -p gen .\src\backend\
Analysed 13 modules with a total of 15 imports
(venv) PS C:\Users\Internet\Git\gen-db> (Get-Content classes_gen.dot) -replace 'rankdir=LR', 'rankdir=TB' -replace 'charset="utf-8"', 'charset="utf-8"; rankdir=TB; nodesep=0.2; ranksep=0.4;' | Set-Content classes_gen_fixed.dot
(venv) PS C:\Users\Internet\Git\gen-db> dot -Tpdf classes_gen_fixed.dot -o classes_gen_compact.pdf
(venv) PS C:\Users\Internet\Git\gen-db> (Get-Content packages_gen.dot) -replace 'rankdir=LR', 'rankdir=TB' -replace 'charset="utf-8"', 'charset="utf-8"; rankdir=TB; nodesep=0.3; ranksep=0.5;' | Set-Content packages_gen_fixed.dot
(venv) PS C:\Users\Internet\Git\gen-db> dot -Tpdf packages_gen_fixed.dot -o packages_gen_compact.pdf
```

## Erwerb

Der Preis für diese Software beträgt 11.445.000,00 EUR.

### Zahlungsinformationen

Name: Stephan Epp  
IBAN: DE24 5003 1900 0012 5603 20
BIC: BBVADEFFXXX
