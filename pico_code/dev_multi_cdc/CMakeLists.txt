# Generated Cmake Pico project file

cmake_minimum_required(VERSION 3.13)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

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

include(pico_sdk_import.cmake)

project(dev_multi_cdc C CXX ASM)

pico_sdk_init()

add_executable(dev_multi_cdc
    main.c
    usb_descriptors.c
)

target_include_directories(dev_multi_cdc PUBLIC
    ${CMAKE_CURRENT_LIST_DIR}
)

target_link_libraries(dev_multi_cdc PUBLIC
    pico_stdlib
    pico_unique_id
    hardware_adc
    hardware_dma
    hardware_pwm
    tinyusb_device
    tinyusb_board
)

pico_enable_stdio_usb(dev_multi_cdc 1)
pico_enable_stdio_uart(dev_multi_cdc 0)

pico_add_extra_outputs(dev_multi_cdc)