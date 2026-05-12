import sys
import time
import struct
import threading

import serial
import numpy as np
import pyqtgraph as pg
from PyQt6 import QtWidgets, QtCore

PORT = "COM3"
BAUD = 115200
EXPECTED_SAMPLES = 1024

MAGIC_BYTES = b"OCIP"  # little-endian bytes for 0x5049434F
HEADER_REST_FMT = "<IIHH"  # sequence, overruns, samples, reserved
HEADER_REST_SIZE = struct.calcsize(HEADER_REST_FMT)

latest_adc = None
latest_status = "Waiting..."
lock = threading.Lock()
running = True

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

        if len(window) > 4:
            del window[0]

        if bytes(window) == MAGIC_BYTES:
            return True

    return False

def serial_thread():
    global latest_adc, latest_status, running

    ser = serial.Serial(PORT, BAUD, timeout=0.1)
    ser.reset_input_buffer()

    last_print = time.time()
    bad_samples = 0
    bad_adc = 0
    resyncs = 0

    try:
        while running:
            if not wait_for_magic(ser):
                break

            rest = read_exact(ser, HEADER_REST_SIZE)
            if rest is None:
                break

            sequence, overruns, samples, reserved = struct.unpack(HEADER_REST_FMT, rest)

            if samples != EXPECTED_SAMPLES:
                bad_samples += 1
                resyncs += 1
                continue

            raw = read_exact(ser, samples * 2)
            if raw is None:
                break

            adc = np.frombuffer(raw, dtype="<u2").copy()

            if adc.max() > 4095:
                bad_adc += 1
                resyncs += 1
                continue

            status = (
                f"seq={sequence}, overruns={overruns}, "
                f"min={adc.min()}, max={adc.max()}, "
                f"badS={bad_samples}, badADC={bad_adc}, resyncs={resyncs}"
            )

            now = time.time()
            if now - last_print >= 1.0:
                print(status, "first10=", adc[:10].tolist())
                last_print = now

            with lock:
                latest_adc = adc
                latest_status = status

    finally:
        ser.close()

app = QtWidgets.QApplication(sys.argv)

win = pg.GraphicsLayoutWidget(show=True, title="Pico ADC Resync Debug")
plot = win.addPlot(title="Waiting for data...")
plot.setLabel("bottom", "Sample")
plot.setLabel("left", "ADC count")
plot.setYRange(0, 4095)

curve = plot.plot()

reader = threading.Thread(target=serial_thread, daemon=True)
reader.start()

def update_plot():
    with lock:
        if latest_adc is None:
            return
        adc = latest_adc.copy()
        status = latest_status

    curve.setData(adc)
    plot.setTitle(status)

timer = QtCore.QTimer()
timer.timeout.connect(update_plot)
timer.start(100)

def cleanup():
    global running
    running = False
    reader.join(timeout=1)

app.aboutToQuit.connect(cleanup)
sys.exit(app.exec())