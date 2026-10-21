"""
Strukturunabhängiger Kern der universellen Kodierung (Kapitel „Universelle Kodierung“).

Der Kern kennt nur *Stapel von Mengenfolgen*:

- Eine Schicht der Länge m ist eine Folge s = (s_0, ..., s_{m-1}) endlicher Mengen s_j ⊂ N
  (die Komponenten). Ein Stapel M besteht aus L >= 1 Schichten derselben Länge |M| = m.
- Paarmengen: ``P_lin(s)`` (linear benachbarte Paare) und ``P_cyc(s)`` (zyklisch benachbarte
  Paare); für m <= 1 sind beide leer.
- Enthaltensein ``M ⊑ M'``:
  ``independent``: |M| <= |M'| und in *jeder* (aktiven) Schicht ein gemeinsames Paar
  ``P_lin(s) ∩ P_cyc(s') != ∅``;
  ``coherent``: |M| <= |M'| und ein gemeinsames Paar der *Tupelfolgen* über alle (aktiven)
  Schichten.
- Aktive Schichten (Projektion pi_I): Alle Relationen akzeptieren eine Indexmenge ``layers``;
  ``None`` bedeutet alle Schichten.

Die Modi heißen wie in ``multiomics_python`` (``coherent``/``independent``), die Ergebnisnamen
von ``compare_stacks`` sind die der C++-Bibliothek (``KEEP_A`` ... ``EQUAL_KEEP_B``). Dadurch
lässt sich der Kern mit den bestehenden Vergleichen direkt gegenprüfen (siehe
``stack_from_matrices``: Matrixstapel als Spezialfall mit lokalen Koordinaten, ohne die
Einschränkung auf 63 Knoten).

Der Kern ist reines Python ohne Datenbank- und Webabhängigkeiten.
"""

from dataclasses import dataclass
from typing import FrozenSet, Hashable, Iterable, List, Optional, Sequence, Set, Tuple, TypeVar

MODES = ("coherent", "independent")

T = TypeVar("T", bound=Hashable)

Component = FrozenSet[int]
Layer = Tuple[Component, ...]


@dataclass(frozen=True)
class Stack:
    """
    Stapel M = (s^(1), ..., s^(L)) von Schichten gleicher Länge.

    Attributes:
        layers: L Schichten, jede eine Folge von Komponenten (frozenset nichtnegativer Ganzzahlen)

    Raises:
        ValueError: kein Schicht, Schichten verschiedener Länge oder ungültige Komponenten
    """

    layers: Tuple[Layer, ...]

    def __post_init__(self):
        if len(self.layers) == 0:
            raise ValueError("a stack must contain at least one layer")
        length = len(self.layers[0])
        for index, layer in enumerate(self.layers):
            if len(layer) != length:
                raise ValueError(f"layer {index} has length {len(layer)}, expected {length}")
            for component in layer:
                if not isinstance(component, frozenset):
                    raise ValueError(f"layer {index}: components must be frozensets")
                if any(not isinstance(member, int) or member < 0 for member in component):
                    raise ValueError(f"layer {index}: components must contain non-negative integers")

    @classmethod
    def of(cls, layers: Iterable[Iterable[Iterable[int]]]) -> "Stack":
        """Baut einen Stapel aus verschachtelten Listen (Schicht -> Komponente -> Elemente)."""
        return cls(tuple(tuple(frozenset(component) for component in layer) for layer in layers))

    def to_lists(self) -> List[List[List[int]]]:
        """Umkehrung von ``of``: sortierte Elementlisten, geeignet für JSON."""
        return [[sorted(component) for component in layer] for layer in self.layers]

    @property
    def length(self) -> int:
        """Länge |M| (Spaltenzahl)."""
        return len(self.layers[0])

    @property
    def layer_count(self) -> int:
        """Schichtzahl L."""
        return len(self.layers)

    @property
    def occupancy(self) -> int:
        """Belegung nu(M): Summe der Komponentengrößen über alle Schichten."""
        return sum(len(component) for layer in self.layers for component in layer)

    def tuples(self) -> Tuple[Tuple[Component, ...], ...]:
        """Tupelfolge tau(M)_j = (s^(1)_j, ..., s^(L)_j)."""
        return tuple(zip(*self.layers))

    def project(self, layers: Optional[Iterable[int]]) -> "Stack":
        """Projektion pi_I auf die Schichten aus ``layers`` (``None`` = alle)."""
        indices = resolve_layers(self.layer_count, layers)
        return Stack(tuple(self.layers[index] for index in indices))


