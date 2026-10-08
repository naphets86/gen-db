// C-Schnittstelle um die Multi-Omics-Erweiterung von libsubgraphlib.a (csubgraph),
// damit Python sie per ctypes aufrufen kann. Wird von backend/csubgraph_native.py
// zusammen mit der statischen Bibliothek zu einer gemeinsam genutzten Bibliothek
// (DLL/.so) gelinkt, getrennt vom Wrapper csubgraph_shim.cpp: Enthält eine ältere
// libsubgraphlib.a die Klasse MultiOmics noch nicht, bleibt der Einzelvergleich nutzbar.
//
// Ein Schichtstapel mit L Schichten der Größe n wird als int-Feld der Länge L*n*n
// übergeben; Eintrag (Schicht l, Zeile i, Spalte j) liegt an Position l*n*n + i*n + j.
#include "MultiOmics.h"
#include "SubgraphAlgorithm.h"

#include <cstdio>
#include <exception>
#include <stdexcept>
#include <vector>

#if defined(_WIN32)
#define CSUB_EXPORT extern "C" __declspec(dllexport)
#else
#define CSUB_EXPORT extern "C" __attribute__((visibility("default")))
#endif

static MultiOmics::LayerStack toStack(const int* data, int layers, int n) {
    MultiOmics::LayerStack stack(static_cast<size_t>(layers));
    size_t position = 0;
    for (auto& layer : stack) {
        layer.assign(static_cast<size_t>(n), std::vector<int>(static_cast<size_t>(n)));
        for (auto& row : layer) {
            for (auto& value : row) {
                value = data[position++];
            }
        }
    }
    return stack;
}

static void setError(char* buffer, int size, const char* prefix, const char* message) {
    if (buffer && size > 0) {
        std::snprintf(buffer, static_cast<size_t>(size), "%s%s", prefix, message);
    }
}

// mode: 0 = kohärent, 1 = unabhängig; strategy: 0 = Bigramm (schnell), 1 = dynamische Programmierung.
// Rückgabe: result_code wie in Cli.cpp (0 KEEP_A, 1 KEEP_B, 2 KEEP_BOTH, 3 IDENTICAL,
// 4 EQUAL_KEEP_A, 5 EQUAL_KEEP_B) oder -1 bei Fehler (Text in error_buffer).
CSUB_EXPORT int csub_omics_compare(const int* layers_a, int count_a, int n_a,
                                   const int* layers_b, int count_b, int n_b,
                                   int mode, int strategy,
                                   char* error_buffer, int error_size) {
    try {
        if (!layers_a || !layers_b || count_a <= 0 || count_b <= 0 || n_a <= 0 || n_b <= 0) {
            throw std::invalid_argument("empty layer stack");
        }
        if ((mode != 0 && mode != 1) || (strategy != 0 && strategy != 1)) {
            throw std::invalid_argument("invalid mode or strategy");
        }
        const SubgraphAlgorithm::Result result = MultiOmics::compareLayered(
            toStack(layers_a, count_a, n_a), toStack(layers_b, count_b, n_b),
            mode == 0 ? MultiOmics::Mode::COHERENT : MultiOmics::Mode::INDEPENDENT,
            strategy == 0 ? MultiOmics::Strategy::BIGRAM : MultiOmics::Strategy::DYNAMIC);
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

// Zur Kontrolle der Anbindung (Versionsstand der Multi-Omics-Schnittstelle)
CSUB_EXPORT int csub_omics_abi_version() { return 1; }
