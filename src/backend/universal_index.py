"""
Invertierter Paarindex: exakte Suche ohne Einzelvergleiche (Kapitel „Universelle Kodierung“,
Abschnitt „Invertierter Index“).

Zu einer Datenbank D = {(k, M_k)} von Stapeln desselben Schemas:

- ``Interner`` ist das injektive Wörterbuch iota_l je Schicht: jede vorkommende Komponente
  erhält beim ersten Auftreten eine Zahl.
- ``PairIndex`` speichert je Schicht und Art (``cyc`` = zyklische, ``lin`` = lineare Paare)
  zu jedem Zahlenpaar die Liste der Schlüssel; die Länge |M_k| liegt zusätzlich je Eintrag vor.

Suche (Satz „Korrektheit des Index“): ``Match_ind(Q, I)`` ist der Schnitt der Mengen R_l(Q)
über die aktiven Schichten l in I, ``Match_coh`` ist die Verifikation von ``Match_ind`` mit der
kohärenten Relation. Richtung ``contains``: Q ⊑ M_k (gespeicherte Struktur enthält die
Anfrage, Listen ``cyc``); Richtung ``contained``: M_k ⊑ Q (Listen ``lin``, Länge <= m_Q).
Paare mit einer im Wörterbuch unbekannten Komponente tragen nichts bei.

Aufwand der Auswertung (Satz „Laufzeit der Indexsuche“): O(nu_I(Q) + |I| m_Q + H) mit der
Trefferlast H = Summe der gelesenen Listenlängen (``IndexSearch.hit_load``).
"""

from typing import Dict, Hashable, Iterable, List, NamedTuple, Optional, Set, Tuple

from .universal_core import (MODES, Component, Stack, contained_coherent, cyclic_pairs,
                             linear_pairs, resolve_layers)

Key = Hashable
Pair = Tuple[int, int]

DIRECTIONS = ("contains", "contained")


class Interner:
    """Injektives Wörterbuch Komponente -> Zahl (Zahlen werden fortlaufend vergeben)."""

    def __init__(self):
        self._ids: Dict[Component, int] = {}

    def intern(self, component: Component) -> int:
        """Zahl der Komponente; vergibt beim ersten Auftreten die nächste."""
        identifier = self._ids.get(component)
        if identifier is None:
            identifier = self._ids[component] = len(self._ids)
        return identifier

    def get(self, component: Component) -> Optional[int]:
        """Zahl der Komponente oder ``None``, falls sie nicht vorkommt; vergibt nichts."""
        return self._ids.get(component)

    def __len__(self) -> int:
        return len(self._ids)


class IndexSearch(NamedTuple):
    """
    Ergebnis einer Indexsuche.

    Attributes:
        keys: Treffer in Einfügereihenfolge
        hit_load: Trefferlast H (Summe der gelesenen Listenlängen)
        candidates: Größe des Schnitts vor der kohärenten Verifikation
    """

    keys: List[Key]
    hit_load: int
    candidates: int


