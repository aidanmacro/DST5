import serial

PORT = "COM6"
BAUD = 115200

ser = serial.Serial(PORT, BAUD, timeout=1)
ser.dtr = True
ser.reset_input_buffer()

print("opened", PORT)

while True:
    data = ser.read(64)
    if data:
        print(data, len(data))