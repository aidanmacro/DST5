#include <stdint.h>
#include <string.h>
#include <stdio.h>

#include <bsp/board_api.h>
#include <tusb.h>

#include "pico/stdlib.h"
#include "hardware/adc.h"
#include "hardware/pwm.h"

#define PWM_PIN 22

#define ADC_GPIO 28
#define ADC_INPUT 2

#define BUFFER_SAMPLES 512

#define MAGIC1 0x5049434F  // "PICO"
#define MAGIC2 0x41444321  // "ADC!"

typedef struct __attribute__((packed)) {
    uint32_t magic1;
    uint32_t magic2;
    uint32_t sequence;
    uint16_t samples;
    uint16_t checksum;
} packet_header_t;

#define TX_PACKET_BYTES (sizeof(packet_header_t) + BUFFER_SAMPLES * sizeof(uint16_t))

static uint16_t samples[BUFFER_SAMPLES];
static uint8_t tx_packet[TX_PACKET_BYTES];

static uint32_t sequence_number = 0;
static uint32_t dropped_packets = 0;

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

    pwm_config_set_clkdiv(&config, 125.0f);
    pwm_config_set_wrap(&config, 999);

    pwm_init(slice, &config, false);
    pwm_set_chan_level(slice, channel, 10);
    pwm_set_enabled(slice, true);
}

static void setup_adc(void) {
    adc_init();
    adc_gpio_init(ADC_GPIO);
    adc_select_input(ADC_INPUT);
}

static void send_adc_packet_on_cdc1(void) {
    if (!tud_cdc_n_connected(1)) {
        return;
    }

    for (uint16_t i = 0; i < BUFFER_SAMPLES; i++) {
        samples[i] = adc_read() & 0x0FFF;
    }

    packet_header_t header = {
        .magic1 = MAGIC1,
        .magic2 = MAGIC2,
        .sequence = sequence_number++,
        .samples = BUFFER_SAMPLES,
        .checksum = checksum_u16(samples, BUFFER_SAMPLES)
    };

    memcpy(tx_packet, &header, sizeof(header));
    memcpy(tx_packet + sizeof(header), samples, sizeof(samples));

    if (tud_cdc_n_write_available(1) >= TX_PACKET_BYTES) {
        tud_cdc_n_write(1, tx_packet, TX_PACKET_BYTES);
        tud_cdc_n_write_flush(1);
    } else {
        dropped_packets++;
    }
}

int main(void) {
    board_init();
    tusb_init();

    if (board_init_after_tusb) {
        board_init_after_tusb();
    }

    stdio_init_all();

    setup_pwm_pulse();
    setup_adc();

    while (true) {
        tud_task();
        send_adc_packet_on_cdc1();
    }

    return 0;
}

void tud_cdc_rx_cb(uint8_t itf) {
    uint8_t buf[CFG_TUD_CDC_RX_BUFSIZE];

    uint32_t count = tud_cdc_n_read(itf, buf, sizeof(buf));
    (void) count;
}