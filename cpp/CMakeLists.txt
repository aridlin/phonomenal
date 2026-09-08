cmake_minimum_required(VERSION 3.20)
project(phonomenal_splicer LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(phonomenal_splicer STATIC
    src/splicer.cpp
)
target_include_directories(phonomenal_splicer PUBLIC include)
target_link_libraries(phonomenal_splicer PUBLIC ${CMAKE_DL_LIBS})
if(MSVC)
    target_compile_options(phonomenal_splicer PRIVATE /W4 /permissive-)
else()
    target_compile_options(phonomenal_splicer PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable(phonomenal_splicer_cli
    src/main.cpp
)
target_link_libraries(phonomenal_splicer_cli PRIVATE phonomenal_splicer)

option(PHONOMENAL_BUILD_FRONTEND "Build FT desktop/terminal frontend" ON)
if(PHONOMENAL_BUILD_FRONTEND)
add_executable(phonomenal_splicer_frontend WIN32
    src/gui_main.cpp
    src/audio_io.cpp
    src/child_process.cpp
)
target_link_libraries(
    phonomenal_splicer_frontend
    PRIVATE
        phonomenal_splicer
)
if(WIN32)
    target_link_libraries(
        phonomenal_splicer_frontend
        PRIVATE
        d2d1
        dwrite
        gdi32
        ole32
        uuid
        user32
        windowscodecs
        comdlg32
        winmm
        ws2_32
        advapi32
    )
else()
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(CAIRO REQUIRED cairo)
    pkg_check_modules(X11 REQUIRED x11)
    target_include_directories(phonomenal_splicer_frontend PRIVATE ${CAIRO_INCLUDE_DIRS} ${X11_INCLUDE_DIRS})
    target_compile_options(phonomenal_splicer_frontend PRIVATE ${CAIRO_CFLAGS_OTHER} ${X11_CFLAGS_OTHER})
    target_link_libraries(phonomenal_splicer_frontend PRIVATE ${CAIRO_LIBRARIES} ${X11_LIBRARIES} dl m)
endif()
target_compile_definitions(phonomenal_splicer_frontend PRIVATE UNICODE _UNICODE NOMINMAX)
find_package(Threads REQUIRED)
target_link_libraries(phonomenal_splicer_frontend PRIVATE Threads::Threads)

endif()
