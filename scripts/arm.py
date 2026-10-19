import serial
import time

# -------------------------
# CONFIGURATION
# -------------------------

PORT = "/dev/ttyUSB0"   # Linux
# PORT = "COM5"         # Windows example

BAUD_RATE = 115200


# -------------------------
# CONNECT
# -------------------------

print(f"Connecting to {PORT}...")

ser = serial.Serial(
    PORT,
    BAUD_RATE,
    timeout=1
)

# Arduino normally resets when USB serial is opened
time.sleep(2)

# Clear anything Arduino printed during startup
while ser.in_waiting:
    print("Arduino:", ser.readline().decode(errors="replace").strip())


# -------------------------
# TERMINAL CONTROL
# -------------------------

print()
print("Adeept Arm Controller")
print("---------------------")
print("Servo 1 = D9")
print("Servo 3 = D5")
print()
print("Commands:")
print("  1 90     -> Servo 1 to 90 degrees")
print("  3 120    -> Servo 3 to 120 degrees")
print("  q        -> quit")
print()


while True:

    command = input("> ").strip()

    if command.lower() in ("q", "quit", "exit"):
        break

    parts = command.split()

    if len(parts) != 2:
        print("Use: <servo> <angle>")
        print("Example: 1 90")
        continue

    try:
        servo_number = int(parts[0])
        angle = int(parts[1])
    except ValueError:
        print("Servo and angle must be numbers.")
        continue

    if servo_number not in (1, 3):
        print("Servo must be 1 or 3.")
        continue

    if not 0 <= angle <= 180:
        print("Angle must be 0-180.")
        continue

    # Send to Arduino
    ser.write(f"{servo_number} {angle}\n".encode())
    ser.flush()

    # Read Arduino response
    response = ser.readline().decode(errors="replace").strip()

    if response:
        print(response)


# -------------------------
# CLEANUP
# -------------------------

ser.close()
print("Disconnected.")