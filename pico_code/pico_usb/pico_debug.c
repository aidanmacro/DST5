#include <stdio.h>
#include <stdint.h>

#include "pico/stdlib.h"
#include "pico/stdio_usb.h"
#include "hardware/adc.h"

#define ADC_GPIO 28
#define ADC_INPUT 2

#define BUFFER_SAMPLES 1024

#define PACKET_MAGIC 0x5049434F  // "PICO"

static uint16_t buffer[BUFFER_SAMPLES];
static uint32_t sequence_number = 0;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint32_t sequence;
    uint32_t overruns;
    uint16_t samples;
    uint16_t reserved;
} packet_header_t;

static void setup_adc(void) {
    adc_init();
    adc_gpio_init(ADC_GPIO);
    adc_select_input(ADC_INPUT);
}

int main(void) {
    stdio_init_all();

    while (!stdio_usb_connected()) {
        sleep_ms(10);
    }

    setup_adc();

    while (true) {
        for (uint i = 0; i < BUFFER_SAMPLES; i++) {
            buffer[i] = adc_read() & 0x0FFF;
        }

        packet_header_t header = {
            .magic = PACKET_MAGIC,
            .sequence = sequence_number++,
            .overruns = 0,
            .samples = BUFFER_SAMPLES,
            .reserved = 0
        };

        fwrite(&header, sizeof(header), 1, stdout);
        fwrite(buffer, sizeof(uint16_t), BUFFER_SAMPLES, stdout);
        fflush(stdout);

        sleep_ms(10);
    }
}