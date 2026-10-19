# Robot Head

Arduino servo control and OAK camera tracking. Run these commands from the repository root.

Set up Python dependencies and upload the Arduino Uno firmware (once):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt platformio
pio run -d robot_head_arduino -t upload --upload-port /dev/ttyUSB0
```

Connect the Arduino and OAK camera, then run one script at a time:

```bash
python scripts/arm.py                           # Type commands such as: 1 90
python scripts/arm2.py                          # Smooth control with arrows/WASD; q quits
python scripts/person_follow.py --device 10.12.222.68  # Face tracking
python scripts/focused_person_follow.py --device-ip 10.12.222.68  # Focused tracking + point cloud (RVC4)
python scripts/cloud.py --device-ip 10.12.222.68  # Stereo depth + point cloud
```

Replace the camera IP as needed. Servo scripts default to `/dev/ttyUSB0`; use `--port` for `arm2.py`, `--serial-port` for `focused_person_follow.py`, or edit the port constant in the other servo scripts. Point clouds require calibrated CAM_A/CAM_D cameras.

Open <http://localhost:8082> for camera views. Add `--no-servos` to focused tracking to run without the Arduino.