class PairIndex:
    """
    Paarindex über Stapel mit ``layer_count`` Schichten.

    Raises:
        ValueError: ``layer_count`` < 1
    """

    def __init__(self, layer_count: int):
        if layer_count < 1:
            raise ValueError("layer_count must be at least 1")
        self.layer_count = layer_count
        self._interners = [Interner() for _ in range(layer_count)]
        self._cyclic: List[Dict[Pair, Set[Key]]] = [{} for _ in range(layer_count)]
        self._linear: List[Dict[Pair, Set[Key]]] = [{} for _ in range(layer_count)]
        self._stacks: Dict[Key, Stack] = {}
        self._sequence: Dict[Key, int] = {}
        self._counter = 0

    def __len__(self) -> int:
        return len(self._stacks)

    def __contains__(self, key: object) -> bool:
        return key in self._stacks

    def stack(self, key: Key) -> Stack:
        """Der gespeicherte Stapel (``KeyError`` bei unbekanntem Schlüssel)."""
        return self._stacks[key]

    def entry_count(self) -> int:
        """Anzahl der Listeneinträge (Speicherbedarf des Index, O(sum_k L |M_k|))."""
        return sum(len(keys) for table in (self._cyclic, self._linear)
                   for postings in table for keys in postings.values())

    def interner_sizes(self) -> List[int]:
        """Größe des Wörterbuchs je Schicht."""
        return [len(interner) for interner in self._interners]

    # -- Pflege -----------------------------------------------------------

    def add(self, key: Key, stack: Stack) -> None:
        """
        Fügt einen Stapel ein, Aufwand O(L |M| + nu(M)).

        Raises:
            ValueError: Schlüssel bereits vorhanden oder falsche Schichtzahl
        """
        if key in self._stacks:
            raise ValueError(f"key {key!r} is already indexed")
        if stack.layer_count != self.layer_count:
            raise ValueError(
                f"stack has {stack.layer_count} layers, the index expects {self.layer_count}"
            )
        for layer_index, layer in enumerate(stack.layers):
            interner = self._interners[layer_index]
            identifiers = [interner.intern(component) for component in layer]
            for pair in cyclic_pairs(identifiers):
                self._cyclic[layer_index].setdefault(pair, set()).add(key)
            for pair in linear_pairs(identifiers):
                self._linear[layer_index].setdefault(pair, set()).add(key)
        self._stacks[key] = stack
        self._sequence[key] = self._counter
        self._counter += 1

    def remove(self, key: Key) -> None:
        """
        Entfernt einen Stapel wieder aus allen Listen.

        Raises:
            ValueError: Schlüssel unbekannt
        """
        if key not in self._stacks:
            raise ValueError(f"key {key!r} is not indexed")
        stack = self._stacks.pop(key)
        del self._sequence[key]
        for layer_index, layer in enumerate(stack.layers):
            interner = self._interners[layer_index]
            identifiers = [interner.get(component) for component in layer]
            for table, pairs in ((self._cyclic, cyclic_pairs(identifiers)),
                                 (self._linear, linear_pairs(identifiers))):
                postings = table[layer_index]
                for pair in pairs:
                    postings[pair].discard(key)
                    if not postings[pair]:
                        del postings[pair]

    # -- Suche ------------------------------------------------------------

    def _candidates(self, query: Stack, indices: Tuple[int, ...],
                    direction: str) -> Tuple[Set[Key], int]:
        """Schnitt der Mengen R_l(Q) über die aktiven Schichten und die Trefferlast."""
        forward = direction == "contains"
        tables = self._cyclic if forward else self._linear
        pairs_of = linear_pairs if forward else cyclic_pairs
        m = query.length

        def length_fits(key: Key) -> bool:
            length = self._stacks[key].length
            return length >= m if forward else length <= m

        result: Optional[Set[Key]] = None
        hit_load = 0
        for layer_index in indices:
            interner = self._interners[layer_index]
            identifiers = [interner.get(component) for component in query.layers[layer_index]]
            reached: Set[Key] = set()
            for pair in pairs_of(identifiers):
                if None in pair:
                    continue
                keys = tables[layer_index].get(pair)
                if keys:
                    hit_load += len(keys)
                    reached.update(key for key in keys if length_fits(key))
            result = reached if result is None else result & reached
        return (result if result is not None else set()), hit_load

    def search(self, query: Stack, mode: str = "coherent", layers: Optional[Iterable[int]] = None,
               direction: str = "contains") -> IndexSearch:
        """
        Exakte Suche ohne Einzelvergleiche im Modus ``independent``; im Modus ``coherent``
        werden nur die Kandidaten des unabhängigen Modus verifiziert.

        Args:
            query: Anfrage Q (Stapel mit derselben Schichtzahl wie der Index)
            mode: ``"coherent"`` oder ``"independent"``
            layers: aktive Schichten I (``None`` = alle)
            direction: ``"contains"`` (Q ⊑ M_k) oder ``"contained"`` (M_k ⊑ Q)

        Raises:
            ValueError: unbekannter Modus oder Richtung, falsche Schichtzahl, ungültige Schichten
        """
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}, expected one of {MODES}")
        if direction not in DIRECTIONS:
            raise ValueError(f"unknown direction {direction!r}, expected one of {DIRECTIONS}")
        if query.layer_count != self.layer_count:
            raise ValueError(
                f"query has {query.layer_count} layers, the index expects {self.layer_count}"
            )
        indices = resolve_layers(self.layer_count, layers)

        candidates, hit_load = self._candidates(query, indices, direction)
        keys = sorted(candidates, key=self._sequence.__getitem__)
        candidate_count = len(keys)

        if mode == "coherent":
            if direction == "contains":
                keys = [key for key in keys
                        if contained_coherent(query, self._stacks[key], indices)]
            else:
                keys = [key for key in keys
                        if contained_coherent(self._stacks[key], query, indices)]
        return IndexSearch(keys, hit_load, candidate_count)

    def classify(self, query: Stack, mode: str = "coherent",
                 layers: Optional[Iterable[int]] = None) -> Dict[Key, str]:
        """
        Ergebnisnamen wie ``compare_stacks(query, M_k, mode, layers)`` für alle Schlüssel, zu
        denen eine Enthaltensbeziehung besteht (Treffer in mindestens einer Richtung). Schlüssel
        ohne Beziehung (``KEEP_BOTH``) fehlen. Stapel der Länge < 2 stehen in keiner Paarliste;
        für sie liefert nur ``compare_stacks`` gegebenenfalls ``IDENTICAL``.
        """
        forward = set(self.search(query, mode, layers, "contains").keys)
        backward = set(self.search(query, mode, layers, "contained").keys)
        projected_query = query.project(layers)
        result: Dict[Key, str] = {}
        for key in sorted(forward | backward, key=self._sequence.__getitem__):
            if key in forward and key in backward:
                stored = self._stacks[key].project(layers)
                if stored == projected_query:
                    result[key] = "IDENTICAL"
                elif projected_query.occupancy >= stored.occupancy:
                    result[key] = "EQUAL_KEEP_A"
                else:
                    result[key] = "EQUAL_KEEP_B"
            elif key in forward:
                result[key] = "KEEP_B"
            else:
                result[key] = "KEEP_A"
        return result
