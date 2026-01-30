cmake_minimum_required(VERSION 3.10)
project(HFT_Engine VERSION 1.0)

# Set C++ standard to C++17
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED True)

# Include directories
include_directories(include)

# Add source files
set(SOURCES
    src/order_book.cpp
    src/main.cpp
)

# Create executable named hft_core
add_executable(hft_core ${SOURCES})

# Optional: Enable warnings
if(MSVC)
    target_compile_options(hft_core PRIVATE /W4)
else()
    target_compile_options(hft_core PRIVATE -Wall -Wextra -pedantic)
endif()
