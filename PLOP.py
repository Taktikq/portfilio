import serial
import time
import cv2
import numpy as np
import csv
from datetime import datetime

# ==========================================
# HARDWARE CONFIGURATION
# ==========================================
TARGET_PORT = 'COM5'     # Verified active Arduino port
BAUD_RATE = 9600
LOG_FILE = "telemetry_log.csv"
DROIDCAM_URL = "http://192.168.10.7:4747/video"

def capture_live_frame(stream_url=DROIDCAM_URL, output_file="live_canopy.jpg"):
    # Pass network URL directly without DirectShow flags
    cap = cv2.VideoCapture(stream_url)
    if not cap.isOpened():
        raise RuntimeError(f"[VISION ERROR] Cannot connect to DroidCam stream at '{stream_url}'. Check IP.")
    
    # Sensor warm-up loop
    ret, frame = False, None
    for _ in range(5):
        ret, frame = cap.read()
        time.sleep(0.05)
        
    if not ret or frame is None:
        cap.release()
        raise RuntimeError("[VISION ERROR] Failed to grab frame from IP stream.")
        
    cap.release()
    cv2.imwrite(output_file, frame)
    print(f"[VISION] Live frame captured via IP Stream -> '{output_file}'")
    return frame

def calculate_canopy_exg(frame):
    b, g, r = cv2.split(frame.astype(np.float32))
    exg = 2.0 * g - r - b
    _, binary_mask = cv2.threshold(exg, 20.0, 255.0, cv2.THRESH_BINARY)
    
    binary_mask_uint8 = binary_mask.astype(np.uint8)
    cv2.imwrite("mask_canopy.jpg", binary_mask_uint8)
    
    green_pixels = cv2.countNonZero(binary_mask_uint8)
    coverage_pct = (green_pixels / binary_mask.size) * 100.0
    return coverage_pct

def log_telemetry(raw_soil, soil_pct, raw_tds, tds_ppm, coverage_pct, runtime_s, state):
    file_exists = False
    try:
        with open(LOG_FILE, 'r'):
            file_exists = True
    except FileNotFoundError:
        pass

    with open(LOG_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['timestamp', 'raw_soil', 'soil_pct', 'raw_tds', 'tds_ppm', 'coverage_pct', 'runtime_s', 'state'])
        writer.writerow([
            datetime.now().isoformat(),
            raw_soil, round(soil_pct, 1),
            raw_tds, round(tds_ppm, 1),
            round(coverage_pct, 2),
            runtime_s, state
        ])
    print(f"[LOG] Saved execution record to '{LOG_FILE}'")

def run_control_cycle():
    print("=== AQUAKZO CLOSED-LOOP ENGINE EXECUTION ===")
    
    # 1. Vision Processing
    frame = capture_live_frame(DROIDCAM_URL)
    coverage_pct = calculate_canopy_exg(frame)
    print(f"[ANALYSIS] Live Plant Coverage: {coverage_pct:.2f}%")

    # 2. Hardware Telemetry Acquisition
    arduino = serial.Serial(TARGET_PORT, BAUD_RATE, timeout=2)
    time.sleep(2.0)  # Reset buffer after DTR drop
    arduino.reset_input_buffer()

    raw_soil, raw_tds = None, None
    start_time = time.time()
    
    while time.time() - start_time < 5.0:
        if arduino.in_waiting > 0:
            line = arduino.readline().decode('utf-8', errors='ignore').strip()
            if line.startswith("TELEMETRY:"):
                parts = line.split(":")[1].split(",")
                raw_soil = int(parts[0])
                raw_tds = int(parts[1])
                break

    if raw_soil is None or raw_tds is None:
        arduino.close()
        raise RuntimeError("[HARDWARE ERROR] Telemetry acquisition timed out on Serial bus.")

    # Calibration Mapping
    soil_pct = max(0.0, min(100.0, (1023 - raw_soil) / 1023.0 * 100.0))
    tds_ppm = raw_tds * 6.927  # Linear conversion baseline

    print(f"[TELEMETRY] Raw Soil: {raw_soil} ({soil_pct:.1f}%) | Raw TDS: {raw_tds} ({tds_ppm:.0f} PPM)")

    # 3. Decision Matrix
    runtime_s = 0.0
    state = "NORMAL"

    if tds_ppm > 1200:
        state = "SALINITY_LOCKOUT"
        runtime_s = 0.0
        print(f"[ALERT] Salinity Threshold Exceeded ({tds_ppm:.0f} PPM)! Safety Lockout Active.")
    elif soil_pct < 40.0:
        state = "CRITICAL_DRY"
        runtime_s = 8.0
    elif soil_pct < 60.0:
        state = "MAINTENANCE"
        runtime_s = 4.0
    else:
        state = "ADEQUATE"
        runtime_s = 0.0

    print(f"[DECISION] State: {state} | Target Runtime: {runtime_s}s")

    # 4. Actuation Protocol
    if runtime_s > 0:
        cmd = f"PUMP_ON:{runtime_s}\n"
        arduino.write(cmd.encode())
        print(f"[SERIAL TRANSMIT] Sent: {cmd.strip()}")
        time.sleep(runtime_s + 0.5)

    arduino.close()
    
    # 5. Persistent Logging
    log_telemetry(raw_soil, soil_pct, raw_tds, tds_ppm, coverage_pct, runtime_s, state)

if __name__ == "__main__":
    try:
        run_control_cycle()
    except Exception as e:
        print(f"[FATAL ERROR] {e}")