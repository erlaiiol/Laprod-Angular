#import "RubberBandWrapper.h"

// ── Moteur PSOLA maison (Rust) — remplace Rubber Band (GPL-3.0/commercial) ──────────────────
//
// Voir docs/roadmap.md pour le rationale complet. Le pitch-shifter lui-même vit dans le
// workspace Rust à la racine du repo (native/psola-dsp + native/psola-ffi) ; ce fichier n'est
// plus qu'un pont Objective-C++ vers son API C plate (psola_ffi.h — en-tête écrit à la main,
// jamais copié ici, trouvé via HEADER_SEARCH_PATHS pointant directement sur
// native/psola-ffi/include, voir project.pbxproj). Le `.a` statique correspondant est
// recompilé par une phase "Run Script" du target Xcode à chaque build (jamais committé),
// exactement comme le CMake Android invoque `cargo build` à chaque build Gradle.
#include "psola_ffi.h"

#include <atomic>
#include <vector>
#include <algorithm>
#include <cstring>

// ── Lock-free SPSC ring buffer ────────────────────────────────────────────────
//
// INCHANGÉ par rapport à la version Rubber Band — un seul producteur (tap IO thread), un seul
// consommateur (render thread), capacité puissance de 2. Ce pont entre threads temps réel n'a
// aucune raison de changer avec le moteur qu'il alimente.

namespace {

template <size_t kCapacity>
struct SPSCRing {
    static_assert((kCapacity & (kCapacity - 1)) == 0,
                  "SPSCRing capacity must be a power of 2");
    static constexpr size_t kMask = kCapacity - 1;

    size_t write(const float *src, size_t n) noexcept {
        const size_t w     = _w.load(std::memory_order_relaxed);
        const size_t r     = _r.load(std::memory_order_acquire);
        const size_t free_ = kCapacity - (w - r);
        const size_t k     = std::min(n, free_);
        for (size_t i = 0; i < k; ++i) _buf[(w + i) & kMask] = src[i];
        _w.store(w + k, std::memory_order_release);
        return k;
    }

    size_t read(float *dst, size_t n) noexcept {
        const size_t r     = _r.load(std::memory_order_relaxed);
        const size_t w     = _w.load(std::memory_order_acquire);
        const size_t avail = w - r;
        const size_t k     = std::min(n, avail);
        for (size_t i = 0; i < k; ++i) dst[i] = _buf[(r + i) & kMask];
        _r.store(r + k, std::memory_order_release);
        return k;
    }

    size_t available() const noexcept {
        return _w.load(std::memory_order_acquire) -
               _r.load(std::memory_order_acquire);
    }

    void reset() noexcept {
        _r.store(0, std::memory_order_relaxed);
        _w.store(0, std::memory_order_relaxed);
    }

private:
    alignas(64) float               _buf[kCapacity]{};
    alignas(64) std::atomic<size_t> _w{0};
    alignas(64) std::atomic<size_t> _r{0};
};

} // namespace

static const size_t kHistCapacity = 16384;   // puissance de 2 (~340 ms @ 48 kHz)
static const size_t kFadeFrames   = 96;      // ~2 ms : fondu des (re)démarrages / famines

// ── RubberBandWrapper ─────────────────────────────────────────────────────────

@implementation RubberBandWrapper {
    PsolaHandle                *_psola;

    // 8 192 samples ≈ 170 ms @ 48 kHz — accommodates tap/render jitter. Inchangé par rapport à
    // la version Rubber Band.
    SPSCRing<8192>              _ring;

    // Pre-allocated scratch buffer avoids heap allocation in the render thread.
    std::vector<float>          _inBuf;

    // Historique circulaire des derniers échantillons micro, pour la détection de hauteur.
    // Un seul écrivain (thread IO), lecteur sans verrou : une fenêtre lue pendant une écriture
    // peut contenir une discontinuité, sans conséquence pour une estimation de fondamentale.
    float                       _hist[kHistCapacity];
    std::atomic<size_t>         _histW;

    // Coussin anti-craquement : la sortie ne démarre (ou ne redémarre après une famine)
    // qu'avec un cycle d'avance en réserve.
    bool                        _primed;
}


- (instancetype)initWithSampleRate:(double)sampleRate {
    self = [super init];
    if (!self) return nil;

    // Formants toujours activés en production — miroir du comportement historique
    // (OptionFormantPreserved) et du shim Android (jni_shim.c). `psola_create` ne peut
    // retourner NULL qu'en cas de panic Rust intercepté par `catch_unwind` (ne devrait jamais
    // arriver en usage normal, voir psola-ffi/src/lib.rs) — on ne fait PAS échouer
    // l'initialisation ObjC dans ce cas : chaque fonction psola_* est elle-même sûre à appeler
    // avec un handle NULL (revalidé à chaque appel côté Rust, voir ffi_contract.rs), donc un
    // handle NULL dégrade proprement en silence plutôt que de complexifier le contrat
    // `NS_ASSUME_NONNULL` de cet initializer pour un cas qui ne se produit essentiellement
    // jamais.
    _psola = psola_create(sampleRate, 1);

    _inBuf.reserve(8192);
    memset(_hist, 0, sizeof(_hist));
    _histW.store(0, std::memory_order_relaxed);
    _primed = false;

    return self;
}

