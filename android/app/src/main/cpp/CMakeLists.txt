cmake_minimum_required(VERSION 3.22.1)
project(rubberband_processor)

# ── Rubber Band source ────────────────────────────────────────────────────────
#
# SETUP: Download Rubber Band Library v3.x from https://breakfastquay.com/rubberband/
# (GPL or commercial licence) and unzip so that this path resolves:
#   android/app/src/main/cpp/rubberband/rubberband/RubberBandStretcher.h
#
# All .cpp files from rubberband/src/ must be listed below (or discovered via glob).
# Run: find rubberband/src -name "*.cpp" | sort
# to regenerate the list after updating the library version.
#
# The glob approach is convenient but requires a cmake re-run on new files:
file(GLOB_RECURSE RUBBERBAND_SOURCES
    "${CMAKE_CURRENT_SOURCE_DIR}/rubberband/src/*.cpp"
)

add_library(
    rubberband_processor
    SHARED
    rubberband_processor.cpp
    ${RUBBERBAND_SOURCES}
)

target_include_directories(rubberband_processor PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/rubberband"
)

# Rubber Band uses HAVE_SPEEX / HAVE_VDSP / HAVE_IPP for optional backends.
# On Android we use the built-in FFTW-fallback (no HAVE_* defined = Rubber Band's
# own KissFFT fallback is compiled in).  If you want to link the FFTW prebuilt .so,
# set -DHAVE_FFTW3=1 here and add the .so to jniLibs/.
target_compile_definitions(rubberband_processor PRIVATE
    USE_BQRESAMPLER=1        # use Rubber Band's built-in resampler
    HAVE_POSIX_MEMALIGN=1    # available on all modern Android NDK targets
)

target_compile_options(rubberband_processor PRIVATE
    -std=c++17
    -O3
    -ffast-math              # safe for audio DSP: assumes no NaN/Inf in input
    -fvisibility=hidden
)

find_library(log-lib log)
target_link_libraries(rubberband_processor ${log-lib})
