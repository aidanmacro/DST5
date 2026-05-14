#include <stdio.h>
#include <stdint.h>
#include <string.h>

#include <bsp/board_api.h>
#include <tusb.h>

#include <pico/stdio.h>
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

static uint16_t samples[BUFFER_SAMPLES];
static uint8_t tx_packet[sizeof(packet_header_t) + BUFFER_SAMPLES * sizeof(uint16_t)];
static uint32_t sequence_number = 0;

static uint16_t checksum_u16(const uint16_t *data, uint16_t n)
{
    uint32_t sum = 0;

    for (uint16_t i = 0; i < n; i++) {
        sum += data[i];
    }

    return (uint16_t)(sum & 0xFFFF);
}

static void setup_pwm_pulse(void)
{
    gpio_set_function(PWM_PIN, GPIO_FUNC_PWM);

    uint slice = pwm_gpio_to_slice_num(PWM_PIN);
    uint channel = pwm_gpio_to_channel(PWM_PIN);

    pwm_config config = pwm_get_default_config();

    // 1 kHz PWM: 125 MHz / 125 / 1000
    pwm_config_set_clkdiv(&config, 125.0f);
    pwm_config_set_wrap(&config, 1999);

    pwm_init(slice, &config, false);

    // 1% duty cycle
    pwm_set_chan_level(slice, channel, 20);

    pwm_set_enabled(slice, true);
}

static void cdc_write_chunks(uint8_t itf, const uint8_t *data, uint32_t len)
{
    const uint32_t chunk_size = 32;
    uint32_t sent = 0;

    while (sent < len) {
        tud_task();

        uint32_t chunk = len - sent;

        if (chunk > chunk_size) {
            chunk = chunk_size;
        }

        uint32_t written = tud_cdc_n_write(itf, data + sent, chunk);

        if (written > 0) {
            tud_cdc_n_write_flush(itf);
            sent += written;
        } else {
            for (int i = 0; i < 10; i++) {
                tud_task();
            }
        }
    }
}

void custom_cdc_task(void);

int main(void)
{
    board_init();
    tusb_init();

    if (board_init_after_tusb) {
        board_init_after_tusb();
    }

    stdio_init_all();

    setup_pwm_pulse();

    adc_init();
    adc_gpio_init(ADC_GPIO);
    adc_select_input(ADC_INPUT);

    while (1) {
        tud_task();
        custom_cdc_task();
    }

    return 0;
}

void custom_cdc_task(void)
{
    static absolute_time_t last_send_time;

    if (absolute_time_diff_us(last_send_time, get_absolute_time()) < 10000) {
        return;
    }

    last_send_time = get_absolute_time();

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

    cdc_write_chunks(1, tx_packet, sizeof(tx_packet));
}

void tud_cdc_rx_cb(uint8_t itf)
{
    uint8_t buf[CFG_TUD_CDC_RX_BUFSIZE];
    uint32_t count = tud_cdc_n_read(itf, buf, sizeof(buf));
    (void)count;
}