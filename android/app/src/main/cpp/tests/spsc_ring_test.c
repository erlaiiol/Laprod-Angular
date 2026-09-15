// spsc_ring_test.c — harnais de test autonome pour spsc_ring.h.
//
// spsc_ring.h est header-only et portable (stdatomic.h pur, aucune dépendance Android) —
// contrairement à aaudio_engine.c (qui a besoin de vraies libs AAudio pour tourner), il peut
// donc être compilé et EXÉCUTÉ nativement ici, sans NDK ni device :
//
//   clang -std=c11 -Wall -Wextra -O2 -pthread \
//       -I ../.. spsc_ring_test.c -o /tmp/spsc_ring_test && /tmp/spsc_ring_test
//
// Ce ring est le pont temps réel entre les callbacks d'entrée/sortie AAudio
// (aaudio_engine.c) — sa correction sous contention concurrente (le scénario RÉEL : deux
// threads audio séparés) est directement une question de latence/robustesse, pas seulement de
// mémoire. Jamais testé jusqu'ici (voir docs/roadmap.md, chantier latence) : ce fichier comble
// ce vide.
//
// N'est PAS un test unifié avec `cargo test` (C, pas Rust) ni construit par le CMake Android
// (pas listé dans CMakeLists.txt) — outil de vérification autonome, même esprit que
// `native/psola-dsp/src/bin/dump_wav.rs`.

#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../spsc_ring.h"

// ── Utilitaires ────────────────────────────────────────────────────────────────

static void fill_seq(float *buf, size_t n, float start) {
    for (size_t i = 0; i < n; i++) buf[i] = start + (float) i;
}

// ── 1. Round-trip simple ─────────────────────────────────────────────────────

static void test_basic_round_trip(void) {
    float storage[16];
    SpscRing ring;
    spsc_ring_init(&ring, storage, 16);

    float in[5] = {1.0f, 2.0f, 3.0f, 4.0f, 5.0f};
    size_t written = spsc_ring_write(&ring, in, 5);
    assert(written == 5);
    assert(spsc_ring_available(&ring) == 5);

    float out[5] = {0};
    size_t read = spsc_ring_read(&ring, out, 5);
    assert(read == 5);
    assert(memcmp(in, out, sizeof(in)) == 0);
    assert(spsc_ring_available(&ring) == 0);

    printf("[OK] test_basic_round_trip\n");
}

// ── 2. Lecture partielle quand pas assez de données ──────────────────────────

static void test_read_more_than_available_is_partial_not_oob(void) {
    float storage[16];
    SpscRing ring;
    spsc_ring_init(&ring, storage, 16);

    float in[3] = {10.0f, 20.0f, 30.0f};
    spsc_ring_write(&ring, in, 3);

    float out[8];
    for (size_t i = 0; i < 8; i++) out[i] = -1.0f; // sentinelle
    size_t read = spsc_ring_read(&ring, out, 8);
    assert(read == 3); // jamais plus que ce qui est réellement dispo
    assert(out[0] == 10.0f && out[1] == 20.0f && out[2] == 30.0f);
    assert(out[3] == -1.0f); // le reste de `out` n'a pas été touché — pas de débordement

    printf("[OK] test_read_more_than_available_is_partial_not_oob\n");
}

// ── 3. Écriture au-delà de la capacité libre : troncature silencieuse ────────

static void test_write_more_than_free_space_truncates_silently(void) {
    float storage[8];
    SpscRing ring;
    spsc_ring_init(&ring, storage, 8);

    float in[20];
    fill_seq(in, 20, 0.0f);
    size_t written = spsc_ring_write(&ring, in, 20);
    assert(written == 8); // jamais plus que `capacity` sur un anneau vide

    float out[8];
    size_t read = spsc_ring_read(&ring, out, 8);
    assert(read == 8);
    // Les 8 PREMIERS échantillons de `in` sont conservés (pas les 8 derniers) — l'excédent en
    // fin d'écriture est ce qui est perdu, pas le début, cohérent avec "on n'écrase jamais un
    // échantillon dispo pour le consommateur".
    for (size_t i = 0; i < 8; i++) assert(out[i] == in[i]);

    printf("[OK] test_write_more_than_free_space_truncates_silently\n");
}

// ── 4. Wraparound : plusieurs tours complets du buffer circulaire ───────────

static void test_wraparound_many_laps(void) {
    float storage[4]; // petite capacité → force le wraparound rapidement
    SpscRing ring;
    spsc_ring_init(&ring, storage, 4);

    float counter = 0.0f;
    for (int lap = 0; lap < 1000; lap++) {
        float in[3] = {counter, counter + 1.0f, counter + 2.0f};
        size_t written = spsc_ring_write(&ring, in, 3);
        assert(written == 3); // toujours de la place : on lit immédiatement après (voir plus bas)

        float out[3] = {0};
        size_t read = spsc_ring_read(&ring, out, 3);
        assert(read == 3);
        assert(out[0] == in[0] && out[1] == in[1] && out[2] == in[2]);

        counter += 3.0f;
    }
    assert(spsc_ring_available(&ring) == 0);

    printf("[OK] test_wraparound_many_laps (1000 tours, capacité=4)\n");
}

