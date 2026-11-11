# Cyber Virtual Mouse

**Developer:** Agi Hacker

A hand-tracking virtual mouse for Linux. Control your mouse cursor with your
index finger tip using a regular webcam. Built with OpenCV, MediaPipe
Hand Landmarker, and PyAutoGUI.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [How It Works](#how-it-works)
- [Requirements](#requirements)
- [Installation (Debian-based Linux)](#installation-debian-based-linux)
- [Running the Project](#running-the-project)
- [Desktop Launcher Setup (GNOME)](#desktop-launcher-setup-gnome)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)
- [License](#license)

---

## Overview

The application tracks your hand through the webcam using Google's
MediaPipe Hand Landmarker model (21 landmarks per hand). The tip of your
**index finger** (landmark 8) drives the mouse cursor: its position inside
a center "tracking box" of the camera frame is mapped linearly to your
full screen resolution.

The current version focuses **only on high-accuracy cursor control** —
all click, scroll, and drag gestures have been removed to keep the
tracking precise and jitter-free.

### How It Works

1. The webcam feed is mirrored for natural interaction.
2. MediaPipe detects the hand and returns 21 normalized landmarks.
3. The index finger tip (landmark 8) is mapped from the tracking box
   (center ~60% of the frame) to the full screen, clamped at the edges.
4. An Exponential Moving Average (EMA) filter smooths the raw position to
   remove jitter while keeping latency low.
5. PyAutoGUI moves the OS cursor to the smoothed position at ~30 FPS.

---

## Features

- **High-accuracy cursor control** via index finger tip tracking
- **EMA smoothing** with tunable alpha (smoothing vs. responsiveness)
- **Tracking box mapping** — center region of the frame maps 1:1 to the
  full screen; cursor never leaves the screen (edge clamping)
- **Live debug GUI** — shows the raw target, the smoothed cursor, the
  index tip landmark, hand detection status, and FPS
- **Adjustable trackbars** — tune smoothing and tracking box size live
- **Camera fallback** — tries the default backend, then V4L2 (Asus
  VivoBook friendly)
- **X11 auto-fix** — attempts `xhost +local:` automatically if the
  display connection fails
- **Failsafe** — slam the mouse into a screen corner to abort (PyAutoGUI
  FAILSAFE)
- **Automatic model download** — fetches `hand_landmarker.task` on first
  run

---

## Requirements

### Software

| Package          | Tested Version | Purpose                     |
|------------------|----------------|-----------------------------|
| Python           | 3.13.x         | Runtime                     |
| opencv-python    | 4.13.0         | Camera capture + GUI        |
| mediapipe        | 0.10.35        | Hand landmark detection     |
| PyAutoGUI        | 0.9.54         | Mouse control               |
| numpy            | 2.3.5          | Numeric backend             |

### Hardware / OS

- A webcam (built-in laptop camera works)
- Linux with **X11** display server (Wayland is not supported by
  PyAutoGUI's Xlib backend)
- ~200 MB free space for the MediaPipe model

---

## Installation (Debian-based Linux)

Tested on Kali Linux with GNOME Shell 50.4. Works on any Debian-based
distribution (Ubuntu, Debian, Kali, Pop!_OS, etc.).

### Step 1 — Install system prerequisites

```bash
sudo apt update
sudo apt install -y \
    python3 python3-pip \
    libgl1 libglib2.0-0 \
    x11-xserver-utils \
    v4l-utils
```

> `libgl1` and `glib` are runtime dependencies of OpenCV;
> `x11-xserver-utils` provides `xhost` for the X11 auto-fix;
> `v4l-utils` helps with camera diagnostics.

### Step 2 — Install Python dependencies

Using your preferred Python (system or conda):

```bash
pip install opencv-python mediapipe PyAutoGUI numpy
```

Or with the system package manager where available:

```bash
sudo apt install -y python3-opencv python3-pyautogui
pip install mediapipe   # mediapipe is not in Debian repos, install via pip
```

<details>
<summary>Using conda (as on the developer's machine)</summary>

```bash
conda activate base   # or your env
pip install opencv-python mediapipe PyAutoGUI numpy
```

The bundled launcher (`launch_hand_mouse.sh`) hard-codes the conda
Python path. If you use a different Python, edit that path (see
[Desktop Launcher Setup](#desktop-launcher-setup-gnome)).

</details>

### Step 3 — Verify the installation

```bash
python3 -c "import cv2, mediapipe, pyautogui, numpy; print('All dependencies OK')"
```

### Step 4 — Allow camera access (if using Flatpak'd browser etc.)

The app accesses `/dev/video0` directly, which normally needs no extra
permissions for desktop users. If the camera fails to open, check:

```bash
# List cameras
v4l2-ctl --list-devices

# Check your user is in the video group
groups | grep video
```

### Step 5 — Ensure an X11 session (not Wayland)

PyAutoGUI requires X11. On GNOME you can select *"GNOME on Xorg"* at the
login screen (gear icon). The script also sets
`QT_QPA_PLATFORM=xcb` to avoid Qt/Wayland conflicts automatically.

---

## Running the Project

### From the terminal

```bash
cd ~/cyber-virtual-mouse
python3 hand_mouse_control.py
```

The MediaPipe model (`hand_landmarker.task`, ~7.5 MB) downloads
automatically on first run.

### From the launcher script

```bash
./launch_hand_mouse.sh
```

This wrapper exports the required environment variables and uses the
conda Python explicitly.

### Controls while running

| Action                     | Effect                                   |
|----------------------------|------------------------------------------|
| Move index finger in frame | Moves the mouse cursor                   |
| Press `q` in GUI window    | Quit                                     |
| Press `g` in GUI window    | Toggle the debug GUI on/off              |
| Move cursor to screen corner| Emergency abort (PyAutoGUI FAILSAFE)     |

**Usage tip:** keep your index finger tip inside the green *Tracking
Area* box in the preview. The box maps to the entire screen, so small
movements of your finger translate to large cursor movements.

---

## Desktop Launcher Setup (GNOME)

The repo ships two desktop entry files.

### Option A — Applications menu (recommended)

```bash
mkdir -p ~/.local/share/applications
cp hand-mouse-control.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications/
```

Press the **Super** key, type *"Hand Mouse Control"*, and click to launch.

### Option B — Desktop icon

```bash
cp hand-mouse-control.desktop ~/Desktop/
chmod +x ~/Desktop/hand-mouse-control.desktop
```

GNOME treats desktop launchers as untrusted by default. Enable desktop
icons, then allow the launcher once:

```bash
gsettings set org.gnome.desktop.background show-desktop-icons true
```

Then **right-click the desktop icon → "Allow Launching"**, and
double-click to start.

### Using a different Python path

`hand-mouse-control.desktop` executes `launch_hand_mouse.sh`. To point it
at another interpreter, edit the last line of the script:

```bash
exec /path/to/your/python3 hand_mouse_control.py
```

---

## Configuration

All settings live in the `Config` class at the top of
`hand_mouse_control.py`, and the most useful ones are adjustable live
via GUI trackbars.

| Setting               | Default | Meaning                                                                 |
|-----------------------|---------|-------------------------------------------------------------------------|
| `SMOOTHING_ALPHA`    | 0.15    | EMA factor. Lower = smoother but laggier; higher = snappier but jittery |
| `TRACKING_BOX_RATIO`  | 0.6     | Size of the active tracking region (center % of camera frame)            |
| `CAMERA_WIDTH/HEIGHT` | 640x480 | Capture resolution                                                      |
| `DETECTION_CONFIDENCE`| 0.7     | MediaPipe hand detection confidence                                     |
| `SHOW_GUI`            | True    | Show the debug GUI window                                               |

### Tuning for accuracy

- **Cursor too jittery** → lower `SMOOTHING_ALPHA` (e.g. 0.08)
- **Cursor feels laggy** → raise `SMOOTHING_ALPHA` (e.g. 0.3)
- **Have to move your hand too much** → lower `TRACKING_BOX_RATIO` (e.g. 0.5)
- **Cursor jumps at frame edges** → raise `TRACKING_BOX_RATIO` (e.g. 0.7)

---

## Troubleshooting

### `Xlib.error.DisplayConnectionError: Can't connect to display ":0"`

Your X session requires authorization. Run:

```bash
xhost +local:
```

Then retry. The script also attempts this fix automatically.

### Camera fails to open

```bash
# Check if a camera exists
ls /dev/video*

# See which process holds the camera
sudo fuser /dev/video0
```

Close other apps using the webcam (browser, Zoom, cheese) and retry. The
app automatically retries with the V4L2 backend.

### Program runs but cursor doesn't move

- Make sure you are on **X11**, not Wayland (`echo $XDG_SESSION_TYPE`).
- Move your hand into the green tracking box — the status indicator
  should say **HAND DETECTED**.

### Icon doesn't launch from GNOME desktop

1. Verify desktop icons are enabled:
   `gsettings get org.gnome.desktop.background show-desktop-icons`
2. Right-click the icon → **Allow Launching**.
3. Confirm the `Exec=` path in the `.desktop` file is correct.

---

## Project Structure

```
cyber-virtual-mouse/
├── hand_mouse_control.py            # Main application (cursor control)
├── launch_hand_mouse.sh             # Desktop launcher wrapper script
├── hand-mouse-control.desktop       # GNOME desktop entry (menu/desktop)
├── hand-mouse-control-terminal.desktop  # Desktop entry w/ terminal output
├── hand_landmarker.task             # MediaPipe model (auto-downloaded)
├── README.md                        # This file
└── __pycache__/                     # Python bytecode cache
```

---

## License

All rights reserved © Agi Hacker. For personal and educational use.
