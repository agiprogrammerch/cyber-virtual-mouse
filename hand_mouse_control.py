#!/usr/bin/env python3
"""
Hand Tracking Mouse Cursor Control for Kali Linux / Asus VivoBook
Uses OpenCV, MediaPipe Tasks API (v0.10+), and PyAutoGUI.

Features:
- High-accuracy cursor control via index finger tip tracking
- Exponential Moving Average smoothing (adjustable alpha)
- Center tracking box mapping to full screen resolution
- Robust coordinate mapping with edge clamping
- Camera fallback for Asus VivoBook (V4L2)
- X11 error handling with auto-fix attempt
- Minimal GUI for debugging/tuning
"""

# Fix Qt/Wayland conflicts BEFORE importing cv2
import os
os.environ['QT_QPA_PLATFORM'] = 'xcb'  # Force X11 backend for GUI
os.environ['OPENCV_VIDEOIO_PRIORITY_MSMF'] = '0'

import cv2
import sys
import math
import time
import subprocess
import logging
from collections import deque

# Suppress MediaPipe/TensorFlow logging
logging.getLogger('absl').setLevel(logging.ERROR)
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

# MediaPipe Tasks API (v0.10+)
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision


# ==================== CONFIGURATION ====================
class Config:
    # Smoothing - lower = smoother but more latency, higher = more responsive
    SMOOTHING_ALPHA = 0.15          # EMA factor (0.05-0.3 recommended for accuracy)
    
    # Tracking box - center region of camera frame mapped to full screen
    TRACKING_BOX_RATIO = 0.6        # Center box % of frame (0.4-0.7)
    
    # Camera resolution
    CAMERA_WIDTH = 640
    CAMERA_HEIGHT = 480
    
    # MediaPipe confidence thresholds
    DETECTION_CONFIDENCE = 0.7
    PRESENCE_CONFIDENCE = 0.5
    TRACKING_CONFIDENCE = 0.5
    
    # GUI
    GUI_WIDTH = 300
    GUI_HEIGHT = 400
    SHOW_GUI = True
    
    MODEL_PATH = "hand_landmarker.task"

config = Config()


# ==================== COORDINATE MAPPING ====================
def euclidean_distance(p1, p2):
    return math.sqrt((p1.x - p2.x) ** 2 + (p1.y - p2.y) ** 2)


def map_tracking_box_to_screen(landmark, frame_width, frame_height, box_x, box_y, box_w, box_h, screen_width, screen_height):
    """
    Map landmark from tracking box to screen coordinates.
    Clamps to tracking box edges - cursor never leaves screen.
    """
    # Convert normalized landmark to pixel coordinates
    px = landmark.x * frame_width
    py = landmark.y * frame_height

    # Clamp to tracking box boundaries
    px = max(box_x, min(px, box_x + box_w))
    py = max(box_y, min(py, box_y + box_h))

    # Normalize within tracking box (0.0 to 1.0)
    norm_x = (px - box_x) / box_w
    norm_y = (py - box_y) / box_h

    # Map to screen coordinates
    screen_x = int(norm_x * (screen_width - 1))
    screen_y = int(norm_y * (screen_height - 1))

    return screen_x, screen_y


def apply_smoothing(current_x, current_y, target_x, target_y, alpha):
    """Exponential Moving Average smoothing."""
    smoothed_x = int(current_x * (1 - alpha) + target_x * alpha)
    smoothed_y = int(current_y * (1 - alpha) + target_y * alpha)
    return smoothed_x, smoothed_y


