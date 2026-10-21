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

CREATE TABLE IF NOT EXISTS network_matrices (
    network_id INTEGER PRIMARY KEY REFERENCES biological_networks(network_id) ON DELETE CASCADE,
    node_labels TEXT[] NOT NULL,
    adjacency_matrix INTEGER[][] NOT NULL,
    signature_array BIGINT[] NOT NULL,
    signature_hash VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_networks_type ON biological_networks(network_type);
CREATE INDEX IF NOT EXISTS idx_networks_organism ON biological_networks(organism);
CREATE INDEX IF NOT EXISTS idx_networks_node_count ON biological_networks(node_count);
CREATE INDEX IF NOT EXISTS idx_matrices_hash ON network_matrices(signature_hash);

-- Multi-Omics: mehrere Schichten (z.B. Transkriptom, Proteom, Metabolom) über denselben Knoten.
-- Die Metadaten stehen wie bei jedem Netzwerk in biological_networks (edge_count = Summe über
-- alle Schichten); Löschen in biological_networks entfernt über CASCADE auch diese Tabellen.
CREATE TABLE IF NOT EXISTS omics_networks (
    network_id INTEGER PRIMARY KEY REFERENCES biological_networks(network_id) ON DELETE CASCADE,
    node_labels TEXT[] NOT NULL,
    layer_count INTEGER NOT NULL CHECK (layer_count >= 1),
    signature_hash VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS omics_layers (
    network_id INTEGER NOT NULL REFERENCES omics_networks(network_id) ON DELETE CASCADE,
    layer_index INTEGER NOT NULL,
    layer_name VARCHAR(100) NOT NULL,
    adjacency_matrix INTEGER[][] NOT NULL,
    row_components BIGINT[] NOT NULL,
    edge_count INTEGER NOT NULL,
    PRIMARY KEY (network_id, layer_name),
    UNIQUE (network_id, layer_index)
);

CREATE INDEX IF NOT EXISTS idx_omics_layers_name ON omics_layers(layer_name);

-- Universelle Kodierung: beliebige Strukturen eines Schemas werden als Stapel von Mengenfolgen
-- gespeichert und über einen invertierten Paarindex gesucht (siehe science/gen-db-universelle-kodierung.tex).
-- Die Metadaten stehen wie bei jedem Netzwerk in biological_networks (node_count = Entitäten,
-- edge_count = Summe aller Relationstupel); Löschen dort entfernt über CASCADE auch Stapel und Indexeinträge.

-- Entitätsregister kappa: jede Entität erhält beim ersten Auftreten eine neue, größere Koordinate.
CREATE TABLE IF NOT EXISTS entity_register (
    coordinate BIGSERIAL PRIMARY KEY,
    entity TEXT NOT NULL UNIQUE
);

-- Schemata (Knotenmerkmale, Relationstypen, Koordinatensystem), versioniert.
CREATE TABLE IF NOT EXISTS universal_schemas (
    schema_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    layer_count INTEGER NOT NULL CHECK (layer_count >= 1),
    definition JSONB NOT NULL,
    UNIQUE (name, version)
);

-- Der kodierte Stapel je Struktur: layers = Schichten -> Komponenten -> sortierte Koordinaten;
-- entity_names = Entitäten in Spaltenreihenfolge (für die Rückgewinnung der Struktur).
CREATE TABLE IF NOT EXISTS universal_structures (
    network_id INTEGER PRIMARY KEY REFERENCES biological_networks(network_id) ON DELETE CASCADE,
    schema_id INTEGER NOT NULL REFERENCES universal_schemas(schema_id),
    length INTEGER NOT NULL CHECK (length >= 0),
    entity_names TEXT[] NOT NULL,
    layers JSONB NOT NULL,
    signature_hash VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_universal_structures_schema ON universal_structures(schema_id);

-- Wörterbuch iota_l: jede vorkommende Komponente einer Schicht erhält eine Zahl.
-- members_hash ist der SHA-256 der sortierten Elemente (kurzer, eindeutiger Schlüssel).
CREATE TABLE IF NOT EXISTS universal_components (
    component_id BIGSERIAL PRIMARY KEY,
    schema_id INTEGER NOT NULL REFERENCES universal_schemas(schema_id) ON DELETE CASCADE,
    layer_index INTEGER NOT NULL,
    members_hash VARCHAR(64) NOT NULL,
    members BIGINT[] NOT NULL,
    UNIQUE (schema_id, layer_index, members_hash)
);

-- Paarindex: je Schicht und Art (cyc = zyklisch, lin = linear) zu jedem Komponentenpaar die
-- Netzwerke, in denen es vorkommt, mit der Länge des Stapels. Der Primärschlüssel ist der
-- B-Baum über Schema, Schicht, Art und Paar, über den die Suche liest.
CREATE TABLE IF NOT EXISTS universal_pairs (
    schema_id INTEGER NOT NULL,
    layer_index INTEGER NOT NULL,
    kind CHAR(3) NOT NULL CHECK (kind IN ('cyc', 'lin')),
    first_id BIGINT NOT NULL,
    second_id BIGINT NOT NULL,
    network_id INTEGER NOT NULL REFERENCES biological_networks(network_id) ON DELETE CASCADE,
    length INTEGER NOT NULL,
    PRIMARY KEY (schema_id, layer_index, kind, first_id, second_id, network_id)
);

INSERT INTO biological_networks (name, network_type, organism, description, node_count, edge_count)
VALUES
    ('Glycolysis', 'metabolic', 'Homo sapiens', 'Glucose breakdown pathway', 7, 6),
    ('DNA_Damage_Response', 'protein', 'Homo sapiens', 'p53-centered protein interactions', 5, 6)
ON CONFLICT DO NOTHING;

INSERT INTO network_matrices (network_id, node_labels, adjacency_matrix, signature_array, signature_hash)
VALUES (
    1,
    ARRAY['Glucose', 'G6P', 'F6P', 'FBP', 'DHAP', 'G3P', 'Pyruvate'],
    ARRAY[
        ARRAY[0,1,0,0,0,0,0],
        ARRAY[0,0,1,0,0,0,0],
        ARRAY[0,0,0,1,0,0,0],
        ARRAY[0,0,0,0,1,1,0],
        ARRAY[0,0,0,0,0,1,0],
        ARRAY[0,0,0,0,0,0,1],
        ARRAY[0,0,0,0,0,0,0]
    ]::INTEGER[][],
    ARRAY[1, 130, 260, 392, 528, 672, 768]::BIGINT[],
    'abc123def456'
)
ON CONFLICT DO NOTHING;

INSERT INTO network_matrices (network_id, node_labels, adjacency_matrix, signature_array, signature_hash)
VALUES (
    2,
    ARRAY['p53', 'MDM2', 'ATM', 'DNA-PK', 'CHK2'],
    ARRAY[
        ARRAY[0,1,0,0,0],
        ARRAY[1,0,0,0,0],
        ARRAY[1,0,0,0,1],
        ARRAY[0,0,1,0,0],
        ARRAY[1,0,0,0,0]
    ]::INTEGER[][],
    ARRAY[10, 33, 68, 96, 144]::BIGINT[],
    'xyz789abc012'
)
ON CONFLICT DO NOTHING;