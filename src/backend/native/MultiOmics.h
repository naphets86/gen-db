#ifndef MULTI_OMICS_H
#define MULTI_OMICS_H

#include "SubgraphAlgorithm.h"

#include <cstddef>
#include <cstdint>
#include <vector>

/**
 * @class MultiOmics
 * @brief Mehrschichtige (Multi-Omics-)Erweiterung des Subgraph-Algorithmus
 *
 * Ein Multi-Omics-Netzwerk besteht aus L >= 1 Schichten (Transkriptom, Proteom,
 * Metabolom, ...), die alle über dieselbe, geordnete Knotenmenge der Größe n
 * definiert sind. Jede Schicht ist eine binäre n x n-Adjazenzmatrix. Ein
 * Schichtstapel (LayerStack) ist ein Vektor solcher Matrizen.
 *
 * Die Klasse stellt bereit:
 *  - Integrationsoperatoren (Vereinigung, Schnitt, k-aus-L-Konsens),
 *  - die kohärente und die unabhängige Mehrschicht-Enthaltenseinsrelation,
 *  - zwei Entscheidungsstrategien (dynamische Programmierung wie in
 *    SubgraphAlgorithm und die Bigramm-Charakterisierung in O(n log n)).
 *
 * Beide Strategien liefern nachweislich dieselben Ergebnisse
 * (siehe Kapitel „Multi-Omics-Integration“, Satz zur Bigramm-Charakterisierung).
 */
class MultiOmics {
public:
    using Matrix = std::vector<std::vector<int>>;
    using LayerStack = std::vector<Matrix>;
    using Result = SubgraphAlgorithm::Result;

    /// Größte unterstützte Knotenzahl (Zeilenkomponenten belegen n Bit in uint64_t).
    static constexpr std::size_t kMaxNodes = 63;

    /**
     * @enum Mode
     * @brief Art der Mehrschicht-Relation
     */
    enum class Mode {
        COHERENT,     ///< alle Schichten müssen an derselben Rotation und Position übereinstimmen
        INDEPENDENT   ///< jede Schicht darf eine eigene Rotation/Position verwenden
    };

    /**
     * @enum Strategy
     * @brief Entscheidungsverfahren für die Enthaltenseinsprüfung
     */
    enum class Strategy {
        BIGRAM,   ///< gemeinsames benachbartes Paar (schnell)
        DYNAMIC   ///< n Rotationen mit Longest-Common-Substring (Referenz)
    };

    /// Operator für die Integration der Schichten
    enum class IntegrationOp { UNION, INTERSECTION, CONSENSUS };

    /**
     * @brief Prüft einen Schichtstapel
     * @return true, wenn L >= 1, jede Schicht eine gültige Adjazenzmatrix ist,
     *         alle Schichten dieselbe Größe n haben und n <= kMaxNodes gilt
     */
    static bool isValidLayerStack(const LayerStack& stack);

    /// Elementweises ODER aller Schichten. @throws std::invalid_argument bei ungültigem Stapel
    static Matrix integrateUnion(const LayerStack& stack);

    /// Elementweises UND aller Schichten. @throws std::invalid_argument bei ungültigem Stapel
    static Matrix integrateIntersection(const LayerStack& stack);

    /**
     * @brief Konsens: Eintrag ist 1, wenn mindestens k Schichten die Kante enthalten
     * @throws std::invalid_argument bei ungültigem Stapel oder k == 0 oder k > L
     */
    static Matrix integrateConsensus(const LayerStack& stack, std::size_t k);

    /// Wählt die angegebenen Schichten (in der angegebenen Reihenfolge) aus.
    /// @throws std::invalid_argument bei ungültigem Stapel, leerer Auswahl oder ungültigem Index
    static LayerStack projectLayers(const LayerStack& stack, const std::vector<std::size_t>& indices);

    /// Gesamtzahl der Kanten über alle Schichten. @throws std::invalid_argument bei ungültigem Stapel
    static std::size_t totalEdges(const LayerStack& stack);

    /// Zeilenkomponenten je Schicht: Ergebnis[l][j]. @throws std::invalid_argument bei ungültigem Stapel
    static std::vector<std::vector<uint64_t>> layerRowComponents(const LayerStack& stack);

    /**
     * @brief Ist A (Teilgraph) in B enthalten?  (A ⊑ B)
     *
     * Entspricht der Relation von SubgraphAlgorithm::compareGraphs für L = 1:
     * nB >= nA und es gibt eine Rotation von B, deren Zeilenkomponentenfolge
     * mit der von A eine gemeinsame zusammenhängende Teilfolge der Länge >= 2 besitzt.
     *
     * @throws std::invalid_argument bei ungültigen Stapeln oder ungleicher Schichtzahl
     */
    static bool contains(const LayerStack& a, const LayerStack& b,
                         Mode mode = Mode::COHERENT, Strategy strategy = Strategy::BIGRAM);

    /**
     * @brief Vergleicht zwei Schichtstapel analog zu SubgraphAlgorithm::compareGraphs
     *
     * Für L = 1 stimmt das Ergebnis in beiden Modi und Strategien mit
     * SubgraphAlgorithm::compareGraphs überein. Als Kantenzahl für die Entscheidung
     * bei wechselseitiger Enthaltung dient die Gesamtkantenzahl über alle Schichten.
     *
     * @throws std::invalid_argument bei ungültigen Stapeln oder ungleicher Schichtzahl
     */
    static Result compareLayered(const LayerStack& a, const LayerStack& b,
                                 Mode mode = Mode::COHERENT, Strategy strategy = Strategy::BIGRAM);
};

#endif  // MULTI_OMICS_H
