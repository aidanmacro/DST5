import sys
import struct
import threading
import csv
from collections import deque

import serial
import numpy as np
import pyqtgraph as pg
from PyQt6 import QtWidgets, QtCore

PORT = "COM6"
BAUD = 115200
EXPECTED_SAMPLES = 512

VREF = 3.3
ADC_MAX = 4095.0
ADC_SAMPLE_RATE_HZ = 500000

MAGIC_BYTES = b"OCIP!CDA"
HEADER_REST_FMT = "<I I H H"
HEADER_REST_SIZE = struct.calcsize(HEADER_REST_FMT)

RAW_BUFFER_SAMPLES = 8192

TRIGGER_LEVEL = 0.609
TRIGGER_MODE = "Rising"
TRIGGER_HOLDOFF_SAMPLES = 30

SMOOTHING_SAMPLES = 3
NOTCH_ENABLED = False
NOTCH_FREQ_HZ = 120000
NOTCH_R = 0.92

PRE_TRIGGER_SAMPLES = 100
POST_TRIGGER_SAMPLES = 50
BASELINE_SAMPLES = 5
SUBTRACT_BASELINE = True

BIN_MS = 10
DISPLAY_SECONDS = 5

TRACE_SMOOTHING_POINTS = 9

Y_MIN = 0.12
Y_MAX = 0.2

latest_status = "Waiting..."
rolling_volts = np.array([], dtype=np.float32)
total_samples_received = 0

lock = threading.Lock()
running = True


def checksum_u16(adc_u16):
    return int(np.sum(adc_u16, dtype=np.uint32) & 0xFFFF)


def read_exact(ser, n):
    buf = bytearray(n)
    view = memoryview(buf)
    got = 0

    while running and got < n:
        r = ser.readinto(view[got:])
        if r:
            got += r

    return bytes(buf) if got == n else None


def wait_for_magic(ser):
    window = bytearray()

    while running:
        b = ser.read(1)

        if not b:
            continue

        window += b

        if len(window) > len(MAGIC_BYTES):
            del window[0]

        if bytes(window) == MAGIC_BYTES:
            return True

    return False


def serial_thread():
    global rolling_volts, latest_status, total_samples_received

    ser = serial.Serial(PORT, BAUD, timeout=0.1)
    ser.dtr = True
    ser.reset_input_buffer()

    try:
        while running:
            if not wait_for_magic(ser):
                break

            rest = read_exact(ser, HEADER_REST_SIZE)

            if rest is None:
                break

            _sequence, _dropped, samples, checksum = struct.unpack(
                HEADER_REST_FMT,
                rest
            )

            if samples != EXPECTED_SAMPLES:
                continue

            raw = read_exact(ser, samples * 2)

            if raw is None:
                break

            adc_u16 = np.frombuffer(raw, dtype="<u2").copy()

            if adc_u16.max() > 4095:
                continue

            if checksum_u16(adc_u16) != checksum:
                continue

            volts = adc_u16.astype(np.float32) * (VREF / ADC_MAX)

            status = (
                f"raw min={volts.min():.3f} V | "
                f"raw max={volts.max():.3f} V"
            )

            with lock:
                total_samples_received += len(volts)

                rolling_volts = np.concatenate((rolling_volts, volts))

                if len(rolling_volts) > RAW_BUFFER_SAMPLES:
                    rolling_volts = rolling_volts[-RAW_BUFFER_SAMPLES:]

                latest_status = status

    finally:
        ser.close()


class CapnogramWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Pico ADC Capnogram")

        self.paused = False

        self.trigger_level = TRIGGER_LEVEL
        self.trigger_mode = TRIGGER_MODE
        self.trigger_holdoff_samples = TRIGGER_HOLDOFF_SAMPLES

        self.smoothing_samples = SMOOTHING_SAMPLES
        self.notch_enabled = NOTCH_ENABLED
        self.notch_freq_hz = NOTCH_FREQ_HZ
        self.notch_r = NOTCH_R

        self.trace_smoothing_points = TRACE_SMOOTHING_POINTS

        self.pre_trigger_samples = PRE_TRIGGER_SAMPLES
        self.post_trigger_samples = POST_TRIGGER_SAMPLES
        self.baseline_samples = BASELINE_SAMPLES
        self.subtract_baseline = SUBTRACT_BASELINE

        self.bin_seconds = BIN_MS / 1000.0
        self.display_seconds = DISPLAY_SECONDS

        self.last_processed_trigger_abs = -1

        self.current_bin_index = None
        self.current_bin_sum = 0.0
        self.current_bin_count = 0

        self.completed_points = deque()

        self.last_plot_x = np.array([], dtype=np.float32)
        self.last_plot_y = np.array([], dtype=np.float32)

        layout = QtWidgets.QVBoxLayout(self)

        self.plot_widget = pg.GraphicsLayoutWidget()
        self.plot = self.plot_widget.addPlot(
            title="Waiting for data..."
        )

        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.setLabel("left", "Smoothed averaged pulse peak", units="V")

        self.plot.setYRange(Y_MIN, Y_MAX, padding=0)
        self.plot.setXRange(-self.display_seconds, 0, padding=0)
        self.plot.showGrid(x=True, y=True)

        self.curve = self.plot.plot(
            pen=pg.mkPen(width=2),
            symbol="o",
            symbolSize=4
        )

        layout.addWidget(self.plot_widget)

        controls = QtWidgets.QGridLayout()

        self.pause_button = QtWidgets.QPushButton("Pause")
        self.pause_button.clicked.connect(self.toggle_pause)
        controls.addWidget(self.pause_button, 0, 0)

        self.export_button = QtWidgets.QPushButton("Export CSV")
        self.export_button.clicked.connect(self.export_csv)
        controls.addWidget(self.export_button, 0, 1)

        controls.addWidget(QtWidgets.QLabel("Y min"), 1, 0)

        self.y_min_spin = QtWidgets.QDoubleSpinBox()
        self.y_min_spin.setRange(-1.0, 3.3)
        self.y_min_spin.setSingleStep(0.01)
        self.y_min_spin.setValue(Y_MIN)
        self.y_min_spin.valueChanged.connect(self.update_y_range)
        controls.addWidget(self.y_min_spin, 1, 1)

        controls.addWidget(QtWidgets.QLabel("Y max"), 1, 2)

        self.y_max_spin = QtWidgets.QDoubleSpinBox()
        self.y_max_spin.setRange(0.0, 5.0)
        self.y_max_spin.setSingleStep(0.01)
        self.y_max_spin.setValue(Y_MAX)
        self.y_max_spin.valueChanged.connect(self.update_y_range)
        controls.addWidget(self.y_max_spin, 1, 3)

        controls.addWidget(QtWidgets.QLabel("Display seconds"), 2, 0)

        self.display_seconds_spin = QtWidgets.QDoubleSpinBox()
        self.display_seconds_spin.setRange(1.0, 120.0)
        self.display_seconds_spin.setSingleStep(1.0)
        self.display_seconds_spin.setValue(self.display_seconds)
        self.display_seconds_spin.valueChanged.connect(
            self.update_display_seconds
        )
        controls.addWidget(self.display_seconds_spin, 2, 1)

        controls.addWidget(QtWidgets.QLabel("Bin ms"), 2, 2)

        self.bin_ms_spin = QtWidgets.QSpinBox()
        self.bin_ms_spin.setRange(1, 1000)
        self.bin_ms_spin.setSingleStep(1)
        self.bin_ms_spin.setValue(BIN_MS)
        self.bin_ms_spin.valueChanged.connect(self.update_bin_ms)
        controls.addWidget(self.bin_ms_spin, 2, 3)

        controls.addWidget(QtWidgets.QLabel("Trigger V"), 3, 0)

        self.trigger_spin = QtWidgets.QDoubleSpinBox()
        self.trigger_spin.setRange(0.0, VREF)
        self.trigger_spin.setSingleStep(0.001)
        self.trigger_spin.setDecimals(3)
        self.trigger_spin.setValue(self.trigger_level)
        self.trigger_spin.valueChanged.connect(self.update_trigger_level)
        controls.addWidget(self.trigger_spin, 3, 1)

        controls.addWidget(QtWidgets.QLabel("Holdoff samples"), 3, 2)

        self.holdoff_spin = QtWidgets.QSpinBox()
        self.holdoff_spin.setRange(0, RAW_BUFFER_SAMPLES)
        self.holdoff_spin.setValue(self.trigger_holdoff_samples)
        self.holdoff_spin.valueChanged.connect(self.update_holdoff)
        controls.addWidget(self.holdoff_spin, 3, 3)

        self.notch_checkbox = QtWidgets.QCheckBox("Notch")
        self.notch_checkbox.setChecked(self.notch_enabled)
        self.notch_checkbox.stateChanged.connect(self.update_notch_enabled)
        controls.addWidget(self.notch_checkbox, 4, 0)

        controls.addWidget(QtWidgets.QLabel("Notch Hz"), 4, 1)

        self.notch_freq_spin = QtWidgets.QSpinBox()
        self.notch_freq_spin.setRange(
            1000,
            (ADC_SAMPLE_RATE_HZ // 2) - 1000
        )
        self.notch_freq_spin.setSingleStep(1000)
        self.notch_freq_spin.setValue(self.notch_freq_hz)
        self.notch_freq_spin.valueChanged.connect(self.update_notch_freq)
        controls.addWidget(self.notch_freq_spin, 4, 2)

        controls.addWidget(QtWidgets.QLabel("Notch r"), 4, 3)

        self.notch_r_spin = QtWidgets.QDoubleSpinBox()
        self.notch_r_spin.setRange(0.800, 0.995)
        self.notch_r_spin.setSingleStep(0.005)
        self.notch_r_spin.setDecimals(3)
        self.notch_r_spin.setValue(self.notch_r)
        self.notch_r_spin.valueChanged.connect(self.update_notch_r)
        controls.addWidget(self.notch_r_spin, 4, 4)

        controls.addWidget(QtWidgets.QLabel("Waveform smooth samples"), 5, 0)

        self.smooth_spin = QtWidgets.QSpinBox()
        self.smooth_spin.setRange(1, 101)
        self.smooth_spin.setSingleStep(2)
        self.smooth_spin.setValue(self.smoothing_samples)
        self.smooth_spin.valueChanged.connect(self.update_smoothing)
        controls.addWidget(self.smooth_spin, 5, 1)

        controls.addWidget(QtWidgets.QLabel("Trace smooth points"), 5, 2)

        self.trace_smooth_spin = QtWidgets.QSpinBox()
        self.trace_smooth_spin.setRange(1, 101)
        self.trace_smooth_spin.setSingleStep(2)
        self.trace_smooth_spin.setValue(self.trace_smoothing_points)
        self.trace_smooth_spin.valueChanged.connect(
            self.update_trace_smoothing
        )
        controls.addWidget(self.trace_smooth_spin, 5, 3)

        self.status_label = QtWidgets.QLabel("No averaged points yet")
        controls.addWidget(self.status_label, 6, 0, 1, 5)

        layout.addLayout(controls)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plot)
        self.timer.start(20)

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_button.setText(
            "Run" if self.paused else "Pause"
        )

    def export_csv(self):
        if len(self.completed_points) == 0:
            QtWidgets.QMessageBox.warning(
                self,
                "Export CSV",
                "No averaged data available to export."
            )
            return

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export capnogram trace",
            "capnogram_trace.csv",
            "CSV files (*.csv)"
        )

        if not path:
            return

        raw_x, raw_y, counts = self.build_raw_completed_arrays()
        smooth_y = self.smooth_trace(raw_y)

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "time_s",
                "averaged_peak_v",
                "smoothed_averaged_peak_v",
                "pulse_count"
            ])

            for t, y_raw, y_smooth, count in zip(
                raw_x,
                raw_y,
                smooth_y,
                counts
            ):
                writer.writerow([
                    float(t),
                    float(y_raw),
                    float(y_smooth),
                    int(count)
                ])

    def update_y_range(self):
        y_min = self.y_min_spin.value()
        y_max = self.y_max_spin.value()

        if y_max <= y_min:
            return

        self.plot.setYRange(y_min, y_max, padding=0)

    def update_display_seconds(self, value):
        self.display_seconds = float(value)
        self.plot.setXRange(-self.display_seconds, 0, padding=0)

    def update_bin_ms(self, value):
        self.bin_seconds = float(value) / 1000.0
        self.reset_bins()

    def update_trigger_level(self, value):
        self.trigger_level = float(value)

    def update_holdoff(self, value):
        self.trigger_holdoff_samples = int(value)

    def update_notch_enabled(self, state):
        self.notch_enabled = (
            state == QtCore.Qt.CheckState.Checked.value
        )

    def update_notch_freq(self, value):
        self.notch_freq_hz = int(value)

    def update_notch_r(self, value):
        self.notch_r = float(value)

    def update_smoothing(self, value):
        if value % 2 == 0:
            value += 1

            self.smooth_spin.blockSignals(True)
            self.smooth_spin.setValue(value)
            self.smooth_spin.blockSignals(False)

        self.smoothing_samples = int(value)

    def update_trace_smoothing(self, value):
        if value % 2 == 0:
            value += 1

            self.trace_smooth_spin.blockSignals(True)
            self.trace_smooth_spin.setValue(value)
            self.trace_smooth_spin.blockSignals(False)

        self.trace_smoothing_points = int(value)

    def reset_bins(self):
        self.current_bin_index = None
        self.current_bin_sum = 0.0
        self.current_bin_count = 0
        self.completed_points.clear()
        self.last_plot_x = np.array([], dtype=np.float32)
        self.last_plot_y = np.array([], dtype=np.float32)

    def moving_average(self, values, window):
        if len(values) == 0:
            return values

        if window <= 1:
            return values

        window = min(window, len(values))

        kernel = np.ones(window, dtype=np.float32) / window

        pad_left = window // 2
        pad_right = window - 1 - pad_left

        padded = np.pad(
            values,
            (pad_left, pad_right),
            mode="edge"
        )

        return np.convolve(padded, kernel, mode="valid")

    def notch_filter(self, values):
        if not self.notch_enabled:
            return values

        if len(values) < 3:
            return values

        f0 = float(self.notch_freq_hz)
        fs = float(ADC_SAMPLE_RATE_HZ)

        if f0 <= 0.0 or f0 >= fs / 2.0:
            return values

        r = self.notch_r
        w0 = 2.0 * np.pi * f0 / fs
        c = np.cos(w0)

        y = np.empty_like(values, dtype=np.float32)

        x1 = 0.0
        x2 = 0.0
        y1 = 0.0
        y2 = 0.0

        for i, x0 in enumerate(values.astype(np.float32)):
            y0 = (
                x0
                - 2.0 * c * x1
                + x2
                + 2.0 * r * c * y1
                - (r * r) * y2
            )

            y[i] = y0

            x2 = x1
            x1 = x0
            y2 = y1
            y1 = y0

        return y

    def smooth_waveform(self, volts):
        volts = self.notch_filter(volts)

        return self.moving_average(
            volts,
            self.smoothing_samples
        ).astype(np.float32)

    def smooth_trace(self, values):
        return self.moving_average(
            values,
            self.trace_smoothing_points
        ).astype(np.float32)

    def find_trigger_crossings(self, volts):
        trigger = self.trigger_level

        if self.trigger_mode == "Rising":
            crossings = np.where(
                (volts[:-1] < trigger)
                & (volts[1:] >= trigger)
            )[0] + 1

        elif self.trigger_mode == "Falling":
            crossings = np.where(
                (volts[:-1] > trigger)
                & (volts[1:] <= trigger)
            )[0] + 1

        else:
            rising = np.where(
                (volts[:-1] < trigger)
                & (volts[1:] >= trigger)
            )[0] + 1

            falling = np.where(
                (volts[:-1] > trigger)
                & (volts[1:] <= trigger)
            )[0] + 1

            crossings = np.sort(
                np.concatenate((rising, falling))
            )

        if self.trigger_holdoff_samples <= 0:
            return crossings

        accepted = []
        last = -self.trigger_holdoff_samples

        for idx in crossings:
            if idx - last >= self.trigger_holdoff_samples:
                accepted.append(idx)
                last = idx

        return np.array(accepted, dtype=np.int64)

    def add_peak_to_bin(self, event_time, peak):
        bin_index = int(event_time / self.bin_seconds)

        if self.current_bin_index is None:
            self.current_bin_index = bin_index

        while bin_index > self.current_bin_index:
            self.finish_current_bin()
            self.current_bin_index += 1
            self.current_bin_sum = 0.0
            self.current_bin_count = 0

        self.current_bin_sum += peak
        self.current_bin_count += 1

    def finish_current_bin(self):
        if self.current_bin_index is None:
            return

        if self.current_bin_count == 0:
            return

        bin_mid_time = (
            self.current_bin_index * self.bin_seconds
            + self.bin_seconds * 0.5
        )

        averaged_peak = (
            self.current_bin_sum / self.current_bin_count
        )

        self.completed_points.append(
            (
                bin_mid_time,
                averaged_peak,
                self.current_bin_count
            )
        )

    def force_complete_old_bins(self, latest_time):
        if self.current_bin_index is None:
            return

        latest_complete_bin = int(latest_time / self.bin_seconds) - 1

        while self.current_bin_index <= latest_complete_bin:
            self.finish_current_bin()
            self.current_bin_index += 1
            self.current_bin_sum = 0.0
            self.current_bin_count = 0

    def prune_completed_points(self, latest_time):
        oldest_time = latest_time - self.display_seconds - 1.0

        while (
            self.completed_points
            and self.completed_points[0][0] < oldest_time
        ):
            self.completed_points.popleft()

    def add_new_peaks_from_buffer(self, volts, buffer_start_abs):
        trigger_volts = self.smooth_waveform(volts)
        crossings = self.find_trigger_crossings(trigger_volts)

        new_count = 0

        for idx in crossings:
            abs_idx = buffer_start_abs + int(idx)

            if abs_idx <= self.last_processed_trigger_abs:
                continue

            start = idx - self.pre_trigger_samples
            end = idx + self.post_trigger_samples

            if start < 0:
                continue

            if end > len(volts):
                continue

            pulse = volts[start:end].copy()

            if self.subtract_baseline:
                baseline_end = self.pre_trigger_samples
                baseline_start = max(
                    0,
                    baseline_end - self.baseline_samples
                )

                if baseline_end > baseline_start:
                    baseline = np.mean(
                        pulse[baseline_start:baseline_end]
                    )

                    pulse = pulse - baseline

            pulse = self.smooth_waveform(pulse)

            peak = float(np.max(pulse))
            event_time = abs_idx / float(ADC_SAMPLE_RATE_HZ)

            self.add_peak_to_bin(event_time, peak)

            self.last_processed_trigger_abs = abs_idx
            new_count += 1

        return new_count

    def build_raw_completed_arrays(self):
        if len(self.completed_points) == 0:
            return (
                np.array([], dtype=np.float32),
                np.array([], dtype=np.float32),
                np.array([], dtype=np.int32)
            )

        xs = []
        ys = []
        counts = []

        for point_time, averaged_peak, count in self.completed_points:
            xs.append(point_time)
            ys.append(averaged_peak)
            counts.append(count)

        return (
            np.array(xs, dtype=np.float32),
            np.array(ys, dtype=np.float32),
            np.array(counts, dtype=np.int32)
        )

    def build_plot_arrays(self, latest_time):
        if len(self.completed_points) == 0:
            return (
                np.array([], dtype=np.float32),
                np.array([], dtype=np.float32)
            )

        xs = []
        ys = []

        for point_time, averaged_peak, _count in self.completed_points:
            relative_time = point_time - latest_time

            if relative_time < -self.display_seconds:
                continue

            if relative_time > 0:
                continue

            xs.append(relative_time)
            ys.append(averaged_peak)

        x = np.array(xs, dtype=np.float32)
        y = np.array(ys, dtype=np.float32)

        y = self.smooth_trace(y)

        return x, y

    def update_plot(self):
        if self.paused:
            return

        with lock:
            if len(rolling_volts) == 0:
                return

            volts = rolling_volts.copy()
            total_samples = total_samples_received
            status = latest_status

        buffer_start_abs = total_samples - len(volts)
        latest_time = total_samples / float(ADC_SAMPLE_RATE_HZ)

        new_peaks = self.add_new_peaks_from_buffer(
            volts,
            buffer_start_abs
        )

        self.force_complete_old_bins(latest_time)
        self.prune_completed_points(latest_time)

        x, y = self.build_plot_arrays(latest_time)

        self.curve.setData(x, y)

        self.last_plot_x = x.copy()
        self.last_plot_y = y.copy()

        self.plot.setXRange(-self.display_seconds, 0, padding=0)

        if len(y) > 0:
            latest_value = y[-1]
            latest_text = f"latest smoothed avg={latest_value:.3f} V"
        else:
            latest_text = "latest smoothed avg=n/a"

        self.status_label.setText(
            f"{status} | completed points={len(self.completed_points)} | "
            f"new peaks={new_peaks} | {latest_text}"
        )

        self.plot.setTitle(
            f"Capnogram style average | "
            f"{int(self.bin_seconds * 1000)} ms bins | "
            f"{self.trace_smoothing_points} point trace smoothing"
        )


app = QtWidgets.QApplication(sys.argv)

reader = threading.Thread(
    target=serial_thread,
    daemon=True
)

reader.start()

window = CapnogramWindow()
window.resize(1200, 700)
window.show()


def cleanup():
    global running

    running = False

    reader.join(timeout=1)


app.aboutToQuit.connect(cleanup)

sys.exit(app.exec())