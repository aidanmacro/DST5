# Generated Cmake Pico project file

cmake_minimum_required(VERSION 3.13)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Initialise pico_sdk from installed location
# (note this can come from environment, CMake cache etc)

# == DO NOT EDIT THE FOLLOWING LINES for the Raspberry Pi Pico VS Code Extension to work ==
if(WIN32)
    set(USERHOME $ENV{USERPROFILE})
else()
    set(USERHOME $ENV{HOME})
endif()
set(sdkVersion 2.2.0)
set(toolchainVersion 14_2_Rel1)
set(picotoolVersion 2.2.0-a4)
set(picoVscode ${USERHOME}/.pico-sdk/cmake/pico-vscode.cmake)
if (EXISTS ${picoVscode})
    include(${picoVscode})
endif()
# ====================================================================================
set(PICO_BOARD pico CACHE STRING "Board type")

# Pull in Raspberry Pi Pico SDK (must be before project)
include(pico_sdk_import.cmake)

project(pico_usb C CXX ASM)

# Initialise the Raspberry Pi Pico SDK
pico_sdk_init()

# Add executable. Default name is the project name, version 0.1

if (TARGET tinyusb_device)
    add_executable(pico_usb
            #pico_usb.c
            pico_debug.c
            )

    # pull in common dependencies
    target_link_libraries(pico_usb 
        pico_stdlib 
        hardware_adc
        hardware_dma
        hardware_pwm
    )

    # enable usb output, disable uart output
    pico_enable_stdio_usb(pico_usb 1)
    pico_enable_stdio_uart(pico_usb 0)

    # create map/bin/hex/uf2 file etc.
    pico_add_extra_outputs(pico_usb)

    # add url via pico_set_program_url
elseif(PICO_ON_DEVICE)
    message("Skipping pico_usb because TinyUSB submodule is not initialized in the SDK")
endif()