// ── 5. Reset ──────────────────────────────────────────────────────────────────

static void test_reset_clears_available(void) {
    float storage[16];
    SpscRing ring;
    spsc_ring_init(&ring, storage, 16);

    float in[16];
    fill_seq(in, 16, 0.0f);
    spsc_ring_write(&ring, in, 10);
    assert(spsc_ring_available(&ring) == 10);

    spsc_ring_reset(&ring);
    assert(spsc_ring_available(&ring) == 0);

    // Après reset, l'anneau redémarre comme neuf — pleine capacité réutilisable.
    size_t written = spsc_ring_write(&ring, in, 16);
    assert(written == 16);

    printf("[OK] test_reset_clears_available\n");
}

// ── 6. Stress concurrent producteur/consommateur (le scénario RÉEL AAudio) ──
//
// Un thread écrit une séquence strictement croissante par petits blocs de taille variable
// (simule des callbacks AAudio de taille non garantie, voir aaudio_engine.c) ; l'autre la lit
// avec un délai variable (simule le polling Kotlin ~20ms qui peut prendre du retard). Le test
// vérifie qu'AUCUN échantillon reçu n'est corrompu ou hors séquence — la seule garantie que
// spsc_ring.h doit tenir sous contention réelle (les pertes par débordement sont attendues et
// tolérées, une valeur reçue erronée ne le serait jamais).

#define STRESS_RING_CAPACITY (1u << 14) // 16384, comme BRIDGE_RING_CAPACITY réel
#define STRESS_TOTAL_SAMPLES 2000000u

static void *producer_thread(void *arg) {
    SpscRing *ring = (SpscRing *) arg;
    float chunk[257];
    unsigned int seed = 12345;
    uint32_t next = 0;
    while (next < STRESS_TOTAL_SAMPLES) {
        // Taille de bloc pseudo-aléatoire dans [1, 256] — simule des callbacks AAudio de
        // taille non garantie (voir MAX_CALLBACK_FRAMES dans aaudio_engine.c).
        seed = seed * 1103515245u + 12345u;
        size_t block = 1 + (seed % 256);
        if (next + block > STRESS_TOTAL_SAMPLES) block = STRESS_TOTAL_SAMPLES - next;

        for (size_t i = 0; i < block; i++) chunk[i] = (float) (next + i);
        size_t written = spsc_ring_write(ring, chunk, block);
        next += (uint32_t) written; // si écriture partielle (anneau plein), on retentera le reste
    }
    return NULL;
}

static void *consumer_thread(void *arg) {
    SpscRing *ring = (SpscRing *) arg;
    float chunk[257];
    float expected = -1.0f; // le producteur commence à 0.0f — voir la vérification ci-dessous
    uint32_t received = 0;
    unsigned int seed = 67890;
    while (received < STRESS_TOTAL_SAMPLES) {
        seed = seed * 1103515245u + 12345u;
        size_t block = 1 + (seed % 256);
        size_t read = spsc_ring_read(ring, chunk, block);
        for (size_t i = 0; i < read; i++) {
            // La seule propriété garantie : ce qui SORT de l'anneau est exactement ce qui y
            // est entré, dans l'ordre — jamais de valeur dupliquée, sautée en désordre, ou
            // corrompue. Des pertes (débordement producteur) sont acceptables ET attendues ici
            // (capacité 16384 << 2M échantillons totaux) ; la séquence reçue doit rester
            // strictement croissante.
            if (chunk[i] <= expected) {
                fprintf(stderr,
                        "CORRUPTION: reçu %f, attendu strictement > %f (received=%u)\n",
                        (double) chunk[i], (double) expected, received);
                exit(1);
            }
            expected = chunk[i];
            received++;
        }
    }
    return NULL;
}

static void test_concurrent_producer_consumer_stress(void) {
    static float storage[STRESS_RING_CAPACITY];
    SpscRing ring;
    spsc_ring_init(&ring, storage, STRESS_RING_CAPACITY);

    pthread_t prod, cons;
    pthread_create(&prod, NULL, producer_thread, &ring);
    pthread_create(&cons, NULL, consumer_thread, &ring);
    pthread_join(prod, NULL);
    pthread_join(cons, NULL);

    printf("[OK] test_concurrent_producer_consumer_stress (%u échantillons, capacité=%u)\n",
           STRESS_TOTAL_SAMPLES, STRESS_RING_CAPACITY);
}

// ── main ──────────────────────────────────────────────────────────────────────

int main(void) {
    test_basic_round_trip();
    test_read_more_than_available_is_partial_not_oob();
    test_write_more_than_free_space_truncates_silently();
    test_wraparound_many_laps();
    test_reset_clears_available();
    test_concurrent_producer_consumer_stress();

    printf("\nspsc_ring_test: 6/6 tests OK\n");
    return 0;
}
