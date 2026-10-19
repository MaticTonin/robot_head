import os
import time

from dotenv import load_dotenv

import depthai as dai
from depthai_nodes.node import ApplyColormap, ImgFrameOverlay, ParsingNeuralNetwork

from utils.arguments import initialize_argparser
from utils.input import create_input_node


DEFAULT_PORT = "/dev/ttyUSB0"
DEFAULT_BAUD_RATE = 115200
SERVO_IDS = (1, 3)
SERVO_STARTUP_DELAY = 2.0
SERVO_START_ANGLE = 90
SERVO_MIN_ANGLE = 0
SERVO_MAX_ANGLE = 180
SERVO_STEP = 2
X_DEADZONE = 0.08
Y_DEADZONE = 0.08
DEFAULT_FACE_MODEL = "luxonis/yunet:320x240"


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


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


def connect_to_arm(port=DEFAULT_PORT):
    try:
        import serial
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "pyserial is not installed. Run 'pip install -r scripts/requirements.txt' or use the project virtualenv."
        ) from exc

    print(f"Connecting to {port}...")

    try:
        connection = serial.Serial(
            port,
            DEFAULT_BAUD_RATE,
            timeout=0,
            write_timeout=1,
        )
    except serial.SerialException as exc:
        raise SystemExit(f"Could not open serial port {port}: {exc}") from exc

    time.sleep(SERVO_STARTUP_DELAY)

    for line in read_available_lines(connection):
        print(f"Arduino: {line}")

    return connection


def initialize_servos(connection):
    servo_targets = {servo_id: SERVO_START_ANGLE for servo_id in SERVO_IDS}

    for servo_id, angle in servo_targets.items():
        send_angle(connection, servo_id, angle)

    for line in read_available_lines(connection):
        print(f"Arduino: {line}")

    return servo_targets


def is_face_detection(detection):
    label_name = getattr(detection, "labelName", "")
    if label_name:
        return label_name.lower() == "face"
    return getattr(detection, "label", None) == 0


def get_first_face_detection(detections_message):
    for detection in detections_message.detections:
        if is_face_detection(detection):
            return detection
    return None


def get_latest_message(queue):
    latest_message = None

    while True:
        message = queue.tryGet()
        if message is None:
            return latest_message
        latest_message = message


def update_servo_targets(face_detection, servo_targets, step=SERVO_STEP):
    x_error = face_detection.getCenterX() - 0.5
    y_error = 0.5 - face_detection.getCenterY()

    if x_error > X_DEADZONE:
        servo_targets[1] = clamp(servo_targets[1] - step, SERVO_MIN_ANGLE, SERVO_MAX_ANGLE)
    elif x_error < -X_DEADZONE:
        servo_targets[1] = clamp(servo_targets[1] + step, SERVO_MIN_ANGLE, SERVO_MAX_ANGLE)

    if y_error > Y_DEADZONE:
        servo_targets[3] = clamp(servo_targets[3] - step, SERVO_MIN_ANGLE, SERVO_MAX_ANGLE)
    elif y_error < -Y_DEADZONE:
        servo_targets[3] = clamp(servo_targets[3] + step, SERVO_MIN_ANGLE, SERVO_MAX_ANGLE)


def send_pending_servo_updates(connection, servo_targets, last_sent):
    for servo_id in SERVO_IDS:
        angle = int(round(servo_targets[servo_id]))
        if last_sent[servo_id] != angle:
            send_angle(connection, servo_id, angle)
            last_sent[servo_id] = angle

    for line in read_available_lines(connection):
        print(f"Arduino: {line}")


def main():
    load_dotenv(override=True)

    parser, args = initialize_argparser()

    if args.model == parser.get_default("model"):
        args.model = DEFAULT_FACE_MODEL

    if args.api_key:
        os.environ["DEPTHAI_HUB_API_KEY"] = args.api_key

    connection = connect_to_arm()
    try:
        servo_targets = initialize_servos(connection)
        last_sent = {servo_id: int(round(angle)) for servo_id, angle in servo_targets.items()}

        visualizer = dai.RemoteConnection(httpPort=8082)
        device = dai.Device(dai.DeviceInfo(args.device)) if args.device else dai.Device()
        platform = device.getPlatformAsString()
        print(f"Platform: {platform}")

        with dai.Pipeline(device) as pipeline:
            print("Creating pipeline...")
            camera_socket = dai.CameraBoardSocket.CAM_D

            if args.model.endswith(".tar.xz"):
                nn_archive = dai.NNArchive(args.model)
            else:
                model_description = dai.NNModelDescription(args.model, platform=platform)
                nn_archive = dai.NNArchive(dai.getModelFromZoo(model_description))

            input_node = create_input_node(
                pipeline,
                platform,
                args.media_path,
                camera_socket=camera_socket,
            )
            if not args.media_path:
                nn_width = nn_archive.getInputWidth()
                nn_height = nn_archive.getInputHeight()
                frame_type = (
                    dai.ImgFrame.Type.BGR888p
                    if platform == "RVC2"
                    else dai.ImgFrame.Type.BGR888i
                )
                rotate_image = pipeline.create(dai.node.ImageManip)
                rotate_image.initialConfig.addRotateDeg(180)
                rotate_image.setMaxOutputFrameSize(nn_width * nn_height * 3)
                input_node.requestOutput(
                    size=(nn_width, nn_height),
                    type=frame_type,
                    resizeMode=dai.ImgResizeMode.CROP,
                ).link(
                    rotate_image.inputImage
                )
                input_node = rotate_image.out

            nn_with_parser = pipeline.create(ParsingNeuralNetwork).build(
                input_node, nn_archive, fps=args.fps_limit
            )
            detections_queue = nn_with_parser.out.createOutputQueue(maxSize=1, blocking=False)

            if args.overlay_mode:
                apply_colormap_node = pipeline.create(ApplyColormap).build(nn_with_parser.out)
                overlay_frames_node = pipeline.create(ImgFrameOverlay).build(
                    nn_with_parser.passthrough,
                    apply_colormap_node.out,
                )
                visualizer.addTopic("Video", overlay_frames_node.out, "images")
            else:
                visualizer.addTopic("Video", nn_with_parser.passthrough, "images")
            visualizer.addTopic("Detections", nn_with_parser.out, "images")

            print("Pipeline created.")

            pipeline.start()
            visualizer.registerPipeline(pipeline)

            while pipeline.isRunning():
                detections_message = get_latest_message(detections_queue)
                if detections_message is not None:
                    face_detection = get_first_face_detection(detections_message)
                    if face_detection is not None:
                        update_servo_targets(face_detection, servo_targets)
                        send_pending_servo_updates(connection, servo_targets, last_sent)

                key = visualizer.waitKey(1)
                if key == ord("q"):
                    print("Got q key from the remote connection!")
                    break
    finally:
        connection.close()
        print("Disconnected.")


if __name__ == "__main__":
    main()
