#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>

#include <bsp/board_api.h>
#include <tusb.h>

#include <pico/stdio.h>
#include "pico/stdlib.h"
#include "hardware/adc.h"
#include "hardware/pwm.h"
#include "hardware/dma.h"
#include "hardware/irq.h"

#define PWM_PIN 22

#define ADC_GPIO 28
#define ADC_INPUT 2

#define BUFFER_SAMPLES 512
#define PACKET_BUFFERS 8

#define ADC_SAMPLE_RATE_HZ 100000

#define MAGIC1 0x5049434F
#define MAGIC2 0x41444321

typedef struct __attribute__((packed)) {
    uint32_t magic1;
    uint32_t magic2;
    uint32_t sequence;
    uint32_t dropped;
    uint16_t samples;
    uint16_t checksum;
} packet_header_t;

typedef struct {
    packet_header_t header;
    uint16_t samples[BUFFER_SAMPLES];
    volatile bool ready;
} packet_t;

static packet_t packets[PACKET_BUFFERS];

static volatile uint32_t sequence_number = 0;
static volatile uint32_t dropped_buffers = 0;

static volatile uint8_t write_index = 0;
static volatile uint8_t read_index = 0;

static int dma_chan;

static uint16_t checksum_u16(const uint16_t *data, uint16_t n)
{
    uint32_t sum = 0;

    for (uint16_t i = 0; i < n; i++) {
        sum += data[i];
    }

    return (uint16_t)(sum & 0xFFFF);
}

static void finish_packet(packet_t *packet)
{
    packet->header.magic1 = MAGIC1;
    packet->header.magic2 = MAGIC2;
    packet->header.sequence = sequence_number++;
    packet->header.dropped = dropped_buffers;
    packet->header.samples = BUFFER_SAMPLES;
    packet->header.checksum = checksum_u16(packet->samples, BUFFER_SAMPLES);

    packet->ready = true;

    write_index++;
    if (write_index >= PACKET_BUFFERS) {
        write_index = 0;
    }
}

static void start_dma_capture(void)
{
    packet_t *packet = &packets[write_index];

    if (packet->ready) {
        dropped_buffers++;
        return;
    }

    dma_channel_set_write_addr(
        dma_chan,
        packet->samples,
        false
    );

    dma_channel_set_trans_count(
        dma_chan,
        BUFFER_SAMPLES,
        true
    );
}

static void dma_irq_handler(void)
{
    dma_hw->ints0 = 1u << dma_chan;

    packet_t *packet = &packets[write_index];

    finish_packet(packet);
    start_dma_capture();
}

static void setup_pwm_pulse(void)
{
    gpio_set_function(PWM_PIN, GPIO_FUNC_PWM);

    uint slice = pwm_gpio_to_slice_num(PWM_PIN);
    uint channel = pwm_gpio_to_channel(PWM_PIN);

    pwm_config config = pwm_get_default_config();

    pwm_config_set_clkdiv(&config, 125.0f);
    pwm_config_set_wrap(&config, 1999);

    pwm_init(slice, &config, false);
    pwm_set_chan_level(slice, channel, 20);

    pwm_set_counter(slice, 0);
    pwm_set_enabled(slice, true);
}

static void setup_adc_dma(void)
{
    adc_init();
    adc_gpio_init(ADC_GPIO);
    adc_select_input(ADC_INPUT);

    adc_fifo_setup(
        true,
        true,
        1,
        false,
        false
    );

    float clkdiv = 48000000.0f / ADC_SAMPLE_RATE_HZ;

    adc_set_clkdiv(clkdiv);

    dma_chan = dma_claim_unused_channel(true);

    dma_channel_config config = dma_channel_get_default_config(dma_chan);

    channel_config_set_transfer_data_size(&config, DMA_SIZE_16);
    channel_config_set_read_increment(&config, false);
    channel_config_set_write_increment(&config, true);
    channel_config_set_dreq(&config, DREQ_ADC);

    dma_channel_configure(
        dma_chan,
        &config,
        NULL,
        &adc_hw->fifo,
        BUFFER_SAMPLES,
        false
    );

    dma_channel_set_irq0_enabled(dma_chan, true);
    irq_set_exclusive_handler(DMA_IRQ_0, dma_irq_handler);
    irq_set_enabled(DMA_IRQ_0, true);

    adc_fifo_drain();

    start_dma_capture();

    adc_run(true);
}

static void cdc_write_chunks(uint8_t itf, const uint8_t *data, uint32_t len)
{
    const uint32_t chunk_size = 64;
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

void custom_cdc_task(void)
{
    packet_t *packet = &packets[read_index];

    if (!packet->ready) {
        return;
    }

    if (!tud_cdc_n_connected(1)) {
        return;
    }

    cdc_write_chunks(
        1,
        (const uint8_t *)&packet->header,
        sizeof(packet_header_t)
    );

    cdc_write_chunks(
        1,
        (const uint8_t *)packet->samples,
        BUFFER_SAMPLES * sizeof(uint16_t)
    );

    packet->ready = false;

    read_index++;
    if (read_index >= PACKET_BUFFERS) {
        read_index = 0;
    }
}

void tud_cdc_rx_cb(uint8_t itf)
{
    uint8_t buf[CFG_TUD_CDC_RX_BUFSIZE];
    uint32_t count = tud_cdc_n_read(itf, buf, sizeof(buf));
    (void)count;
}

int main(void)
{
    board_init();
    tusb_init();

    stdio_init_all();

    for (uint8_t i = 0; i < PACKET_BUFFERS; i++) {
        packets[i].ready = false;
    }

    setup_pwm_pulse();
    setup_adc_dma();

    while (1) {
        tud_task();
        custom_cdc_task();
    }

    return 0;
}