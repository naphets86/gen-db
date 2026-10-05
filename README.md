# gen-db

Biological Network Database mit PostgreSQL-Backend, FastAPI-REST-API und Web-Frontend zur Analyse biologischer Netzwerke mittels Subgraph Algorithmus.

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/Tests-111%20passed-4c1)](tests/)
[![Test Coverage](https://img.shields.io/badge/Test%20Coverage-92%25-brightgreen)](doc/coverage/index.html)
[![scicov](https://img.shields.io/badge/scicov-10-ff69b4)](doc/coverage/index.html)

## Inhaltsverzeichnis

- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Abhängigkeiten](#abhängigkeiten)
- [SQL-Struktur](#sql-strutkur)
- [1.000.000 Netzwerke](#1000000-netzwerke)
- [Starten](#starten)
- [Suche](#suche)
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
INFO:     Started reloader process [6472] using WatchFiles
2026-10-05 11:51:16 [INFO] Configuration loaded (ENV=development)
INFO:     Started server process [13868]
INFO:     Waiting for application startup.
2026-10-05 11:51:16 [INFO] Starting Gen API - Environment: development
2026-10-05 11:51:16 [INFO] ProcessPoolExecutor ready for Subgraph Executor
INFO:     Application startup complete.
2026-10-05 11:51:48 [INFO] GET / - Serving frontend
INFO:     127.0.0.1:59981 - "GET / HTTP/1.1" 200 OK
2026-10-05 11:51:48 [INFO] GET /api/networks limit=33 random=True
2026-10-05 11:51:48 [INFO] get_all_networks: limit=33 random_sample=True
2026-10-05 11:51:52 [INFO] get_all_networks: Fetched 33 records
2026-10-05 11:51:52 [INFO] GET /api/networks - Returned 33 networks
INFO:     127.0.0.1:59981 - "GET /api/networks?limit=33&random=true HTTP/1.1" 200 OK
```

## Suche

Die Suche läuft über das Web-Frontend und ermöglicht den Vergleich biologischer Netzwerke über die Subgraph-Suche direkt im Browser.

Ausgabe:
```bash
(venv) PS C:\Users\Internet\Git\gen-db> python -m uvicorn src.backend.app:app --reload
INFO:     Will watch for changes in these directories: ['C:\\Users\\Internet\\Git\\gen-db']
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [6472] using WatchFiles
2026-10-05 11:51:16 [INFO] Configuration loaded (ENV=development)
INFO:     Started server process [13868]
INFO:     Waiting for application startup.
2026-10-05 11:51:16 [INFO] Starting Gen API - Environment: development
2026-10-05 11:51:16 [INFO] ProcessPoolExecutor ready for Subgraph Executor
INFO:     Application startup complete.
2026-10-05 11:51:48 [INFO] GET / - Serving frontend
INFO:     127.0.0.1:59981 - "GET / HTTP/1.1" 200 OK
2026-10-05 11:51:48 [INFO] GET /api/networks limit=33 random=True
2026-10-05 11:51:48 [INFO] get_all_networks: limit=33 random_sample=True
2026-10-05 11:51:52 [INFO] get_all_networks: Fetched 33 records
2026-10-05 11:51:52 [INFO] GET /api/networks - Returned 33 networks
INFO:     127.0.0.1:59981 - "GET /api/networks?limit=33&random=true HTTP/1.1" 200 OK
2026-10-05 11:52:57 [INFO] GET /api/networks/226554
2026-10-05 11:52:57 [INFO] get_network_by_id: network_id=226554
2026-10-05 11:52:57 [INFO] get_network_by_id: Found network 'metabolic_E._coli_226554'
2026-10-05 11:52:57 [INFO] GET /api/networks/226554 - Found: metabolic_E._coli_226554
INFO:     127.0.0.1:54783 - "GET /api/networks/226554 HTTP/1.1" 200 OK
2026-10-05 11:53:00 [INFO] POST /api/networks/search - nodes=15
2026-10-05 11:53:00 [INFO] search_subgraph: Starting search for subgraph with 15 nodes
2026-10-05 11:53:29 [INFO] search_subgraph: 280310 candidates for query (n=15, e=67)
2026-10-05 11:53:29 [INFO] ProcessPoolExecutor initialized with 2 workers
2026-10-05 11:58:36 [INFO] search_subgraph: Found 2 matches
2026-10-05 11:58:37 [INFO] POST /api/networks/search - Found 2 matches
INFO:     127.0.0.1:54783 - "POST /api/networks/search HTTP/1.1" 200 OK
```

## Testen

Die automatisierten Tests laufen gegen eine separate Test-Datenbank, damit die Validierung der Funktionalität ohne Einfluss auf die lokale Entwicklungsumgebung erfolgt.

```bash
pytest
```
Der Coverage-Report wird automatisch generiert nach `doc/coverage/index.html`.

## Erwerb

Der Preis für diese Software beträgt 2.345.000,00 EUR.

### Zahlungsinformationen

Name: Stephan Epp  
IBAN: DE24 5003 1900 0012 5603 20
BIC: BBVADEFFXXX