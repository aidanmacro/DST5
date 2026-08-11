#define PWM_PIN 4

const int frequency = 500;      // 500 Hz (2 ms period)
const int resolution = 12;      // 12-bit (0-4095)

void setup() {
  ledcAttach(PWM_PIN, frequency, resolution);

  // 1% duty cycle
  // 4095 * 0.01 ≈ 41
  ledcWrite(PWM_PIN, 41);
}

void loop() {
}