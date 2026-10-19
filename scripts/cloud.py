#!/usr/bin/env python3

"""Stereo depth and point cloud from the IMX586 cameras on CAM_A and CAM_D."""

import argparse

import depthai as dai
from depthai_nodes.node import ApplyDepthColormap


CAMERA_SOCKETS = {
    dai.CameraBoardSocket.CAM_A,
    dai.CameraBoardSocket.CAM_D,
}
OUTPUT_SIZE = (1280, 720)
COLOR_SIZE = (3840, 2160)
COLOR_DISPLAY_SIZE = (960, 540)
POINT_CLOUD_SIZE = (320, 180)
FPS = 30.0
VISUALIZER_PORT = 8082


def parseArgs():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--device-ip",
        default="10.12.222.68",
        help="PoE device IP address (default: %(default)s)",
    )
    return parser.parse_args()


def getStereoSockets(calibrationHandler):
    eeprom = calibrationHandler.getEepromData()
    rectification = eeprom.stereoRectificationData
    leftSocket = rectification.leftCameraSocket
    rightSocket = rectification.rightCameraSocket

    if {leftSocket, rightSocket} != CAMERA_SOCKETS:
        raise RuntimeError(
            "Expected the calibrated stereo pair to be CAM_A/CAM_D, but EEPROM "
            f"contains {leftSocket.name}/{rightSocket.name}."
        )

    return leftSocket, rightSocket


def createPointCloud(pipeline, stereo, rightCamera, fps=FPS):
    # Align depth to a small color output from the same camera. RGBD handles
    # synchronization and intrinsics while keeping the 3D stream manageable.
    rgbd = pipeline.create(dai.node.RGBD).build(
        rightCamera, stereo, size=POINT_CLOUD_SIZE, fps=fps
    )
    # Interpret the raw depth numbers as metres, even though stereo labels
    # them as millimetres. Do not apply the usual division by 1,000.
    rgbd.setDepthUnits(dai.LengthUnit.METER)

    return rgbd.pcl


def main():
    args = parseArgs()
    visualizer = dai.RemoteConnection(httpPort=VISUALIZER_PORT)
    device = dai.Device(dai.DeviceInfo(args.device_ip))

    with dai.Pipeline(device) as pipeline:
        calibrationHandler = device.readCalibration()
        leftSocket, rightSocket = getStereoSockets(calibrationHandler)
        print(f"Using calibrated stereo pair: {leftSocket.name} -> {rightSocket.name}")

        leftCamera = pipeline.create(dai.node.Camera).build(leftSocket, sensorFps=FPS)
        rightCamera = pipeline.create(dai.node.Camera).build(rightSocket, sensorFps=FPS)

        leftFocus = calibrationHandler.getLensPosition(leftSocket)
        rightFocus = calibrationHandler.getLensPosition(rightSocket)
        leftCamera.initialControl.setManualFocus(leftFocus)
        rightCamera.initialControl.setManualFocus(rightFocus)
        """print(
            "Using calibrated focus positions: "
            f"{leftSocket.name}={leftFocus}, {rightSocket.name}={rightFocus}"
        )"""

        # StereoDepth accepts inputs up to 1280 pixels wide. requestOutput makes
        # each 8000x6000 IMX586 use a downscaled 1280x720 ISP output.
        leftOutput = leftCamera.requestOutput(
            OUTPUT_SIZE, fps=FPS, enableUndistortion=False
        )
        rightOutput = rightCamera.requestOutput(
            OUTPUT_SIZE, fps=FPS, enableUndistortion=False
        )
        leftColorOutput = leftCamera.requestOutput(
            COLOR_SIZE, fps=FPS, enableUndistortion=False
        )
        rightColorOutput = rightCamera.requestOutput(
            COLOR_SIZE, fps=FPS, enableUndistortion=False
        )

        leftColorPreview = pipeline.create(dai.node.ImageManip)
        rightColorPreview = pipeline.create(dai.node.ImageManip)
        manipBackend = (
            dai.node.ImageManip.Backend.GPU
            if device.hasGPU()
            else dai.node.ImageManip.Backend.CPU
        )
        for colorOutput, preview in (
            (leftColorOutput, leftColorPreview),
            (rightColorOutput, rightColorPreview),
        ):
            preview.setBackend(manipBackend)
            preview.initialConfig.setOutputSize(
                *COLOR_DISPLAY_SIZE, dai.ImageManipConfig.ResizeMode.STRETCH
            )
            colorOutput.link(preview.inputImage)

        stereo = pipeline.create(dai.node.StereoDepth)
        stereo.setRectification(True)
        stereo.setSubpixel(True)
        stereo.setDepthAlign(rightSocket)

        leftOutput.link(stereo.left)
        rightOutput.link(stereo.right)

        depthColor = pipeline.create(ApplyDepthColormap).build(stereo.depth)
        # Process Python callbacks in the main loop so they finish before
        # shutdown closes their output queues.
        depthColor.sendProcessingToPipeline(True)
        pointCloud = createPointCloud(pipeline, stereo, rightCamera)

        visualizer.addTopic("Depth (metres)", depthColor.out, group="Stereo")
        visualizer.addTopic("Point cloud (metres)", pointCloud, group="Point cloud")
        visualizer.addTopic(
            "Rectified left", stereo.rectifiedLeft, group="Stereo"
        )
        visualizer.addTopic(
            "Rectified right", stereo.rectifiedRight, group="Stereo"
        )
        # Only transfer the downscaled previews to the host. Sending two raw 4K
        # streams over XLink can backpressure the camera branches and break the
        # synchronization required by StereoDepth.
        visualizer.addTopic(
            f"{leftSocket.name} color 4K", leftColorPreview.out, group="Color"
        )
        visualizer.addTopic(
            f"{rightSocket.name} color 4K", rightColorPreview.out, group="Color"
        )

        pipeline.start()
        visualizer.registerPipeline(pipeline)
        print(
            f"Open http://localhost:{VISUALIZER_PORT} in Chrome to view the streams."
        )
        print("Depth and point-cloud values are interpreted as metres without rescaling.")
        try:
            while pipeline.isRunning():
                pipeline.processTasks()
                if visualizer.waitKey(1) == ord("q"):
                    break
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