def resolve_layers(layer_count: int, layers: Optional[Iterable[int]]) -> Tuple[int, ...]:
    """
    Normalisiert eine Menge aktiver Schichten zu einem aufsteigenden Tupel.

    Raises:
        ValueError: leere Menge oder Index außerhalb von 0 .. layer_count-1
    """
    if layers is None:
        return tuple(range(layer_count))
    indices = tuple(sorted(set(layers)))
    if not indices:
        raise ValueError("at least one active layer is required")
    if indices[0] < 0 or indices[-1] >= layer_count:
        raise ValueError(f"layer indices must be in 0..{layer_count - 1}, got {list(indices)}")
    return indices


def linear_pairs(sequence: Sequence[T]) -> Set[Tuple[T, T]]:
    """P_lin(s) = {(s_j, s_{j+1}) : 0 <= j <= m-2}; leer für m <= 1."""
    return {(sequence[j], sequence[j + 1]) for j in range(len(sequence) - 1)}


def cyclic_pairs(sequence: Sequence[T]) -> Set[Tuple[T, T]]:
    """P_cyc(s) = {(s_j, s_{(j+1) mod m})}; leer für m <= 1."""
    m = len(sequence)
    if m < 2:
        return set()
    return {(sequence[j], sequence[(j + 1) % m]) for j in range(m)}


def _require_comparable(a: Stack, b: Stack) -> None:
    if a.layer_count != b.layer_count:
        raise ValueError("stacks must have the same number of layers")


def _require_mode(mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}, expected one of {MODES}")


def contained_independent(a: Stack, b: Stack, layers: Optional[Iterable[int]] = None) -> bool:
    """
    ``A ⊑_ind B`` auf den Schichten ``layers``: |A| <= |B| und je Schicht ein gemeinsames Paar.

    Raises:
        ValueError: verschiedene Schichtzahl oder ungültige Schichtauswahl
    """
    _require_comparable(a, b)
    indices = resolve_layers(a.layer_count, layers)
    if a.length > b.length:
        return False
    return all(
        not linear_pairs(a.layers[index]).isdisjoint(cyclic_pairs(b.layers[index]))
        for index in indices
    )


def contained_coherent(a: Stack, b: Stack, layers: Optional[Iterable[int]] = None) -> bool:
    """
    ``A ⊑_coh B`` auf den Schichten ``layers``: |A| <= |B| und ein gemeinsames Paar der
    Tupelfolgen (alle aktiven Schichten an derselben Position).

    Raises:
        ValueError: verschiedene Schichtzahl oder ungültige Schichtauswahl
    """
    _require_comparable(a, b)
    projected_a, projected_b = a.project(layers), b.project(layers)
    if a.length > b.length:
        return False
    return not linear_pairs(projected_a.tuples()).isdisjoint(cyclic_pairs(projected_b.tuples()))


def contained(a: Stack, b: Stack, mode: str = "coherent",
              layers: Optional[Iterable[int]] = None) -> bool:
    """
    Ist A in B enthalten (``⊑`` im Modus ``mode``)?

    Raises:
        ValueError: unbekannter Modus, verschiedene Schichtzahl oder ungültige Schichtauswahl
    """
    _require_mode(mode)
    if mode == "independent":
        return contained_independent(a, b, layers)
    return contained_coherent(a, b, layers)


