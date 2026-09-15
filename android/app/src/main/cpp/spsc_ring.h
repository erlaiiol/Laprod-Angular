// spsc_ring.h — anneau lock-free mono-producteur/mono-consommateur pour float32.
//
// Portage en C portable du même pattern déjà utilisé côté iOS (RubberBandWrapper.mm,
// SPSCRing) — un seul producteur, un seul consommateur, capacité puissance de 2. Sert de pont
// entre le callback d'entrée AAudio (producteur) et le callback de sortie AAudio
// (consommateur), qui tournent sur deux threads temps réel potentiellement différents (voir
// aaudio_engine.c).

#ifndef SPSC_RING_H
#define SPSC_RING_H

#include <stdatomic.h>
#include <stddef.h>
#include <string.h>

typedef struct {
    float *buf;
    size_t capacity; // puissance de 2
    size_t mask;
    _Atomic size_t write_pos;
    _Atomic size_t read_pos;
} SpscRing;

// `storage` doit pointer vers `capacity` floats déjà alloués (pas d'allocation ici — appelé
// une fois à l'init du moteur, jamais dans le chemin chaud). `capacity` doit être une
// puissance de 2.
static inline void spsc_ring_init(SpscRing *ring, float *storage, size_t capacity) {
    ring->buf = storage;
    ring->capacity = capacity;
    ring->mask = capacity - 1;
    atomic_store_explicit(&ring->write_pos, 0, memory_order_relaxed);
    atomic_store_explicit(&ring->read_pos, 0, memory_order_relaxed);
}

static inline void spsc_ring_reset(SpscRing *ring) {
    atomic_store_explicit(&ring->write_pos, 0, memory_order_relaxed);
    atomic_store_explicit(&ring->read_pos, 0, memory_order_relaxed);
}

// Écrit jusqu'à `n` échantillons. Retourne le nombre réellement écrit (< n si l'anneau est
// plein — les échantillons excédentaires sont silencieusement perdus, préférable à bloquer un
// thread audio temps réel). Appelable uniquement depuis le thread producteur.
static inline size_t spsc_ring_write(SpscRing *ring, const float *src, size_t n) {
    size_t w = atomic_load_explicit(&ring->write_pos, memory_order_relaxed);
    size_t r = atomic_load_explicit(&ring->read_pos, memory_order_acquire);
    size_t free_space = ring->capacity - (w - r);
    size_t k = n < free_space ? n : free_space;
    for (size_t i = 0; i < k; i++) {
        ring->buf[(w + i) & ring->mask] = src[i];
    }
    atomic_store_explicit(&ring->write_pos, w + k, memory_order_release);
    return k;
}

// Lit jusqu'à `n` échantillons dans `dst`. Retourne le nombre réellement lu (< n si pas assez
// de données disponibles). Appelable uniquement depuis le thread consommateur.
static inline size_t spsc_ring_read(SpscRing *ring, float *dst, size_t n) {
    size_t r = atomic_load_explicit(&ring->read_pos, memory_order_relaxed);
    size_t w = atomic_load_explicit(&ring->write_pos, memory_order_acquire);
    size_t available = w - r;
    size_t k = n < available ? n : available;
    for (size_t i = 0; i < k; i++) {
        dst[i] = ring->buf[(r + i) & ring->mask];
    }
    atomic_store_explicit(&ring->read_pos, r + k, memory_order_release);
    return k;
}

static inline size_t spsc_ring_available(const SpscRing *ring) {
    size_t w = atomic_load_explicit(&ring->write_pos, memory_order_acquire);
    size_t r = atomic_load_explicit(&ring->read_pos, memory_order_acquire);
    return w - r;
}

#endif // SPSC_RING_H
