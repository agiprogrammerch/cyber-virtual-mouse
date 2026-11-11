#!/bin/bash
# Hand Mouse Control Launcher
# This wrapper ensures proper environment for GUI apps launched from desktop

export QT_QPA_PLATFORM=xcb
export OPENCV_VIDEOIO_PRIORITY_MSMF=0
export PATH="/home/agi_programmer/anaconda3/bin:$PATH"

cd /home/agi_programmer/cyber-virtual-mouse
exec /home/agi_programmer/anaconda3/bin/python3 hand_mouse_control.py