#include <stdio.h>
#include <stdint.h>

#include "pico/stdlib.h"
#include "pico/stdio_usb.h"

#include "hardware/adc.h"
#include "hardware/pwm.h"

#define PWM_PIN 22

#define ADC_GPIO 28
#define ADC_INPUT 2

#define BUFFER_SAMPLES 512

#define MAGIC1 0x5049434F  // "PICO"
#define MAGIC2 0x41444321  // "ADC!"

static uint16_t buffer[BUFFER_SAMPLES];
static uint32_t sequence_number = 0;

typedef struct __attribute__((packed)) {
    uint32_t magic1;
    uint32_t magic2;
    uint32_t sequence;
    uint16_t samples;
    uint16_t checksum;
} packet_header_t;

static uint16_t checksum_u16(const uint16_t *data, uint16_t n) {
    uint32_t sum = 0;

    for (uint16_t i = 0; i < n; i++) {
        sum += data[i];
    }

    return (uint16_t)(sum & 0xFFFF);
}

static void setup_pwm_pulse(void) {
    gpio_set_function(PWM_PIN, GPIO_FUNC_PWM);

    uint slice = pwm_gpio_to_slice_num(PWM_PIN);
    uint channel = pwm_gpio_to_channel(PWM_PIN);

    pwm_config config = pwm_get_default_config();

    // 1 kHz PWM: 125 MHz / 125 / 1000
    pwm_config_set_clkdiv(&config, 125.0f);
    pwm_config_set_wrap(&config, 999);

    pwm_init(slice, &config, false);

    // 1% duty cycle
    pwm_set_chan_level(slice, channel, 10);

    pwm_set_enabled(slice, true);
}

int main(void) {
    stdio_init_all();

    while (!stdio_usb_connected()) {
        sleep_ms(10);
    }

    setup_pwm_pulse();

    adc_init();
    adc_gpio_init(ADC_GPIO);
    adc_select_input(ADC_INPUT);

    while (true) {
        for (uint16_t i = 0; i < BUFFER_SAMPLES; i++) {
            buffer[i] = adc_read() & 0x0FFF;
        }

        packet_header_t header = {
            .magic1 = MAGIC1,
            .magic2 = MAGIC2,
            .sequence = sequence_number++,
            .samples = BUFFER_SAMPLES,
            .checksum = checksum_u16(buffer, BUFFER_SAMPLES)
        };

        fwrite(&header, sizeof(header), 1, stdout);
        fwrite(buffer, sizeof(uint16_t), BUFFER_SAMPLES, stdout);
        fflush(stdout);

        sleep_ms(10);
    }
}