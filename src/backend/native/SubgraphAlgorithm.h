#ifndef SUBGRAPH_ALGORITHM_H
#define SUBGRAPH_ALGORITHM_H

#include <vector>
#include <cstdint>
#include <string>
#include <algorithm>
#include <numeric>

/**
 * @class SubgraphAlgorithm
 * @brief Implementiert den Subgraph-Vergleichsalgorithmus nach Epp (2026)
 * 
 * Der Algorithmus vergleicht zwei Graphen mittels Adjazenzmatrizen und eindeutigen
 * Signaturen, bestimmt Subgraph-Beziehungen durch zyklische Rotation und LCS-Analyse.
 */
class SubgraphAlgorithm {
public:
    /**
     * @enum Result
     * @brief Ergebnis des Subgraph-Vergleichs
     */
    enum class Result {
        KEEP_A,         ///< Graph A ist Subgraph von B oder identisch → behalte A
        KEEP_B,         ///< Graph B ist Subgraph von A oder identisch → behalte B
        KEEP_BOTH,      ///< Keine Subgraph-Beziehung → behalte beide
        IDENTICAL,      ///< Graphen sind identisch → beide gleichwertig
        EQUAL_KEEP_A,   ///< Wechselseitig enthalten; behalte A
        EQUAL_KEEP_B    ///< Wechselseitig enthalten; behalte B
    };

    /**
     * @brief Berechnet Signaturen für eine Adjazenzmatrix
     * 
     * σ_j = Σ(i=0 bis n-1) A_ij * 2^i + j * 2^n
     * 
     * @param matrix Adjazenzmatrix (n × n)
     * @return Vektor von Signaturen der Länge n
     */
    static std::vector<uint64_t> calculateSignatures(const std::vector<std::vector<int>>& matrix);

    /**
     * @brief Berechnet die längste gemeinsame Teilsequenz (LCS)
     * 
     * Nutzt dynamische Programmierung für zwei Signatur-Arrays
     * 
     * @param seqA Erste Signatur-Sequenz
     * @param seqB Zweite Signatur-Sequenz
     * @return Länge der LCS
     */
    static size_t computeLCS(const std::vector<uint64_t>& seqA, const std::vector<uint64_t>& seqB);

    /**
     * @brief Erzeugt eine zyklisch rotierte Version eines Arrays
     * 
     * @param seq Original-Sequenz
     * @param rotation Anzahl der Rotationen nach rechts
     * @return Rotierte Sequenz
     */
    static std::vector<uint64_t> rotateSequence(const std::vector<uint64_t>& seq, size_t rotation);

    /**
     * @brief Extrahiert die Zeilenkomponenten aus Signaturen (ohne Spaltengewichtung)
     * 
     * @param signatures Signatur-Array
     * @param n Dimensionalität (Anzahl der Knoten)
     * @return Vektor von Zeilenkomponenten
     */
    static std::vector<uint64_t> extractRowComponents(const std::vector<uint64_t>& signatures, size_t n);

    /**
     * @brief Vergleicht zwei Graphen und bestimmt ihre Subgraph-Beziehung
     * 
     * Implementiert die vollständige Algorithmus-Logik:
     * 1. Berechne Signaturen für beide Graphen
     * 2. Prüfe alle n zyklischen Rotationen
     * 3. Berechne LCS für jede Rotation
     * 4. Bestimme Subgraph-Beziehung (LCS >= 2)
     * 
     * @param graphA Adjazenzmatrix des ersten Graphen (n × n)
     * @param graphB Adjazenzmatrix des zweiten Graphen (m × m)
     * @return Result-Enum mit Empfehlung zum Behalten der Graphen
     * @throws std::invalid_argument wenn Matrizen ungültig oder leer sind
     */
    static Result compareGraphs(
        const std::vector<std::vector<int>>& graphA,
        const std::vector<std::vector<int>>& graphB
    );

    /**
     * @brief Validiert eine Adjazenzmatrix
     * 
     * @param matrix Zu validierende Matrix
     * @param name Name der Matrix (für Fehlermeldungen)
     * @return true wenn Matrix gültig, sonst false
     */
    static bool isValidAdjacencyMatrix(const std::vector<std::vector<int>>& matrix);

    /**
     * @brief Gibt das Ergebnis als String aus
     * 
     * @param result Result-Enum
     * @return Beschreibung des Ergebnisses
     */
    static std::string resultToString(Result result);
};

#endif  // SUBGRAPH_ALGORITHM_H