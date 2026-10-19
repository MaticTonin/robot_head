#!/usr/bin/env python3

import argparse
import curses
import time
from collections import deque


DEFAULT_PORT = "/dev/ttyUSB0"
DEFAULT_BAUD_RATE = 115200
SERVO_IDS = (1, 3)


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def ramp_toward(current, target, max_delta):
    if target > current:
        return min(target, current + max_delta)
    if target < current:
        return max(target, current - max_delta)
    return current


def read_available_lines(connection):
    lines = []

    while connection.in_waiting:
        line = connection.readline().decode(errors="replace").strip()
        if line:
            lines.append(line)

    return lines


def send_angle(connection, servo_id, angle):
    connection.write(f"{servo_id} {angle}\n".encode())
    connection.flush()


def safe_add_line(stdscr, row, text):
    height, width = stdscr.getmaxyx()
    if row < 0 or row >= height:
        return

    stdscr.addnstr(row, 0, text, max(1, width - 1))


def draw_screen(stdscr, state):
    stdscr.erase()
    safe_add_line(stdscr, 0, "Adeept Arm Smooth Terminal Controller")
    safe_add_line(stdscr, 1, "-" * 38)
    safe_add_line(stdscr, 3, f"Port: {state['port']}  Baud: {state['baud_rate']}")
    safe_add_line(stdscr, 4, f"Step: {state['step']} deg/key  Speed: {state['speed']:.0f} deg/s")
    safe_add_line(stdscr, 5, f"Limits: {state['min_angle']}..{state['max_angle']}")
    safe_add_line(stdscr, 7, "Servo 1 (left/right, a/d)")
    safe_add_line(
        stdscr,
        8,
        f"  target={state['targets'][1]:6.1f} deg   current={state['currents'][1]:6.1f} deg",
    )
    safe_add_line(stdscr, 10, "Servo 3 (up/down, w/s)")
    safe_add_line(
        stdscr,
        11,
        f"  target={state['targets'][3]:6.1f} deg   current={state['currents'][3]:6.1f} deg",
    )
    safe_add_line(stdscr, 13, "Controls:")
    safe_add_line(stdscr, 14, "  arrows or WASD  move targets")
    safe_add_line(stdscr, 15, "  +/-             change angle step size")
    safe_add_line(stdscr, 16, "  [ / ]           change motion speed")
    safe_add_line(stdscr, 17, "  c               center both servos")
    safe_add_line(stdscr, 18, "  q               quit")
    safe_add_line(stdscr, 20, "Arduino messages:")

    row = 21
    for message in state["messages"]:
        safe_add_line(stdscr, row, message)
        row += 1

    stdscr.refresh()


def adjust_target(targets, servo_id, delta, minimum, maximum):
    targets[servo_id] = clamp(targets[servo_id] + delta, minimum, maximum)