# ==================== X11 / PYAutoGUI INIT ====================
def fix_x11_authorization():
    try:
        result = subprocess.run(['xhost', '+local:'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("X11 authorization fixed: local connections allowed")
            return True
        else:
            print(f"xhost warning: {result.stderr.strip()}")
    except Exception as e:
        print(f"Could not fix X11 authorization: {e}")
    return False


def initialize_pyautogui():
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0  # No delay between commands
    try:
        sw, sh = pyautogui.size()
        print(f"PyAutoGUI initialized. Screen: {sw}x{sh}")
        return pyautogui, sw, sh
    except Exception as e:
        print(f"PyAutoGUI init failed: {e}")
        if fix_x11_authorization():
            try:
                sw, sh = pyautogui.size()
                print(f"PyAutoGUI initialized after fix. Screen: {sw}x{sh}")
                return pyautogui, sw, sh
            except Exception as e2:
                print(f"Still failed: {e2}")
    return None, None, None


# ==================== MEDIAPIPE INIT ====================
def download_model():
    import urllib.request
    if not os.path.exists(config.MODEL_PATH):
        print("Downloading MediaPipe hand landmarker model...")
        url = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
        try:
            urllib.request.urlretrieve(url, config.MODEL_PATH)
            print("Model downloaded successfully")
        except Exception as e:
            print(f"Failed to download model: {e}")
            return False
    return True


def initialize_hand_landmarker():
    if not download_model():
        return None
    base_options = mp_python.BaseOptions(model_asset_path=config.MODEL_PATH)
    options = vision.HandLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=config.DETECTION_CONFIDENCE,
        min_hand_presence_confidence=config.PRESENCE_CONFIDENCE,
        min_tracking_confidence=config.TRACKING_CONFIDENCE
    )
    try:
        landmarker = vision.HandLandmarker.create_from_options(options)
        print("MediaPipe HandLandmarker initialized")
        return landmarker
    except Exception as e:
        print(f"Failed to initialize HandLandmarker: {e}")
        return None


# ==================== CAMERA INIT ====================
def initialize_camera():
    cap = cv2.VideoCapture(0)
    if cap.isOpened():
        print("Camera initialized with default backend")
        return cap
    print("Default backend failed, trying V4L2 backend...")
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    if cap.isOpened():
        print("Camera initialized with V4L2 backend")
        return cap
    print("Error: Could not open camera with either backend")
    return None


# ==================== MINIMAL GUI ====================
class GuiWindow:
    def __init__(self, config, screen_width, screen_height):
        self.config = config
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.window_name = "Hand Cursor Control"
        self.visible = config.SHOW_GUI
        self.last_frame = None
        self.smoothed_pos = (screen_width // 2, screen_height // 2)
        self.target_pos = None
        self.fps = 0
        self.frame_times = deque(maxlen=30)
        self.hand_detected = False
        
        if self.visible:
            cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(self.window_name, config.GUI_WIDTH, config.GUI_HEIGHT)
            cv2.moveWindow(self.window_name, screen_width - config.GUI_WIDTH - 20, 20)
            self._create_trackbars()
    
    def _create_trackbars(self):
        cv2.createTrackbar('Smoothing (x100)', self.window_name, int(config.SMOOTHING_ALPHA * 100), 50, self._on_smoothing)
        cv2.createTrackbar('Tracking Box %', self.window_name, int(config.TRACKING_BOX_RATIO * 100), 80, self._on_tracking_box)
    
    def _on_smoothing(self, val): config.SMOOTHING_ALPHA = max(0.01, val / 100.0)
    def _on_tracking_box(self, val): config.TRACKING_BOX_RATIO = max(0.2, val / 100.0)
    
    def update(self, frame, hand_detected, smoothed_pos, target_pos, tracking_box, index_tip_landmark=None):
        if not self.visible:
            return
        
        self.last_frame = frame.copy()
        self.smoothed_pos = smoothed_pos
        self.target_pos = target_pos
        self.hand_detected = hand_detected
        
        # Update FPS
        now = time.time()
        self.frame_times.append(now)
        if len(self.frame_times) > 1:
            self.fps = len(self.frame_times) / (self.frame_times[-1] - self.frame_times[0])
        
        self._draw_overlay(tracking_box, index_tip_landmark)
        cv2.imshow(self.window_name, self.last_frame)
    
    def _draw_overlay(self, tracking_box, index_tip_landmark):
        box_x, box_y, box_w, box_h = tracking_box
        frame_h, frame_w = self.last_frame.shape[:2]
        sx, sy = self.smoothed_pos
        
        # Draw tracking box
        cv2.rectangle(self.last_frame, (box_x, box_y), (box_x + box_w, box_y + box_h), (0, 255, 0), 2)
        cv2.putText(self.last_frame, "Tracking Area", (box_x, box_y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        
        # Draw target position (raw index tip)
        if self.target_pos:
            tx, ty = self.target_pos
            cv2.circle(self.last_frame, (tx, ty), 8, (0, 0, 255), 2)
            cv2.putText(self.last_frame, "Target", (tx + 10, ty), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
        
        # Draw smoothed position (actual mouse cursor)
        display_x = int((sx / self.screen_width) * box_w + box_x)
        display_y = int((sy / self.screen_height) * box_h + box_y)
        cv2.circle(self.last_frame, (display_x, display_y), 10, (255, 0, 0), -1)
        cv2.putText(self.last_frame, "Cursor", (display_x + 12, display_y), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1)
        
        # Draw index tip landmark if available
        if index_tip_landmark:
            ix = int(index_tip_landmark.x * frame_w)
            iy = int(index_tip_landmark.y * frame_h)
            cv2.circle(self.last_frame, (ix, iy), 6, (0, 255, 255), 2)
            cv2.putText(self.last_frame, "Index Tip", (ix + 8, iy), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
        
        # Info panel on right side
        panel_x = frame_w - 180
        cv2.rectangle(self.last_frame, (panel_x, 0), (frame_w, frame_h), (0, 0, 0), -1)
        cv2.rectangle(self.last_frame, (panel_x, 0), (frame_w, frame_h), (100, 100, 100), 1)
        
        y = 25
        status_color = (0, 255, 0) if self.hand_detected else (0, 0, 255)
        status_text = "HAND DETECTED" if self.hand_detected else "NO HAND"
        cv2.putText(self.last_frame, status_text, (panel_x + 5, y), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, status_color, 1)
        y += 25
        
        for text in [
            f"FPS: {self.fps:.1f}",
            f"Screen: {self.screen_width}x{self.screen_height}",
            f"Cursor: ({sx}, {sy})",
            "",
            "Settings (trackbars):",
            f"  Smoothing: {config.SMOOTHING_ALPHA:.2f}",
            f"  Box: {config.TRACKING_BOX_RATIO:.0%}",
            "",
            "Control:",
            "  Index finger tip = cursor",
            "  Stay in green box",
            "",
            "Press 'q' to quit",
            "Press 'g' to toggle GUI",
        ]:
            color = (255, 255, 255)
            if text.startswith("  "): color = (200, 200, 200)
            if "FPS" in text: color = (0, 255, 255)
            if "Cursor" in text: color = (255, 0, 0)
            if "HAND" in text: color = status_color
            cv2.putText(self.last_frame, text, (panel_x + 5, y), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1)
            y += 18
    
    def check_key(self):
        if not self.visible:
            return None
        key = cv2.waitKey(1) & 0xFF
        return key if key != 255 else None
    
    def close(self):
        if self.visible:
            cv2.destroyWindow(self.window_name)


# ==================== MAIN ====================
def main():
    # Initialize pyautogui
    pyautogui, screen_width, screen_height = initialize_pyautogui()
    if pyautogui is None:
        print("\n❌ Cannot connect to X11 display.")
        print("Run: xhost +local:")
        sys.exit(1)

    # Initialize MediaPipe
    landmarker = initialize_hand_landmarker()
    if landmarker is None:
        sys.exit(1)

    # Initialize camera
    cap = initialize_camera()
    if cap is None:
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Tracking box (center region)
    box_w = int(frame_width * config.TRACKING_BOX_RATIO)
    box_h = int(frame_height * config.TRACKING_BOX_RATIO)
    box_x = (frame_width - box_w) // 2
    box_y = (frame_height - box_h) // 2

    # Smoothing state
    smoothed_x = screen_width // 2
    smoothed_y = screen_height // 2
    first_frame = True

    # Timestamp for MediaPipe video mode
    timestamp_ms = 0

    # GUI
    gui = GuiWindow(config, screen_width, screen_height)

    print("\n✅ Hand cursor control started!")
    print(f"   Screen: {screen_width}x{screen_height}")
    print(f"   Camera: {frame_width}x{frame_height}")
    print(f"   Tracking box: {box_w}x{box_h} at ({box_x}, {box_y})")
    print(f"   Smoothing (alpha): {config.SMOOTHING_ALPHA}")
    print(f"   GUI window: {'Enabled' if config.SHOW_GUI else 'Disabled'} (press 'g' to toggle)")
    print(f"   Failsafe: Enabled (move mouse to corner to abort)")
    print("\nControl: Point with index finger tip inside green box")
    print("Press Ctrl+C to quit")
    sys.stdout.flush()

    try:
        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                print("Failed to read frame")
                break

            # Mirror for natural interaction
            frame = cv2.flip(frame, 1)
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

            timestamp_ms += 33  # ~30 FPS
            results = landmarker.detect_for_video(mp_image, timestamp_ms)

            target_pos = None
            hand_detected = False
            index_tip_landmark = None

            if results.hand_landmarks:
                hand_landmarks = results.hand_landmarks[0]
                hand_detected = True
                
                # Get index finger tip (landmark 8)
                index_tip = hand_landmarks[8]
                index_tip_landmark = index_tip
                
                # Draw hand landmarks for visualization
                for i, lm in enumerate(hand_landmarks):
                    px, py = int(lm.x * frame_width), int(lm.y * frame_height)
                    color = (0, 255, 255) if i == 8 else (0, 255, 0)
                    radius = 5 if i == 8 else 3
                    cv2.circle(frame, (px, py), radius, color, -1)
                
                # Draw hand connections
                connections = [
                    (0,1),(1,2),(2,3),(3,4), (0,5),(5,6),(6,7),(7,8),
                    (5,9),(9,10),(10,11),(11,12), (9,13),(13,14),(14,15),(15,16),
                    (13,17),(17,18),(18,19),(19,20), (0,17)
                ]
                for s, e in connections:
                    p1, p2 = hand_landmarks[s], hand_landmarks[e]
                    x1, y1 = int(p1.x * frame_width), int(p1.y * frame_height)
                    x2, y2 = int(p2.x * frame_width), int(p2.y * frame_height)
                    cv2.line(frame, (x1, y1), (x2, y2), (255, 0, 0), 1)

                # Map index tip to screen coordinates
                target_pos = map_tracking_box_to_screen(
                    index_tip, frame_width, frame_height, box_x, box_y, box_w, box_h,
                    screen_width, screen_height
                )

            # Apply smoothing and move cursor
            if target_pos:
                tx, ty = target_pos
                if first_frame:
                    smoothed_x, smoothed_y = tx, ty
                    first_frame = False
                else:
                    smoothed_x, smoothed_y = apply_smoothing(
                        smoothed_x, smoothed_y, tx, ty, config.SMOOTHING_ALPHA
                    )
                
                try:
                    pyautogui.moveTo(smoothed_x, smoothed_y, duration=0)
                except Exception as e:
                    print(f"Move error: {e}")

            # Update GUI
            tracking_box = (box_x, box_y, box_w, box_h)
            gui.update(frame, hand_detected, (smoothed_x, smoothed_y), target_pos, tracking_box, index_tip_landmark)

            # Check keys
            key = gui.check_key()
            if key == ord('q'):
                print("Quit pressed")
                break
            elif key == ord('g'):
                config.SHOW_GUI = not config.SHOW_GUI
                if config.SHOW_GUI:
                    gui = GuiWindow(config, screen_width, screen_height)
                else:
                    gui.close()
                    gui = GuiWindow(config, screen_width, screen_height)

    except KeyboardInterrupt:
        print("\nInterrupted (Ctrl+C)")
    finally:
        cap.release()
        gui.close()
        cv2.destroyAllWindows()
        landmarker.close()
        print("Resources released. Goodbye!")


if __name__ == "__main__":
    main()