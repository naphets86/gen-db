"""
Python-Implementierung der Multi-Omics-Relation (Fallback für csubgraph/MultiOmics).

Ein Multi-Omics-Netzwerk ist ein Schichtstapel: L >= 1 binäre Adjazenzmatrizen (eine je
Schicht, z. B. Transkriptom, Proteom, Metabolom) über derselben, geordneten Knotenmenge
der Größe n. Die Relation entspricht der C++-Klasse ``MultiOmics`` (csubgraph):

- Zeilenkomponente der Spalte j einer Schicht: ``sum_i A[i][j] * 2**i``
  (die Signatur ohne Spaltengewichtung, wie ``SubgraphAlgorithm::extractRowComponents``).
- ``contains(A, B)`` (A ist in B enthalten): ``n_B >= n_A`` und die Zeilenkomponentenfolge
  von A hat mit einer zyklischen Rotation der von B eine gemeinsame zusammenhängende
  Teilfolge der Länge >= 2.
- Das ist gleichwertig zu: Ein benachbartes Paar von A kommt als zyklisch benachbartes
  Paar in B vor (Bigramm-Charakterisierung). Sie wird hier verwendet, weil sie ohne die
  n Rotationen auskommt.
- Modus ``coherent``: Alle Schichten müssen an derselben Position übereinstimmen (die
  Folgenelemente sind die Tupel der Zeilenkomponenten über alle Schichten).
  Modus ``independent``: Jede Schicht darf eine eigene Position verwenden.

Die Ergebnisnamen sind die der C++-Bibliothek (``KEEP_A`` ... ``EQUAL_KEEP_B``), damit
beide Backends dieselbe Abbildung auf die Gen-DB-Werte nutzen.
"""

from typing import List, Sequence, Tuple

Matrix = List[List[int]]
LayerStack = Sequence[Matrix]

MAX_NODES = 63
MODES = ("coherent", "independent")


def validate_layer_stack(stack: LayerStack, name: str = "layer stack") -> None:
    """
    Prüft einen Schichtstapel.

    Raises:
        ValueError: leer, eine Schicht ist nicht quadratisch/binär, Schichten sind verschieden
            groß oder n > 63 (Zeilenkomponenten passen dann nicht mehr in 64 Bit)
    """
    if len(stack) == 0:
        raise ValueError(f"{name} must contain at least one layer")
    n = len(stack[0])
    if n == 0:
        raise ValueError(f"{name} must not contain empty matrices")
    if n > MAX_NODES:
        raise ValueError(f"{name} has {n} nodes, at most {MAX_NODES} are supported")
    for index, layer in enumerate(stack):
        if len(layer) != n or any(len(row) != n for row in layer):
            raise ValueError(f"{name}: layer {index} must be a square {n}x{n} matrix")
        if any(value not in (0, 1) for row in layer for value in row):
            raise ValueError(f"{name}: layer {index} must contain only 0 and 1")


def row_components(matrix: Matrix) -> Tuple[int, ...]:
    """Zeilenkomponenten (Spaltenbitmuster) einer Adjazenzmatrix."""
    n = len(matrix)
    return tuple(sum(matrix[i][j] << i for i in range(n)) for j in range(n))


def total_edges(stack: LayerStack) -> int:
    """Gesamtzahl der Kanten über alle Schichten."""
    return sum(value for layer in stack for row in layer for value in row)


def _sequences(stack: LayerStack, mode: str) -> List[Tuple]:
    """
    Folgen, auf denen die Relation geprüft wird: je Schicht eine Folge von Zahlen
    (``independent``) oder eine einzige Folge von Tupeln über alle Schichten (``coherent``).
    """
    per_layer = [row_components(layer) for layer in stack]
    if mode == "independent":
        return per_layer
    return [tuple(zip(*per_layer))]


def _contains_sequence(a: Sequence, b: Sequence) -> bool:
    """Gemeinsames Paar: linear benachbart in a, zyklisch benachbart in b."""
    if len(b) < len(a) or len(a) < 2:
        return False
    cyclic_pairs = {(b[k], b[(k + 1) % len(b)]) for k in range(len(b))}
    return any((a[i], a[i + 1]) in cyclic_pairs for i in range(len(a) - 1))


def contains(stack_a: LayerStack, stack_b: LayerStack, mode: str = "coherent") -> bool:
    """
    Ist A in B enthalten?

    Raises:
        ValueError: ungültige Stapel, verschiedene Schichtzahl oder unbekannter Modus
    """
    _require_comparable(stack_a, stack_b, mode)
    return all(
        _contains_sequence(seq_a, seq_b)
        for seq_a, seq_b in zip(_sequences(stack_a, mode), _sequences(stack_b, mode))
    )


def compare_layered(stack_a: LayerStack, stack_b: LayerStack, mode: str = "coherent") -> str:
    """
    Vergleicht zwei Schichtstapel wie ``MultiOmics::compareLayered``.

    Returns:
        ``IDENTICAL``, ``KEEP_A`` (B in A), ``KEEP_B`` (A in B), ``KEEP_BOTH``,
        ``EQUAL_KEEP_A`` oder ``EQUAL_KEEP_B``

    Raises:
        ValueError: ungültige Stapel, verschiedene Schichtzahl oder unbekannter Modus
    """
    _require_comparable(stack_a, stack_b, mode)

    rows_a = [row_components(layer) for layer in stack_a]
    rows_b = [row_components(layer) for layer in stack_b]
    if len(stack_a[0]) == len(stack_b[0]) and rows_a == rows_b:
        return "IDENTICAL"

    a_in_b = contains(stack_a, stack_b, mode)
    b_in_a = contains(stack_b, stack_a, mode)

    if a_in_b and not b_in_a:
        return "KEEP_B"
    if b_in_a and not a_in_b:
        return "KEEP_A"
    if a_in_b and b_in_a:
        # Wechselseitige Enthaltung setzt n_A <= n_B und n_B <= n_A voraus, also n_A == n_B.
        return "EQUAL_KEEP_A" if total_edges(stack_a) >= total_edges(stack_b) else "EQUAL_KEEP_B"
    return "KEEP_BOTH"


def _require_comparable(stack_a: LayerStack, stack_b: LayerStack, mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}, expected one of {MODES}")
    validate_layer_stack(stack_a, "Stack A")
    validate_layer_stack(stack_b, "Stack B")
    if len(stack_a) != len(stack_b):
        raise ValueError("Layer stacks must have the same number of layers")
