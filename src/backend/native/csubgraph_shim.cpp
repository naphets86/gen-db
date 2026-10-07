// C-Schnittstelle um libsubgraphlib.a (csubgraph), damit Python sie per ctypes aufrufen kann.
// Wird von backend/csubgraph_native.py zusammen mit der statischen Bibliothek zu einer
// gemeinsam genutzten Bibliothek (DLL/.so) gelinkt. Matrizen werden zeilenweise
// (row-major) als int-Feld übergeben.
#include "SubgraphAlgorithm.h"

#include <cstdio>
#include <cstring>
#include <exception>
#include <stdexcept>
#include <vector>

#if defined(_WIN32)
#define CSUB_EXPORT extern "C" __declspec(dllexport)
#else
#define CSUB_EXPORT extern "C" __attribute__((visibility("default")))
#endif

static std::vector<std::vector<int>> toMatrix(const int* data, int n) {
    std::vector<std::vector<int>> matrix(static_cast<size_t>(n));
    for (int i = 0; i < n; ++i) {
        matrix[static_cast<size_t>(i)].assign(data + static_cast<size_t>(i) * n,
                                              data + static_cast<size_t>(i + 1) * n);
    }
    return matrix;
}

static void setError(char* buffer, int size, const char* prefix, const char* message) {
    if (buffer && size > 0) {
        std::snprintf(buffer, static_cast<size_t>(size), "%s%s", prefix, message);
    }
}

// Rückgabe: result_code wie in Cli.cpp (0 KEEP_A, 1 KEEP_B, 2 KEEP_BOTH, 3 IDENTICAL,
// 4 EQUAL_KEEP_A, 5 EQUAL_KEEP_B) oder -1 bei Fehler (Text in error_buffer).
CSUB_EXPORT int csub_compare(const int* graph_a, int n_a, const int* graph_b, int n_b,
                             char* error_buffer, int error_size) {
    try {
        if (!graph_a || !graph_b || n_a <= 0 || n_b <= 0) {
            throw std::invalid_argument("empty matrix");
        }
        const SubgraphAlgorithm::Result result =
            SubgraphAlgorithm::compareGraphs(toMatrix(graph_a, n_a), toMatrix(graph_b, n_b));
        switch (result) {
            case SubgraphAlgorithm::Result::KEEP_A: return 0;
            case SubgraphAlgorithm::Result::KEEP_B: return 1;
            case SubgraphAlgorithm::Result::KEEP_BOTH: return 2;
            case SubgraphAlgorithm::Result::IDENTICAL: return 3;
            case SubgraphAlgorithm::Result::EQUAL_KEEP_A: return 4;
            case SubgraphAlgorithm::Result::EQUAL_KEEP_B: return 5;
        }
        setError(error_buffer, error_size, "Unexpected error: ", "unknown result");
        return -1;
    } catch (const std::invalid_argument& e) {
        setError(error_buffer, error_size, "Validation error: ", e.what());
    } catch (const std::exception& e) {
        setError(error_buffer, error_size, "Unexpected error: ", e.what());
    } catch (...) {
        setError(error_buffer, error_size, "Unexpected error: ", "unknown exception");
    }
    return -1;
}

// Zur Kontrolle der Anbindung (Versionsstand der Shim-Schnittstelle)
CSUB_EXPORT int csub_abi_version() { return 1; }
