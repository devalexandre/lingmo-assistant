cmake_minimum_required(VERSION 3.16)
project(lingmo-assistant VERSION 1.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

include(GNUInstallDirs)

find_package(Qt6 REQUIRED COMPONENTS Core Gui Qml Quick DBus LinguistTools)
find_package(Python3 REQUIRED COMPONENTS Interpreter)

# Engine (Python package + launcher) lives in /usr/lib/lingmo-assistant
set(ENGINE_DIR ${CMAKE_INSTALL_FULL_LIBDIR}/lingmo-assistant)
set(ENGINE_PATH ${ENGINE_DIR}/lingmo-assistant-engine)
set(TRANSLATIONS_DIR ${CMAKE_INSTALL_FULL_DATADIR}/lingmo-assistant/translations)

add_executable(lingmo-assistant
    app/src/main.cpp
    app/src/assistant.cpp
    app/src/chatmodel.cpp
    app/src/engineclient.cpp
    app/src/flowdocument.cpp
    app/src/assistant_extra.cpp
    app/qml.qrc
)
target_compile_definitions(lingmo-assistant PRIVATE
    ENGINE_PATH="${ENGINE_PATH}"
    TRANSLATIONS_DIR="${TRANSLATIONS_DIR}"
)
target_link_libraries(lingmo-assistant PRIVATE Qt6::Core Qt6::Gui Qt6::Qml Qt6::Quick Qt6::DBus)

# lrelease only: building never rewrites the hand-edited .ts sources
qt_add_translation(QM_FILES translations/lingmo-assistant_pt_BR.ts)
add_custom_target(translations ALL DEPENDS ${QM_FILES})

configure_file(backend/lingmo-assistant-engine.in ${CMAKE_CURRENT_BINARY_DIR}/lingmo-assistant-engine @ONLY)
configure_file(backend/lingmo-assistant-flows.in ${CMAKE_CURRENT_BINARY_DIR}/lingmo-assistant-flows @ONLY)
configure_file(data/com.lingmo.Assistant.service.in ${CMAKE_CURRENT_BINARY_DIR}/com.lingmo.Assistant.service @ONLY)

install(TARGETS lingmo-assistant RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
install(FILES ${QM_FILES} DESTINATION ${TRANSLATIONS_DIR})
install(PROGRAMS ${CMAKE_CURRENT_BINARY_DIR}/lingmo-assistant-engine DESTINATION ${ENGINE_DIR})
# Background workflows (scheduled and event triggers), started at login
install(PROGRAMS ${CMAKE_CURRENT_BINARY_DIR}/lingmo-assistant-flows DESTINATION ${CMAKE_INSTALL_BINDIR})
install(FILES data/lingmo-assistant-flows.desktop DESTINATION ${CMAKE_INSTALL_FULL_SYSCONFDIR}/xdg/autostart)
install(DIRECTORY backend/lingmo_assistant DESTINATION ${ENGINE_DIR}
        PATTERN "__pycache__" EXCLUDE PATTERN "*.pyc" EXCLUDE)
install(FILES data/lingmo-assistant.desktop DESTINATION ${CMAKE_INSTALL_DATADIR}/applications)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/com.lingmo.Assistant.service
        DESTINATION ${CMAKE_INSTALL_DATADIR}/dbus-1/services)
install(FILES docs/protocol.md DESTINATION ${CMAKE_INSTALL_DOCDIR})
# Byte-compile the engine at install time (skipped when DESTDIR packaging prefers its own step)
install(CODE "execute_process(COMMAND ${Python3_EXECUTABLE} -m compileall -q \"\$ENV{DESTDIR}${ENGINE_DIR}/lingmo_assistant\")")

# Tests: ctest (engine: agno, ollama, sqlalchemy, pytest; app: Qt Test)
option(BUILD_TESTING "Run the engine and app tests with ctest" OFF)
if(BUILD_TESTING)
    enable_testing()
    find_package(Qt6 REQUIRED COMPONENTS Test)
    add_test(NAME engine COMMAND ${Python3_EXECUTABLE} -m pytest -q ${CMAKE_CURRENT_SOURCE_DIR}/backend/tests)
    add_executable(tst_flowdocument app/tests/tst_flowdocument.cpp app/src/flowdocument.cpp)
    target_include_directories(tst_flowdocument PRIVATE app/src)
    target_link_libraries(tst_flowdocument PRIVATE Qt6::Core Qt6::Qml Qt6::Test)
    add_test(NAME flowdocument COMMAND tst_flowdocument)
endif()