def compare_stacks(a: Stack, b: Stack, mode: str = "coherent",
                   layers: Optional[Iterable[int]] = None) -> str:
    """
    Vergleicht zwei Stapel wie ``MultiOmics::compareLayered`` auf den aktiven Schichten.

    Returns:
        ``IDENTICAL`` (projizierte Stapel gleich), ``KEEP_B`` (A in B), ``KEEP_A`` (B in A),
        ``EQUAL_KEEP_A`` / ``EQUAL_KEEP_B`` (gegenseitig enthalten, der Stapel mit der größeren
        Belegung bleibt, bei Gleichstand A) oder ``KEEP_BOTH``

    Raises:
        ValueError: unbekannter Modus, verschiedene Schichtzahl oder ungültige Schichtauswahl
    """
    _require_mode(mode)
    _require_comparable(a, b)
    projected_a, projected_b = a.project(layers), b.project(layers)

    if projected_a == projected_b:
        return "IDENTICAL"

    a_in_b = contained(projected_a, projected_b, mode)
    b_in_a = contained(projected_b, projected_a, mode)

    if a_in_b and not b_in_a:
        return "KEEP_B"
    if b_in_a and not a_in_b:
        return "KEEP_A"
    if a_in_b and b_in_a:
        return "EQUAL_KEEP_A" if projected_a.occupancy >= projected_b.occupancy else "EQUAL_KEEP_B"
    return "KEEP_BOTH"


# ---------------------------------------------------------------------------
# Matrixstapel als Spezialfall (lokale Koordinaten)
# ---------------------------------------------------------------------------

def validate_matrices(matrices: Sequence[Sequence[Sequence[int]]]) -> int:
    """Prüft einen Stapel quadratischer 0/1-Matrizen gleicher Größe und gibt n zurück."""
    if len(matrices) == 0:
        raise ValueError("matrix stack must contain at least one layer")
    n = len(matrices[0])
    if n == 0:
        raise ValueError("matrix stack must not contain empty matrices")
    for index, matrix in enumerate(matrices):
        if len(matrix) != n or any(len(row) != n for row in matrix):
            raise ValueError(f"layer {index} must be a square {n}x{n} matrix")
        if any(value not in (0, 1) for row in matrix for value in row):
            raise ValueError(f"layer {index} must contain only 0 and 1")
    return n


def stack_from_matrices(matrices: Sequence[Sequence[Sequence[int]]]) -> Stack:
    """
    Matrixstapel (A_1, ..., A_L) -> Stapel mit s^(l)_j = {i : A_l[i][j] = 1}.

    Das ist die In-Nachbarschaft des Knotens j; sie entspricht bijektiv dem Bitmuster
    ``sum_i A[i][j] * 2**i`` der Zeilenkomponente aus ``multiomics_python.row_components``,
    hier ohne die Einschränkung n <= 63.

    Raises:
        ValueError: leerer Stapel, nicht quadratische, verschieden große oder nicht binäre Matrizen
    """
    n = validate_matrices(matrices)
    return Stack(tuple(
        tuple(frozenset(i for i in range(n) if matrix[i][j] == 1) for j in range(n))
        for matrix in matrices
    ))


def matrices_from_stack(stack: Stack) -> List[List[List[int]]]:
    """
    Umkehrung von ``stack_from_matrices``.

    Raises:
        ValueError: Länge 0 oder eine Komponente enthält ein Element außerhalb von 0 .. n-1
    """
    n = stack.length
    if n == 0:
        raise ValueError("a stack of length 0 is not a matrix stack")
    result = []
    for layer in stack.layers:
        matrix = [[0] * n for _ in range(n)]
        for j, component in enumerate(layer):
            for i in component:
                if i >= n:
                    raise ValueError(f"component element {i} is outside 0..{n - 1}")
                matrix[i][j] = 1
        result.append(matrix)
    return result
