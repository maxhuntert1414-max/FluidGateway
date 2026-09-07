cmake_minimum_required(VERSION 3.25)
project(FluidGatewayNative VERSION 0.68.0 LANGUAGES CXX)

if(NOT WIN32 OR NOT MSVC)
    message(FATAL_ERROR "The native server currently requires Windows and MSVC.")
endif()

option(FLUIDGATEWAY_ENABLE_ASAN "Enable AddressSanitizer (development only)" OFF)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

add_library(fluidgateway-core STATIC src/core.cpp src/protocol.cpp)
target_include_directories(fluidgateway-core PUBLIC include)
target_compile_features(fluidgateway-core PUBLIC cxx_std_20)

add_executable(fluidgateway-native src/server.cpp)
target_link_libraries(fluidgateway-native PRIVATE fluidgateway-core ws2_32 bcrypt)

include(CTest)
if(BUILD_TESTING)
    add_executable(fluidgateway-native-tests tests/core_tests.cpp)
    target_link_libraries(fluidgateway-native-tests PRIVATE fluidgateway-core)
    add_executable(fluidgateway-native-benchmark tests/benchmark.cpp)
    target_link_libraries(fluidgateway-native-benchmark PRIVATE fluidgateway-core)
    add_test(NAME native-core COMMAND fluidgateway-native-tests)
endif()

get_directory_property(targets BUILDSYSTEM_TARGETS)
foreach(target IN LISTS targets)
    get_target_property(target_type ${target} TYPE)
    if(target_type STREQUAL "UTILITY")
        continue()
    endif()
    target_compile_definitions(${target} PRIVATE
        WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE)
    target_compile_options(${target} PRIVATE /W4 /WX /permissive- /EHsc /GS /sdl /guard:cf)
    target_link_options(${target} PRIVATE /guard:cf /DYNAMICBASE /NXCOMPAT /HIGHENTROPYVA)
    if(FLUIDGATEWAY_ENABLE_ASAN)
        target_compile_options(${target} PRIVATE /fsanitize=address /Zi)
        target_link_options(${target} PRIVATE /INCREMENTAL:NO /DEBUG)
    endif()
endforeach()

install(TARGETS fluidgateway-native RUNTIME DESTINATION .)
install(FILES ../LICENSE DESTINATION .)
