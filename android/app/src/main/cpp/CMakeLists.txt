cmake_minimum_required(VERSION 3.22.1)
project(psola_processor)

# ── Moteur PSOLA maison (Rust) — remplace Rubber Band (GPL-3.0) ─────────────────
#
# Ce CMakeLists ne compile QUE le petit pont JNI (jni_shim.c, ~90 lignes) ; le moteur DSP
# lui-même vit dans le workspace Rust natif à la racine du repo (native/psola-dsp +
# native/psola-ffi — voir docs/roadmap.md). On invoque `cargo build` pour l'ABI en cours
# (CMake le refait automatiquement à chaque appel de `cargo build` pour chaque ABI ciblée par
# `externalNativeBuild`), puis on lie l'archive statique produite comme IMPORTED.
#
# PRÉREQUIS (voir docs/deployment.md) : `rustup target add` pour les 4 triples ci-dessous.
# Sans ça, `cargo build` échoue ici avec un message explicite plutôt qu'une erreur de link
# cryptique.

if(ANDROID_ABI STREQUAL "arm64-v8a")
    set(RUST_TARGET "aarch64-linux-android")
    set(CLANG_TARGET "aarch64-linux-android")
elseif(ANDROID_ABI STREQUAL "armeabi-v7a")
    set(RUST_TARGET "armv7-linux-androideabi")
    set(CLANG_TARGET "armv7a-linux-androideabi") # note le "a" — nommage NDK, pas le triple Rust
elseif(ANDROID_ABI STREQUAL "x86")
    set(RUST_TARGET "i686-linux-android")
    set(CLANG_TARGET "i686-linux-android")
elseif(ANDROID_ABI STREQUAL "x86_64")
    set(RUST_TARGET "x86_64-linux-android")
    set(CLANG_TARGET "x86_64-linux-android")
else()
    message(FATAL_ERROR "ABI Android non supportée par le moteur Rust psola-ffi : ${ANDROID_ABI}")
endif()

# minSdkVersion (android/variables.gradle) — le wrapper clang du NDK est nommé par API level.
set(ANDROID_MIN_API 24)

if(CMAKE_HOST_SYSTEM_NAME STREQUAL "Darwin")
    set(NDK_HOST_TAG "darwin-x86_64")
elseif(CMAKE_HOST_SYSTEM_NAME STREQUAL "Linux")
    set(NDK_HOST_TAG "linux-x86_64")
else()
    set(NDK_HOST_TAG "windows-x86_64")
endif()

set(NDK_TOOLCHAIN_BIN "${CMAKE_ANDROID_NDK}/toolchains/llvm/prebuilt/${NDK_HOST_TAG}/bin")
set(RUST_LINKER "${NDK_TOOLCHAIN_BIN}/${CLANG_TARGET}${ANDROID_MIN_API}-clang")

string(REPLACE "-" "_" RUST_TARGET_ENV "${RUST_TARGET}")
string(TOUPPER "${RUST_TARGET_ENV}" RUST_TARGET_ENV)

set(RUST_WORKSPACE "${CMAKE_CURRENT_SOURCE_DIR}/../../../../../native")
get_filename_component(RUST_WORKSPACE "${RUST_WORKSPACE}" ABSOLUTE)
set(RUST_OUT_DIR "${RUST_WORKSPACE}/target/${RUST_TARGET}/release")
set(PSOLA_STATIC_LIB "${RUST_OUT_DIR}/libpsola_ffi.a")

find_program(CARGO_EXECUTABLE cargo
    PATHS "$ENV{HOME}/.cargo/bin"
    ENV PATH
)
if(NOT CARGO_EXECUTABLE)
    message(FATAL_ERROR
        "cargo introuvable. Installe Rust (https://rustup.rs) — voir docs/deployment.md, "
        "prérequis de build Android."
    )
endif()

message(STATUS "psola-ffi : cargo build --release --target ${RUST_TARGET} (linker: ${RUST_LINKER})")
execute_process(
    COMMAND ${CMAKE_COMMAND} -E env
        "CARGO_TARGET_${RUST_TARGET_ENV}_LINKER=${RUST_LINKER}"
        "CC_${RUST_TARGET}=${RUST_LINKER}"
        "AR_${RUST_TARGET}=${NDK_TOOLCHAIN_BIN}/llvm-ar"
        ${CARGO_EXECUTABLE} build --release --target ${RUST_TARGET} -p psola-ffi
    WORKING_DIRECTORY ${RUST_WORKSPACE}
    RESULT_VARIABLE CARGO_BUILD_RESULT
)
if(NOT CARGO_BUILD_RESULT EQUAL 0)
    message(FATAL_ERROR
        "cargo build a échoué pour ${RUST_TARGET} (code ${CARGO_BUILD_RESULT}). "
        "Vérifie que la cible est installée : rustup target add ${RUST_TARGET} "
        "— voir docs/deployment.md."
    )
endif()

add_library(psola_ffi_imported STATIC IMPORTED)
set_target_properties(psola_ffi_imported PROPERTIES
    IMPORTED_LOCATION "${PSOLA_STATIC_LIB}"
)

add_library(
    psola_processor
    SHARED
    jni_shim.c
    # aaudio_engine.c/aaudio_jni.c : moteur audio bas niveau optionnel (voir leur en-tête).
    # AAudio est chargé via dlopen à l'exécution (aaudio_shim.h), jamais lié directement — le
    # dlopen échoue proprement sur les appareils API<26 (minSdkVersion=24), pas d'erreur de
    # link. spsc_ring.h/aaudio_shim.h sont header-only, pas de .c séparé à lister.
    aaudio_engine.c
    aaudio_jni.c
)

target_include_directories(psola_processor PRIVATE
    "${RUST_WORKSPACE}/psola-ffi/include"
)

target_compile_options(psola_processor PRIVATE
    -O3
    -fvisibility=hidden
)

find_library(log-lib log)

# libdl (dlopen/dlsym, aaudio_shim.h) — sur Android moderne dl est déjà dans libc/bionic, mais
# find_library reste portable/explicite si jamais ça change.
find_library(dl-lib dl)

# L'ordre compte pour un linker statique classique (ld.bfd/gold) : psola_ffi_imported avant
# log/libc — lld (par défaut sur NDK récent) est plus tolérant mais autant rester correct.
target_link_libraries(psola_processor
    psola_ffi_imported
    ${log-lib}
    ${dl-lib}
)