- (void)dealloc {
    psola_destroy(_psola);
}

// ── Pitch update (any thread) ─────────────────────────────────────────────────

- (void)setPitchCents:(float)cents {
    // Thread-safe côté Rust (AtomicU32 interne, voir PitchTarget::set dans psola-dsp) —
    // appelable directement depuis n'importe quel thread, comme côté Android
    // (jni_shim.c::nativeSetPitchCents). Contrairement à RubberBandStretcher::setPitchScale
    // (non thread-safe, imposait un différé au thread de rendu via un atomic + comparaison
    // locale), plus besoin de cette indirection : elle disparaît avec elle.
    psola_set_pitch_cents(_psola, cents);
}

// ── Feed input (tap IO thread) ────────────────────────────────────────────────

- (void)feedInput:(const float *)input count:(NSInteger)count {
    // Overflows are silently discarded: if the ring is full, the render thread
    // is behind. Oldest unprocessed samples are the least relevant.
    _ring.write(input, static_cast<size_t>(count));

    size_t w = _histW.load(std::memory_order_relaxed);
    for (NSInteger i = 0; i < count; ++i) _hist[(w + static_cast<size_t>(i)) & (kHistCapacity - 1)] = input[i];
    _histW.store(w + static_cast<size_t>(count), std::memory_order_release);
}

// ── Recent input for pitch detection (detection timer thread) ─────────────────

- (BOOL)copyLatestInto:(float *)output count:(NSInteger)count {
    const size_t n = static_cast<size_t>(count);
    const size_t w = _histW.load(std::memory_order_acquire);
    if (count <= 0 || n > kHistCapacity || w < n) return NO;
    const size_t start = w - n;
    for (size_t i = 0; i < n; ++i) output[i] = _hist[(start + i) & (kHistCapacity - 1)];
    return YES;
}

// ── Render (AVAudioSourceNode render block — audio render thread) ─────────────

- (NSInteger)renderInto:(float *)output frameCount:(NSInteger)frameCount {
    // Le moteur maison n'a pas de contrainte de bloc minimal/maximal comme
    // RubberBandStretcher::getSamplesRequired() (voir PsolaShifter::samples_required, qui
    // existe pour compatibilité mais ne borne plus rien de fonctionnel) — on draine simplement
    // tout ce que le ring a de disponible, dans la limite du scratch buffer. Prouvé sûr quel
    // que soit le découpage par `variable_block_size_feeding_is_bit_identical_to_fixed_block_
    // size_feeding` côté Rust (native/psola-dsp/tests/sample_rate_and_latency_sweep.rs).
    size_t ringAvail = _ring.available();
    size_t toRead    = std::min(ringAvail, static_cast<size_t>(8192));
    if (toRead > 0) {
        _inBuf.resize(toRead);
        _ring.read(_inBuf.data(), toRead);
        psola_process(_psola, _inBuf.data(), toRead);
    }

    // psola_retrieve complète déjà de silence si moins de frameCount échantillons sont prêts
    // (voir PsolaShifter::retrieve côté Rust) — pas de memset préalable ni de vérification
    // d'available() à faire nous-mêmes, contrairement à la version Rubber Band.
    //
    // Coussin : psola_retrieve comblerait un manque par du silence EN PLEIN signal — c'est
    // un craquement. On attend donc d'avoir un cycle complet d'avance avant de (re)démarrer
    // la sortie : une famine devient un court silence propre au lieu d'une rafale de clics.
    //
    // Aucune transition n'est franche (20/11/2026) : un démarrage part d'un fondu entrant,
    // une famine se termine par un fondu sortant des derniers échantillons disponibles —
    // jamais un saut du signal à zéro (= clic).
    const int32_t avail = psola_available(_psola);
    const int32_t need  = static_cast<int32_t>(frameCount);
    const size_t  n     = static_cast<size_t>(frameCount);
    if (!_primed) {
        if (avail < need * 2) {
            memset(output, 0, n * sizeof(float));
            return frameCount;
        }
        _primed = true;
        psola_retrieve(_psola, output, n);
        const size_t f = std::min<size_t>(n, kFadeFrames);
        for (size_t i = 0; i < f; ++i) output[i] *= static_cast<float>(i + 1) / static_cast<float>(f + 1);
        return frameCount;
    }
    if (avail < need) {
        _primed = false;
        const size_t k = static_cast<size_t>(std::max<int32_t>(0, avail));
        psola_retrieve(_psola, output, k);
        const size_t f = std::min<size_t>(k, kFadeFrames);
        for (size_t i = 0; i < f; ++i) output[k - f + i] *= static_cast<float>(f - i) / static_cast<float>(f + 1);
        memset(output + k, 0, (n - k) * sizeof(float));
        return frameCount;
    }
    psola_retrieve(_psola, output, n);
    return frameCount;
}

// ── Reset ─────────────────────────────────────────────────────────────────────

- (void)reset {
    _ring.reset();
    psola_reset(_psola);
    _primed = false;
}

// ── Latency ───────────────────────────────────────────────────────────────────

- (NSInteger)latencySamples {
    return static_cast<NSInteger>(psola_get_latency(_psola));
}

@end
