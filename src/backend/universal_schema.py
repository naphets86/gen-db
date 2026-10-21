"""
Schema, Struktur, Koordinatensysteme und Kodierung Phi (Kapitel „Universelle Kodierung“).

Für eine neue Art biologischer Daten genügt ein neues ``Schema``; der Kern
(``universal_core``) und der Index (``universal_index``) bleiben unverändert.

- ``Schema``: Knotenmerkmale Lambda, geordnete Relationstypen T mit Stelligkeit k_t und
  Gewichtsstufen W_t (W_t = 1: ungewichtet). Die Schichtanordnung ist Teil des Schemas
  (``version``).
- ``Structure``: V mit Merkmalen, Relationen R_t mit Gewichten w_t. Relationen sind Mengen.
- Koordinatensysteme kappa: ``RegisterCoordinates`` (global, Vergabereihenfolge, bestehende
  Koordinaten ändern sich nie), ``LocalCoordinates`` (Rang innerhalb einer Struktur) und
  ``QueryCoordinates`` (Register nur lesend; unbekannte Entitäten erhalten temporäre
  Koordinaten und können dadurch nichts treffen).
- ``SchemaEncoder``: ``encode`` (Definition der Kodierung) und ``decode`` (Satz zur
  Verlustfreiheit). ``decode`` prüft zuletzt ``encode(decode(M)) == M`` und weist damit jeden
  Stapel zurück, der nicht im Bild der Kodierung liegt.

Schichtanordnung eines Schemas (``Schema.layer_labels``):
``ex``, dann ``lab:<a>`` je Merkmal, dann je Relationstyp in der Reihenfolge von T
``bin:<t>:<r>`` (r = 1..W_t) für k_t = 2, sonst ``inz:<t>:<p>`` (p = 1..k_t) und
``wgt:<t>:<r>`` (r = 2..W_t). Die Anzahl ist L_Sigma = 1 + |Lambda| + sum_{k=2} W_t
+ sum_{k!=2} (k_t + W_t - 1).
"""

from dataclasses import dataclass
from functools import cached_property
from typing import (Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Protocol, Sequence,
                    Tuple)

from .universal_core import Stack, resolve_layers, validate_matrices

Entity = str
Row = Tuple[Entity, ...]

COORDINATE_SYSTEMS = ("register", "local")


def _check_name(kind: str, name: Any) -> None:
    if not isinstance(name, str) or not name:
        raise ValueError(f"{kind} must be a non-empty string")
    if ":" in name:
        raise ValueError(f"{kind} {name!r} must not contain ':'")


@dataclass(frozen=True)
class RelationType:
    """
    Relationstyp t mit Stelligkeit k_t >= 1 und Gewichtsstufen W_t >= 1.

    Raises:
        ValueError: ungültiger Name, Stelligkeit oder Stufenzahl
    """

    name: str
    arity: int = 2
    levels: int = 1

    def __post_init__(self):
        _check_name("relation type name", self.name)
        if not isinstance(self.arity, int) or self.arity < 1:
            raise ValueError(f"relation type {self.name!r}: arity must be an integer >= 1")
        if not isinstance(self.levels, int) or self.levels < 1:
            raise ValueError(f"relation type {self.name!r}: levels must be an integer >= 1")


