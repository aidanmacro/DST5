#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>

#include "pico/stdlib.h"
#include "pico/stdio_usb.h"

#include "hardware/adc.h"
#include "hardware/dma.h"
#include "hardware/irq.h"
#include "hardware/pwm.h"
#include "hardware/clocks.h"

#define PWM_PIN 22

#define ADC_GPIO 28
#define ADC_INPUT 2

#define SAMPLE_RATE_HZ 1000
#define BUFFER_SAMPLES 4096
#define NUM_BUFFERS 8

#define PACKET_MAGIC 0x5049434F  // "PICO"

static uint16_t buffers[NUM_BUFFERS][BUFFER_SAMPLES];

static volatile uint8_t buffer_state[NUM_BUFFERS] = {0};
// 0 = free, 1 = filling, 2 = full

static volatile uint current_dma_buffer = 0;
static volatile uint32_t sequence_number = 0;
static volatile uint32_t overrun_count = 0;

static int dma_chan;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint32_t sequence;
    uint32_t overruns;
    uint16_t samples;
    uint16_t reserved;
} packet_header_t;

static void start_dma_to_buffer(uint buffer_index) {
    buffer_state[buffer_index] = 1;
    current_dma_buffer = buffer_index;

    dma_channel_set_write_addr(dma_chan, buffers[buffer_index], false);
    dma_channel_set_read_addr(dma_chan, &adc_hw->fifo, false);
    dma_channel_set_trans_count(dma_chan, BUFFER_SAMPLES, true);
}

static void dma_irq_handler(void) {
    dma_hw->ints0 = 1u << dma_chan;

    uint finished = current_dma_buffer;
    buffer_state[finished] = 2;

    uint next = (finished + 1) % NUM_BUFFERS;

    if (buffer_state[next] != 0) {
        overrun_count++;
        buffer_state[next] = 0;
    }

    start_dma_to_buffer(next);
}

static void setup_pwm_pulse(void) {
    gpio_set_function(PWM_PIN, GPIO_FUNC_PWM);

    uint slice = pwm_gpio_to_slice_num(PWM_PIN);
    uint channel = pwm_gpio_to_channel(PWM_PIN);

    pwm_config config = pwm_get_default_config();

    // 125 MHz / 125 / 1000 = 1 kHz
    pwm_config_set_clkdiv(&config, 125.0f);
    pwm_config_set_wrap(&config, 999);

    pwm_init(slice, &config, false);

    // 1% duty cycle
    pwm_set_chan_level(slice, channel, 10);

    pwm_set_enabled(slice, true);
}

static void setup_adc(void) {
    adc_init();
    adc_gpio_init(ADC_GPIO);
    adc_select_input(ADC_INPUT);

    adc_fifo_setup(
        true,   // write each conversion to FIFO
        true,   // enable DMA data request
        1,      // DREQ when at least 1 sample present
        false,  // no error bit
        false   // do not shift to 8-bit
    );

    float div = (48000000.0f / (SAMPLE_RATE_HZ * 96.0f)) - 1.0f;
    if (div < 0.0f) div = 0.0f;

    adc_set_clkdiv(div);
}

static void setup_dma(void) {
    dma_chan = dma_claim_unused_channel(true);

    dma_channel_config config = dma_channel_get_default_config(dma_chan);

    channel_config_set_transfer_data_size(&config, DMA_SIZE_16);
    channel_config_set_read_increment(&config, false);
    channel_config_set_write_increment(&config, true);
    channel_config_set_dreq(&config, DREQ_ADC);

    dma_channel_configure(
        dma_chan,
        &config,
        buffers[0],
        &adc_hw->fifo,
        BUFFER_SAMPLES,
        false
    );

    dma_channel_set_irq0_enabled(dma_chan, true);
    irq_set_exclusive_handler(DMA_IRQ_0, dma_irq_handler);
    irq_set_enabled(DMA_IRQ_0, true);
}

int main(void) {
    stdio_init_all();

    while (!stdio_usb_connected()) {
        sleep_ms(10);
    }

    setup_pwm_pulse();
    setup_adc();
    setup_dma();

    buffer_state[0] = 0;
    buffer_state[1] = 0;

    start_dma_to_buffer(0);

    adc_run(true);

    while (true) {
        for (uint i = 0; i < NUM_BUFFERS; i++) {
            if (buffer_state[i] == 2) {
                packet_header_t header = {
                    .magic = PACKET_MAGIC,
                    .sequence = sequence_number++,
                    .overruns = overrun_count,
                    .samples = BUFFER_SAMPLES,
                    .reserved = 0
                };

                fwrite(&header, sizeof(header), 1, stdout);
                fwrite(buffers[i], sizeof(uint16_t), BUFFER_SAMPLES, stdout);
                fflush(stdout);

                buffer_state[i] = 0;
            }
        }
    }
}