def run_controller(stdscr, args, connection):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)

    targets = {servo_id: float(args.start_angle) for servo_id in SERVO_IDS}
    currents = {servo_id: float(args.start_angle) for servo_id in SERVO_IDS}
    last_sent = {servo_id: None for servo_id in SERVO_IDS}
    messages = deque(maxlen=8)

    time.sleep(args.startup_delay)
    for line in read_available_lines(connection):
        messages.append(line)

    step = args.step
    speed = float(args.speed)
    frame_delay = 1.0 / args.refresh_hz
    last_time = time.monotonic()
    running = True

    while running:
        while True:
            key = stdscr.getch()
            if key == -1:
                break

            if key in (ord("q"), ord("Q")):
                running = False
            elif key in (curses.KEY_LEFT, ord("a"), ord("A")):
                adjust_target(targets, 1, -step, args.min_angle, args.max_angle)
            elif key in (curses.KEY_RIGHT, ord("d"), ord("D")):
                adjust_target(targets, 1, step, args.min_angle, args.max_angle)
            elif key in (curses.KEY_UP, ord("w"), ord("W")):
                adjust_target(targets, 3, step, args.min_angle, args.max_angle)
            elif key in (curses.KEY_DOWN, ord("s"), ord("S")):
                adjust_target(targets, 3, -step, args.min_angle, args.max_angle)
            elif key in (ord("+"), ord("=")):
                step = clamp(step + 1, 1, 30)
            elif key in (ord("-"), ord("_")):
                step = clamp(step - 1, 1, 30)
            elif key == ord("["):
                speed = clamp(speed - 10.0, 10.0, 360.0)
            elif key == ord("]"):
                speed = clamp(speed + 10.0, 10.0, 360.0)
            elif key in (ord("c"), ord("C")):
                for servo_id in SERVO_IDS:
                    targets[servo_id] = float(args.center_angle)

        now = time.monotonic()
        dt = now - last_time
        last_time = now
        max_delta = speed * dt

        for servo_id in SERVO_IDS:
            currents[servo_id] = ramp_toward(currents[servo_id], targets[servo_id], max_delta)
            angle_to_send = int(round(currents[servo_id]))

            if last_sent[servo_id] != angle_to_send:
                send_angle(connection, servo_id, angle_to_send)
                last_sent[servo_id] = angle_to_send

        for line in read_available_lines(connection):
            messages.append(line)

        draw_screen(
            stdscr,
            {
                "port": args.port,
                "baud_rate": args.baud_rate,
                "step": step,
                "speed": speed,
                "min_angle": args.min_angle,
                "max_angle": args.max_angle,
                "targets": targets,
                "currents": currents,
                "messages": messages,
            },
        )

        elapsed = time.monotonic() - now
        time.sleep(max(0.0, frame_delay - elapsed))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Smooth terminal controller for the two arm servos."
    )
    parser.add_argument("--port", default=DEFAULT_PORT, help="Serial port for the Arduino.")
    parser.add_argument("--baud-rate", type=int, default=DEFAULT_BAUD_RATE, help="Serial baud rate.")
    parser.add_argument(
        "--startup-delay",
        type=float,
        default=2.0,
        help="Seconds to wait after opening serial so the Arduino can reset.",
    )
    parser.add_argument(
        "--refresh-hz",
        type=float,
        default=30.0,
        help="Terminal and control loop refresh rate.",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=90.0,
        help="Maximum servo speed in degrees per second.",
    )
    parser.add_argument(
        "--step",
        type=int,
        default=4,
        help="Target angle change per key press.",
    )
    parser.add_argument(
        "--start-angle",
        type=int,
        default=90,
        help="Initial angle assumed for both servos when the script starts.",
    )
    parser.add_argument(
        "--center-angle",
        type=int,
        default=90,
        help="Angle to use when you press c to re-center.",
    )
    parser.add_argument("--min-angle", type=int, default=0, help="Minimum allowed target angle.")
    parser.add_argument("--max-angle", type=int, default=180, help="Maximum allowed target angle.")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.min_angle > args.max_angle:
        raise SystemExit("--min-angle must be less than or equal to --max-angle")
    if args.refresh_hz <= 0:
        raise SystemExit("--refresh-hz must be greater than 0")
    if args.speed <= 0:
        raise SystemExit("--speed must be greater than 0")
    if args.step <= 0:
        raise SystemExit("--step must be greater than 0")

    args.start_angle = clamp(args.start_angle, args.min_angle, args.max_angle)
    args.center_angle = clamp(args.center_angle, args.min_angle, args.max_angle)

    try:
        import serial
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "pyserial is not installed. Run 'pip install -r scripts/requirements.txt' or use the project virtualenv."
        ) from exc

    print(f"Connecting to {args.port}...")

    try:
        connection = serial.Serial(
            args.port,
            args.baud_rate,
            timeout=0,
            write_timeout=1,
        )
    except serial.SerialException as exc:
        raise SystemExit(f"Could not open serial port {args.port}: {exc}") from exc

    try:
        curses.wrapper(run_controller, args, connection)
    finally:
        connection.close()
        print("Disconnected.")


if __name__ == "__main__":
    main()