@dataclass(frozen=True)
class Schema:
    """
    Schema Sigma = (Lambda, T, (k_t), (W_t)).

    Attributes:
        name: Schemaname
        relations: Relationstypen in fester Reihenfolge
        features: Knotenmerkmale Lambda (Reihenfolge = Schichtanordnung)
        version: Version der Schichtanordnung (>= 1)
        coordinates: Koordinatensystem der gespeicherten Stapel, ``"register"`` (globales
            Entitätsregister) oder ``"local"`` (Rang in der Struktur). Es gehört zum Schema,
            weil Stapel nur innerhalb desselben Koordinatensystems vergleichbar sind.

    Raises:
        ValueError: ungültige oder doppelte Namen, Version < 1, unbekanntes Koordinatensystem
    """

    name: str
    relations: Tuple[RelationType, ...] = ()
    features: Tuple[str, ...] = ()
    version: int = 1
    coordinates: str = "register"

    def __post_init__(self):
        _check_name("schema name", self.name)
        if self.coordinates not in COORDINATE_SYSTEMS:
            raise ValueError(
                f"unknown coordinate system {self.coordinates!r}, expected one of {COORDINATE_SYSTEMS}"
            )
        if not isinstance(self.version, int) or self.version < 1:
            raise ValueError("schema version must be an integer >= 1")
        for feature in self.features:
            _check_name("feature name", feature)
        if len(set(self.features)) != len(self.features):
            raise ValueError("feature names must be unique")
        names = [relation.name for relation in self.relations]
        if len(set(names)) != len(names):
            raise ValueError("relation type names must be unique")

    @cached_property
    def layout(self) -> Dict[Tuple, int]:
        """Schicht-Index je Schlüssel ``("ex",)``, ``("lab", a)``, ``("bin", t, r)``,
        ``("inz", t, p)``, ``("wgt", t, r)``."""
        keys: List[Tuple] = [("ex",)]
        keys += [("lab", feature) for feature in self.features]
        for relation in self.relations:
            if relation.arity == 2:
                keys += [("bin", relation.name, r) for r in range(1, relation.levels + 1)]
            else:
                keys += [("inz", relation.name, p) for p in range(1, relation.arity + 1)]
                keys += [("wgt", relation.name, r) for r in range(2, relation.levels + 1)]
        return {key: index for index, key in enumerate(keys)}

    @cached_property
    def layer_labels(self) -> Tuple[str, ...]:
        """Lesbare Schichtnamen in der Reihenfolge des Stapels."""
        return tuple(":".join(str(part) for part in key) for key in self.layout)

    @property
    def layer_count(self) -> int:
        """Schichtzahl L_Sigma (hängt nur vom Schema ab)."""
        return len(self.layout)

    def relation(self, name: str) -> RelationType:
        """Relationstyp nach Name (``ValueError`` bei unbekanntem Namen)."""
        for relation in self.relations:
            if relation.name == name:
                return relation
        raise ValueError(f"unknown relation type {name!r}")

    def to_dict(self) -> Dict[str, Any]:
        """JSON-fähige Darstellung (für die Datenbank)."""
        return {
            "name": self.name,
            "version": self.version,
            "coordinates": self.coordinates,
            "features": list(self.features),
            "relations": [
                {"name": r.name, "arity": r.arity, "levels": r.levels} for r in self.relations
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Schema":
        """Umkehrung von ``to_dict`` (``ValueError`` bei unvollständiger Definition)."""
        try:
            return cls(
                name=data["name"],
                version=data["version"],
                coordinates=data.get("coordinates", "register"),
                features=tuple(data["features"]),
                relations=tuple(
                    RelationType(r["name"], r["arity"], r["levels"]) for r in data["relations"]
                ),
            )
        except (KeyError, TypeError) as error:
            raise ValueError(f"invalid schema definition: {error!r}") from error


@dataclass(frozen=True)
class Structure:
    """
    Struktur S = (V, lambda, (R_t), (w_t)) über einem Schema.

    Attributes:
        entities: Entität -> Menge ihrer Merkmale
        relations: Relationstyp -> {Tupel von Entitäten: Gewicht}; jeder Typ des Schemas ist
            vorhanden (gegebenenfalls leer)

    Strukturen werden über ``Structure.build`` erzeugt, das prüft und normalisiert.
    """

    entities: Mapping[Entity, FrozenSet[str]]
    relations: Mapping[str, Mapping[Row, int]]

    @classmethod
    def build(
        cls,
        schema: Schema,
        entities: "Mapping[Entity, Iterable[str]] | Iterable[Entity]",
        relations: Optional[Mapping[str, "Mapping[Sequence[Entity], int] | Iterable[Sequence[Entity]]"]] = None,
    ) -> "Structure":
        """
        Prüft und normalisiert eine Struktur.

        Args:
            schema: Schema der Struktur
            entities: Mapping Entität -> Merkmale oder nur eine Folge von Entitäten
            relations: Relationstyp -> Mapping Tupel -> Gewicht oder Folge von Tupeln
                (Gewicht 1)

        Raises:
            ValueError: unbekannter Relationstyp oder Merkmal, Tupel falscher Stelligkeit,
                Entität außerhalb von V, Gewicht außerhalb von 1..W_t
        """
        if isinstance(entities, Mapping):
            feature_sets = {entity: frozenset(features) for entity, features in entities.items()}
        else:
            feature_sets = {entity: frozenset() for entity in entities}
        known = set(schema.features)
        for entity, features in feature_sets.items():
            if not features <= known:
                raise ValueError(f"entity {entity!r} has unknown features {sorted(features - known)}")

        given = relations or {}
        for name in given:
            schema.relation(name)

        normalized: Dict[str, Dict[Row, int]] = {}
        for relation in schema.relations:
            raw = given.get(relation.name, {})
            items = raw.items() if isinstance(raw, Mapping) else ((row, 1) for row in raw)
            rows: Dict[Row, int] = {}
            for row, weight in items:
                row = tuple(row)
                if len(row) != relation.arity:
                    raise ValueError(
                        f"relation {relation.name!r}: tuple {row} must have {relation.arity} entities"
                    )
                missing = [entity for entity in row if entity not in feature_sets]
                if missing:
                    raise ValueError(f"relation {relation.name!r}: unknown entities {missing}")
                if not isinstance(weight, int) or not 1 <= weight <= relation.levels:
                    raise ValueError(
                        f"relation {relation.name!r}: weight {weight!r} outside 1..{relation.levels}"
                    )
                rows[row] = weight
            normalized[relation.name] = rows
        return cls(entities=feature_sets, relations=normalized)

    @property
    def size(self) -> int:
        """Größe |S| = |V| + sum_t |R_t|."""
        return len(self.entities) + sum(len(rows) for rows in self.relations.values())


# ---------------------------------------------------------------------------
# Koordinatensysteme kappa: Entität -> N (injektiv)
# ---------------------------------------------------------------------------

class Coordinates(Protocol):
    """Injektive Abbildung kappa von Entitäten auf natürliche Zahlen."""

    def __call__(self, entity: Entity) -> int: ...

    def entity(self, coordinate: int) -> Entity: ...


class RegisterCoordinates:
    """
    Globales Entitätsregister: neue Entitäten erhalten stets die nächste, größere Koordinate,
    bestehende Koordinaten ändern sich nie.

    Args:
        assigned: bereits vergebene Koordinaten (z. B. aus der Datenbank geladen)
        frozen: ``True`` = nur lesen; unbekannte Entitäten lösen ``ValueError`` aus

    Raises:
        ValueError: vergebene Koordinaten sind negativ oder nicht injektiv
    """

    def __init__(self, assigned: Optional[Mapping[Entity, int]] = None, frozen: bool = False):
        self._by_entity: Dict[Entity, int] = {}
        self._by_coordinate: Dict[int, Entity] = {}
        self.frozen = frozen
        for entity, coordinate in (assigned or {}).items():
            if not isinstance(coordinate, int) or coordinate < 0:
                raise ValueError(f"coordinate of {entity!r} must be a non-negative integer")
            if coordinate in self._by_coordinate:
                raise ValueError(f"coordinate {coordinate} is assigned twice")
            self._by_entity[entity] = coordinate
            self._by_coordinate[coordinate] = entity

    @property
    def next_coordinate(self) -> int:
        """Die Koordinate, die die nächste neue Entität erhält."""
        return max(self._by_coordinate, default=-1) + 1

    def lookup(self, entity: Entity) -> Optional[int]:
        """Koordinate einer Entität oder ``None``; vergibt nichts."""
        return self._by_entity.get(entity)

    def __call__(self, entity: Entity) -> int:
        coordinate = self._by_entity.get(entity)
        if coordinate is not None:
            return coordinate
        if self.frozen:
            raise ValueError(f"entity {entity!r} is not registered")
        coordinate = self.next_coordinate
        self._by_entity[entity] = coordinate
        self._by_coordinate[coordinate] = entity
        return coordinate

    def entity(self, coordinate: int) -> Entity:
        try:
            return self._by_coordinate[coordinate]
        except KeyError:
            raise ValueError(f"coordinate {coordinate} is not registered") from None

    def __len__(self) -> int:
        return len(self._by_entity)

    def __contains__(self, entity: object) -> bool:
        return entity in self._by_entity

    def items(self) -> List[Tuple[Entity, int]]:
        """Alle Zuordnungen, aufsteigend nach Koordinate."""
        return sorted(self._by_entity.items(), key=lambda item: item[1])


class LocalCoordinates:
    """
    Lokale Koordinaten kappa_S(v) in 0..|V|-1: der Rang einer Entität in der gegebenen
    Reihenfolge (z. B. ``node_labels``). Für reine Mehrschicht-Netzwerke entsteht so genau der
    Matrixstapel der bisherigen Multi-Omics-Relation.

    Raises:
        ValueError: Entitäten in ``order`` nicht eindeutig
    """

    def __init__(self, order: Sequence[Entity]):
        if len(set(order)) != len(order):
            raise ValueError("entities of a local coordinate system must be unique")
        self._order = list(order)
        self._rank = {entity: rank for rank, entity in enumerate(self._order)}

    def __call__(self, entity: Entity) -> int:
        try:
            return self._rank[entity]
        except KeyError:
            raise ValueError(f"entity {entity!r} is not part of the local coordinate system") from None

    def entity(self, coordinate: int) -> Entity:
        if not 0 <= coordinate < len(self._order):
            raise ValueError(f"coordinate {coordinate} is outside 0..{len(self._order) - 1}")
        return self._order[coordinate]


class QueryCoordinates:
    """
    Lesender Zugriff auf ein Register für Anfragen: Bekannte Entitäten erhalten ihre Koordinate,
    unbekannte erhalten temporäre Koordinaten oberhalb des Registers (innerhalb der Anfrage
    eindeutig, nicht gespeichert). Eine solche Komponente kommt in keinem gespeicherten Stapel
    vor und trägt deshalb nichts zur Suche bei.

    Args:
        register: die bekannten Entitäten der Anfrage
        first_free: kleinste Koordinate oberhalb *aller* vergebenen Koordinaten. Ist das Register
            nur ein Ausschnitt eines größeren (z. B. in der Datenbank), muss dies angegeben werden,
            damit eine temporäre Koordinate nie mit der einer fremden Entität zusammenfällt.
    """

    def __init__(self, register: RegisterCoordinates, first_free: Optional[int] = None):
        self._register = register
        self._temporary: Dict[Entity, int] = {}
        self._temporary_reverse: Dict[int, Entity] = {}
        self._next = max(register.next_coordinate, first_free or 0)

    def __call__(self, entity: Entity) -> int:
        known = self._register.lookup(entity)
        if known is not None:
            return known
        if entity not in self._temporary:
            self._temporary[entity] = self._next
            self._temporary_reverse[self._next] = entity
            self._next += 1
        return self._temporary[entity]

    def entity(self, coordinate: int) -> Entity:
        if coordinate in self._temporary_reverse:
            return self._temporary_reverse[coordinate]
        return self._register.entity(coordinate)


# ---------------------------------------------------------------------------
# Kodierung Phi
# ---------------------------------------------------------------------------

class StructureEncoder(Protocol):
    """Schnittstelle je Strukturart: ``schema``, ``encode`` (Phi) und ``decode`` (Umkehrung)."""

    schema: Schema

    def encode(self, structure: Structure) -> Stack: ...

    def decode(self, stack: Stack) -> Structure: ...


class SchemaEncoder:
    """
    Allgemeine Kodierung Phi_{Sigma,kappa} für jedes ``Schema``.

    Spalten: zuerst die Entitätsspalten aufsteigend nach kappa, dann die Relationsknoten der
    Typen mit k_t != 2 in der Reihenfolge von T und innerhalb eines Typs lexikographisch nach
    den kappa-Tupeln. Laufzeit O(|S| log |S|) bei festem Schema.
    """

    def __init__(self, schema: Schema, coordinates: Coordinates):
        self.schema = schema
        self.coordinates = coordinates

    def encode(self, structure: Structure) -> Stack:
        """
        Kodiert eine Struktur verlustfrei als Stapel mit ``schema.layer_count`` Schichten.

        Raises:
            ValueError: Struktur passt nicht zum Schema oder Entität ohne Koordinate
        """
        schema, layout = self.schema, self.schema.layout
        structure = Structure.build(schema, structure.entities, structure.relations)
        kappa = {entity: self.coordinates(entity) for entity in structure.entities}

        entity_order = sorted(structure.entities, key=kappa.__getitem__)
        position = {entity: index for index, entity in enumerate(entity_order)}

        relation_nodes: List[Tuple[RelationType, Row, int]] = []
        for relation in schema.relations:
            if relation.arity != 2:
                rows = sorted(structure.relations[relation.name],
                              key=lambda row: tuple(kappa[entity] for entity in row))
                relation_nodes += [(relation, row, structure.relations[relation.name][row])
                                   for row in rows]

        length = len(entity_order) + len(relation_nodes)
        cells: List[List[set]] = [[set() for _ in range(length)] for _ in range(schema.layer_count)]

        for entity in entity_order:
            column = position[entity]
            cells[layout[("ex",)]][column].add(kappa[entity])
            for feature in structure.entities[entity]:
                cells[layout[("lab", feature)]][column].add(kappa[entity])

        for relation in schema.relations:
            if relation.arity == 2:
                for (source, target), weight in structure.relations[relation.name].items():
                    column = position[target]
                    for level in range(1, weight + 1):
                        cells[layout[("bin", relation.name, level)]][column].add(kappa[source])

        for offset, (relation, row, weight) in enumerate(relation_nodes):
            column = len(entity_order) + offset
            for place, entity in enumerate(row, start=1):
                cells[layout[("inz", relation.name, place)]][column].add(kappa[entity])
            for level in range(2, weight + 1):
                cells[layout[("wgt", relation.name, level)]][column].add(kappa[row[0]])

        return Stack(tuple(tuple(frozenset(cell) for cell in layer) for layer in cells))

    def decode(self, stack: Stack) -> Structure:
        """
        Rekonstruiert die Struktur aus ihrem Stapel (Umkehrung auf dem Bild von ``encode``).

        Raises:
            ValueError: falsche Schichtzahl, unbekannte Koordinaten oder ein Stapel, der nicht
                im Bild der Kodierung liegt
        """
        schema, layout, coordinates = self.schema, self.schema.layout, self.coordinates
        if stack.layer_count != schema.layer_count:
            raise ValueError(
                f"stack has {stack.layer_count} layers, schema {schema.name!r} needs {schema.layer_count}"
            )

        existence = stack.layers[layout[("ex",)]]
        entity_count = sum(1 for component in existence if component)
        if any(len(existence[j]) != 1 for j in range(entity_count)):
            raise ValueError("malformed existence layer")
        names = [coordinates.entity(next(iter(existence[j]))) for j in range(entity_count)]

        entities: Dict[Entity, set] = {name: set() for name in names}
        for feature in schema.features:
            layer = stack.layers[layout[("lab", feature)]]
            for j in range(entity_count):
                if layer[j]:
                    entities[names[j]].add(feature)

        relations: Dict[str, Dict[Row, int]] = {relation.name: {} for relation in schema.relations}
        for relation in schema.relations:
            if relation.arity != 2:
                continue
            for level in range(1, relation.levels + 1):
                layer = stack.layers[layout[("bin", relation.name, level)]]
                for j in range(entity_count):
                    for source in layer[j]:
                        relations[relation.name][(coordinates.entity(source), names[j])] = level

        general = [relation for relation in schema.relations if relation.arity != 2]
        for j in range(entity_count, stack.length):
            owners = [relation for relation in general
                      if stack.layers[layout[("inz", relation.name, 1)]][j]]
            if len(owners) != 1:
                raise ValueError(f"column {j} does not belong to exactly one relation type")
            relation = owners[0]
            members = []
            for place in range(1, relation.arity + 1):
                component = stack.layers[layout[("inz", relation.name, place)]][j]
                if len(component) != 1:
                    raise ValueError(f"column {j}: incidence {place} of {relation.name!r} must be a single entity")
                members.append(coordinates.entity(next(iter(component))))
            weight = max(
                [1] + [level for level in range(2, relation.levels + 1)
                       if stack.layers[layout[("wgt", relation.name, level)]][j]]
            )
            relations[relation.name][tuple(members)] = weight

        structure = Structure.build(schema, entities, relations)
        if self.encode(structure) != stack:
            raise ValueError("stack is not the image of a structure of this schema")
        return structure


# ---------------------------------------------------------------------------
# Aktive Schichten einer Anfrage
# ---------------------------------------------------------------------------

def resolve_active_layers(schema: Schema, stack: Stack,
                          layers: "Optional[Iterable[int | str]]" = None,
                          include_existence: bool = False) -> Tuple[int, ...]:
    """
    Aktive Schichten I einer Anfrage.

    Ohne ``layers`` sind es alle Schichten mit nichtleerem Inhalt (Schichten mit nur leeren
    Komponenten sind per Definition nicht aktiv); die Existenzschicht ist nur mit
    ``include_existence`` aktiv. Explizit können Schichtindizes oder -namen (``layer_labels``)
    gegeben werden.

    Raises:
        ValueError: Stapel passt nicht zum Schema, unbekannte oder leere Schicht, keine aktive
            Schicht
    """
    if stack.layer_count != schema.layer_count:
        raise ValueError(
            f"stack has {stack.layer_count} layers, schema {schema.name!r} needs {schema.layer_count}"
        )
    if layers is None:
        existence = schema.layout[("ex",)]
        active = tuple(index for index, layer in enumerate(stack.layers)
                       if any(layer) and (include_existence or index != existence))
        if not active:
            raise ValueError("the query has no non-empty layer to search with")
        return active

    indices = []
    for layer in layers:
        if isinstance(layer, str):
            if layer not in schema.layer_labels:
                raise ValueError(f"unknown layer {layer!r}, expected one of {list(schema.layer_labels)}")
            layer = schema.layer_labels.index(layer)
        indices.append(layer)
    indices = list(resolve_layers(schema.layer_count, indices))
    empty = [schema.layer_labels[index] for index in indices if not any(stack.layers[index])]
    if empty:
        raise ValueError(f"layers {empty} of the query are empty and cannot be active")
    return tuple(indices)


# ---------------------------------------------------------------------------
# Mehrschicht-Netzwerke (Matrixstapel) als Schema
# ---------------------------------------------------------------------------

def matrix_schema(layer_names: Sequence[str], name: str = "multiomics-matrix",
                  version: int = 1) -> Schema:
    """
    Schema eines reinen Mehrschicht-Netzwerks: je Schicht ein zweistelliger, ungewichteter
    Relationstyp, keine Merkmale (Lambda leer).

    Raises:
        ValueError: doppelte oder ungültige Schichtnamen
    """
    return Schema(name=name, version=version, coordinates="local",
                  relations=tuple(RelationType(layer_name, 2, 1) for layer_name in layer_names))


def matrix_search_layers(schema: Schema) -> Tuple[int, ...]:
    """Schichten eines Matrixschemas, die in der Suche aktiv sind (ohne Existenzschicht)."""
    return tuple(schema.layout[("bin", relation.name, 1)] for relation in schema.relations)


def encode_matrices(schema: Schema, labels: Sequence[Entity],
                    matrices: Sequence[Sequence[Sequence[int]]]) -> Stack:
    """
    Kodiert einen Matrixstapel mit lokalen Koordinaten (Rang in ``labels``). Auf den Schichten
    ``matrix_search_layers(schema)`` ist das Ergebnis genau ``stack_from_matrices(matrices)``.

    Raises:
        ValueError: ungültige Matrizen, Anzahl Labels weicht von der Matrixgröße ab oder die
            Zahl der Matrizen weicht von den Relationstypen des Schemas ab
    """
    n = validate_matrices(matrices)
    if len(labels) != n:
        raise ValueError("number of labels must equal the size of the matrices")
    if len(matrices) != len(schema.relations):
        raise ValueError("number of matrices must equal the number of relation types")
    structure = Structure.build(
        schema,
        labels,
        {
            relation.name: [(labels[i], labels[j]) for i in range(n) for j in range(n)
                            if matrix[i][j] == 1]
            for relation, matrix in zip(schema.relations, matrices)
        },
    )
    return SchemaEncoder(schema, LocalCoordinates(labels)).encode(structure)
