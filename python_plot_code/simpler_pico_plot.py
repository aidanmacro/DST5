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

HEADER_FMT = "<IIIHH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MAGIC = 0x5049434F
EXPECTED_SAMPLES = 4096

latest_adc = None
latest_sequence = 0
latest_overruns = 0
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

    return buf if got == n else None

def serial_thread():
    global latest_adc, latest_sequence, latest_overruns, running

    ser = serial.Serial(PORT, BAUD, timeout=0.1)
    ser.reset_input_buffer()

    try:
        while running:
            header = read_exact(ser, HEADER_SIZE)
            if header is None:
                break

            magic, sequence, overruns, samples, reserved = struct.unpack(HEADER_FMT, header)

            if magic != MAGIC or samples != EXPECTED_SAMPLES:
                ser.reset_input_buffer()
                continue

            raw = read_exact(ser, samples * 2)
            if raw is None:
                break

            adc = np.frombuffer(raw, dtype="<u2").copy()

            with lock:
                latest_adc = adc
                latest_sequence = sequence
                latest_overruns = overruns

    finally:
        ser.close()

app = QtWidgets.QApplication(sys.argv)

win = pg.GraphicsLayoutWidget(show=True, title="Pico ADC Stream")
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
        seq = latest_sequence
        ovs = latest_overruns

    curve.setData(adc)
    plot.setTitle(f"seq={seq}, overruns={ovs}")

timer = QtCore.QTimer()
timer.timeout.connect(update_plot)
timer.start(33)  # about 30 FPS max

def cleanup():
    global running
    running = False
    reader.join(timeout=1)

app.aboutToQuit.connect(cleanup)
sys.exit(app.exec())