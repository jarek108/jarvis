import os
import time
import asyncio
from typing import Any, AsyncGenerator
from loguru import logger
from ..contract import IOType

# --- Optional Dependencies ---
try:
    import mss
    import PIL.Image
except ImportError:
    mss = PIL = None

try:
    import cv2
except ImportError:
    cv2 = None

async def execute_screen_capture(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """Captures desktop screenshots."""
    if not mss or not PIL: 
        logger.warning(f"[{node_id}] mss or PIL missing. Skipping capture.")
        return
        
    session_dir = config.get('session_dir', '.')
    out_path = os.path.join(session_dir, f"{node_id}_capture.jpg")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with mss.mss() as sct:
        monitor = sct.monitors[1]
        sct_img = sct.grab(monitor)
        img = PIL.Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        img.save(out_path, format="JPEG", quality=85)
        
    await output_queue.put({"type": "image_path", "content": out_path, "ts": time.perf_counter()})

async def execute_camera_capture(node_id: str, input_streams: dict[str, AsyncGenerator], config: dict[str, Any], output_queue: asyncio.Queue, session: Any):
    """Captures frames from the system webcam."""
    if not cv2:
        logger.warning(f"[{node_id}] opencv-python missing. Skipping camera capture.")
        return
        
    session_dir = config.get('session_dir', '.')
    out_path = os.path.join(session_dir, f"{node_id}_camera.jpg")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    
    device_index = config.get('device_index', 0)
    cap = cv2.VideoCapture(device_index)
    
    if not cap.isOpened():
        logger.error(f"[{node_id}] Could not open camera {device_index}")
        return
        
    # Warm up camera
    for _ in range(5): cap.read()
    
    ret, frame = cap.read()
    if ret:
        cv2.imwrite(out_path, frame)
        await output_queue.put({"type": "image_path", "content": out_path, "ts": time.perf_counter()})
    else:
        logger.error(f"[{node_id}] Failed to capture frame from camera.")
        
    cap.release()

def validate_screen_capture(node_id: str, config: dict, scenario_inputs: dict) -> tuple[bool, str]:
    """Ensures screen capture dependencies are present."""
    if not mss: return False, "Missing 'mss' library for screen capture."
    return True, ""

def validate_camera_capture(node_id: str, config: dict, scenario_inputs: dict) -> tuple[bool, str]:
    """Ensures camera is accessible."""
    if not cv2: return False, "Missing 'opencv-python' library for camera capture."
    
    device_index = config.get('device_index', 0)
    cap = cv2.VideoCapture(device_index)
    opened = cap.isOpened()
    cap.release()
    
    if not opened:
        return False, f"Could not access camera device at index {device_index}."
    return True, ""