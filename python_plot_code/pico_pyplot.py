import sys
import struct
import threading
import time

import serial
import numpy as np
import pyqtgraph as pg
from PyQt6 import QtWidgets, QtCore

PORT = "COM6"
BAUD = 115200
EXPECTED_SAMPLES = 512

VREF = 3.3
ADC_MAX = 4095.0

MAGIC_BYTES = b"OCIP!CDA"

HEADER_REST_FMT = "<I H H"
HEADER_REST_SIZE = struct.calcsize(HEADER_REST_FMT)

latest_volts = None
latest_status = "Waiting..."
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
    global latest_volts, latest_status

    ser = serial.Serial(PORT, BAUD, timeout=0.1)
    ser.dtr = True
    ser.reset_input_buffer()

    bad_samples = 0
    bad_adc = 0
    bad_checksum = 0
    accepted = 0
    last_print = time.time()

    try:
        while running:
            if not wait_for_magic(ser):
                break

            rest = read_exact(ser, HEADER_REST_SIZE)
            if rest is None:
                break

            sequence, samples, checksum = struct.unpack(HEADER_REST_FMT, rest)

            if samples != EXPECTED_SAMPLES:
                bad_samples += 1
                continue

            raw = read_exact(ser, samples * 2)
            if raw is None:
                break

            adc_u16 = np.frombuffer(raw, dtype="<u2").copy()

            if adc_u16.max() > 4095:
                bad_adc += 1
                continue

            if checksum_u16(adc_u16) != checksum:
                bad_checksum += 1
                continue

            volts = adc_u16.astype(np.float32) * (VREF / ADC_MAX)
            accepted += 1

            status = (
                f"seq={sequence} | min={volts.min():.3f} V | max={volts.max():.3f} V | "
                f"ok={accepted} | badS={bad_samples} | badADC={bad_adc} | badCRC={bad_checksum}"
            )

            if time.time() - last_print > 1:
                print(status)
                last_print = time.time()

            with lock:
                latest_volts = volts
                latest_status = status

    finally:
        ser.close()


class ScopeWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Pico ADC Scope")

        self.paused = False
        self.trigger_enabled = True
        self.trigger_level = 1.0
        self.samples_displayed = EXPECTED_SAMPLES

        layout = QtWidgets.QVBoxLayout(self)

        self.plot_widget = pg.GraphicsLayoutWidget()
        self.plot = self.plot_widget.addPlot(title="Waiting for data...")
        self.plot.setLabel("bottom", "Sample")
        self.plot.setLabel("left", "Voltage", units="V")
        self.plot.setYRange(0, 3.3)
        self.plot.setXRange(0, EXPECTED_SAMPLES)
        self.plot.showGrid(x=True, y=True)

        self.curve = self.plot.plot()

        layout.addWidget(self.plot_widget)

        controls = QtWidgets.QGridLayout()

        self.pause_button = QtWidgets.QPushButton("Pause")
        self.pause_button.clicked.connect(self.toggle_pause)
        controls.addWidget(self.pause_button, 0, 0)

        self.trigger_checkbox = QtWidgets.QCheckBox("Trigger")
        self.trigger_checkbox.setChecked(True)
        self.trigger_checkbox.stateChanged.connect(self.update_trigger_enabled)
        controls.addWidget(self.trigger_checkbox, 0, 1)

        controls.addWidget(QtWidgets.QLabel("Trigger V"), 0, 2)
        self.trigger_spin = QtWidgets.QDoubleSpinBox()
        self.trigger_spin.setRange(0.0, 3.3)
        self.trigger_spin.setSingleStep(0.05)
        self.trigger_spin.setValue(self.trigger_level)
        self.trigger_spin.valueChanged.connect(self.update_trigger_level)
        controls.addWidget(self.trigger_spin, 0, 3)

        controls.addWidget(QtWidgets.QLabel("Y min"), 1, 0)
        self.y_min_spin = QtWidgets.QDoubleSpinBox()
        self.y_min_spin.setRange(-1.0, 3.3)
        self.y_min_spin.setSingleStep(0.05)
        self.y_min_spin.setValue(0.0)
        self.y_min_spin.valueChanged.connect(self.update_y_range)
        controls.addWidget(self.y_min_spin, 1, 1)

        controls.addWidget(QtWidgets.QLabel("Y max"), 1, 2)
        self.y_max_spin = QtWidgets.QDoubleSpinBox()
        self.y_max_spin.setRange(0.0, 5.0)
        self.y_max_spin.setSingleStep(0.05)
        self.y_max_spin.setValue(3.3)
        self.y_max_spin.valueChanged.connect(self.update_y_range)
        controls.addWidget(self.y_max_spin, 1, 3)

        controls.addWidget(QtWidgets.QLabel("Samples shown"), 2, 0)
        self.samples_spin = QtWidgets.QSpinBox()
        self.samples_spin.setRange(16, EXPECTED_SAMPLES)
        self.samples_spin.setSingleStep(16)
        self.samples_spin.setValue(EXPECTED_SAMPLES)
        self.samples_spin.valueChanged.connect(self.update_samples_displayed)
        controls.addWidget(self.samples_spin, 2, 1)

        controls.addWidget(QtWidgets.QLabel("Refresh ms"), 2, 2)
        self.refresh_spin = QtWidgets.QSpinBox()
        self.refresh_spin.setRange(5, 1000)
        self.refresh_spin.setSingleStep(5)
        self.refresh_spin.setValue(33)
        self.refresh_spin.valueChanged.connect(self.update_refresh_rate)
        controls.addWidget(self.refresh_spin, 2, 3)

        layout.addLayout(controls)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plot)
        self.timer.start(33)

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_button.setText("Run" if self.paused else "Pause")

    def update_trigger_enabled(self, state):
        self.trigger_enabled = state == QtCore.Qt.CheckState.Checked.value

    def update_trigger_level(self, value):
        self.trigger_level = value

    def update_y_range(self):
        y_min = self.y_min_spin.value()
        y_max = self.y_max_spin.value()

        if y_max <= y_min:
            return

        self.plot.setYRange(y_min, y_max)

    def update_samples_displayed(self, value):
        self.samples_displayed = value
        self.plot.setXRange(0, value)

    def update_refresh_rate(self, value):
        self.timer.start(value)

    def align_to_trigger(self, volts):
        if not self.trigger_enabled:
            return volts

        trigger = self.trigger_level

        crossings = np.where((volts[:-1] < trigger) & (volts[1:] >= trigger))[0]

        if len(crossings) == 0:
            return volts

        idx = crossings[0] + 1
        return np.roll(volts, -idx)

    def update_plot(self):
        if self.paused:
            return

        with lock:
            if latest_volts is None:
                return

            volts = latest_volts.copy()
            status = latest_status

        volts = self.align_to_trigger(volts)

        shown = volts[:self.samples_displayed]

        self.curve.setData(shown)
        self.plot.setTitle(status)


app = QtWidgets.QApplication(sys.argv)

reader = threading.Thread(target=serial_thread, daemon=True)
reader.start()

window = ScopeWindow()
window.resize(1000, 650)
window.show()


def cleanup():
    global running
    running = False
    reader.join(timeout=1)


app.aboutToQuit.connect(cleanup)
sys.exit(app.exec())