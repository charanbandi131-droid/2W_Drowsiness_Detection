import time
import numpy as np
import threading  # mainly to avoid LCD delays
from scipy.signal import find_peaks, butter, filtfilt
from collections import deque
import max30100
import random
import sys
import curses
import locale
import lcd_display

from gpiozero import Buzzer

locale.setlocale(locale.LC_ALL, '')

current_speed = 0.0
target_speed = 45.0
last_bpm = 0.0
current_heart_symbol = ""
last_lcd_text = ""
last_lcd_color = (0, 0, 0)
start_time = None
current_imu_x = 0.2
current_imu_y = 0.2
target_imu_x = 0.2
target_imu_y = 0.2
detection_time = None

# Initialize the MAX30100 sensor
mx30 = max30100.MAX30100()
mx30.enable_spo2()  # Use SpO2 mode for both IR and red, but we'll use IR for HR

# Parameters
sampling_rate = 100  # Hz
window_size = 10 * sampling_rate  # Increased to 10 seconds for more stable calculation
update_interval = 1  # Update BPM every 1 second
finger_threshold = 12000  # IR value below this indicates no finger (adjust if needed)
bpm_history = deque(maxlen=10)  # Increased to 10 for more averaging
ir_buffer = deque(maxlen=window_size)
last_update_time = time.time()
finger_detected_time = None
was_finger_on = False
first_heartbeat_detected = False
last_beat_time = time.time()

# Global scenario flag
scenario = None
speed = 0.0
imu_x = 0.0
imu_y = 0.0
drowsiness_status = "No Warning"  # Simulated, since no AI

finger_off_start_time = None
was_hands_off = False

buzzer = Buzzer(17, active_high=False)  # Use active_high=True if active high


# Butterworth bandpass filter
def bandpass_filter(data, lowcut=0.8, highcut=2.5, fs=sampling_rate, order=5):
    nyq = 0.5 * fs
    low = lowcut / nyq
    high = highcut / nyq
    b, a = butter(order, [low, high], btype='band')
    return filtfilt(b, a, data)

# Curses color pairs
GREEN = 1
BLUE = 2
RED = 3
GRAY = 4

def init_curses(stdscr):
    curses.curs_set(0)  # Hide cursor
    curses.start_color()
    curses.init_pair(GREEN, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(BLUE, curses.COLOR_BLUE, curses.COLOR_BLACK)
    curses.init_pair(RED, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(GRAY, curses.COLOR_WHITE, curses.COLOR_BLACK)  # Gray as dim white
    curses.use_default_colors()

def draw_borders(stdscr, rows, cols):
    # Left panel: Inputs
    left_width = cols // 2
    try:
        stdscr.addstr(0, 0, "+" + "-" * (left_width - 2) + "+")
    except curses.error:
        pass
    for i in range(1, rows - 1):
        try:
            stdscr.addstr(i, 0, "|")
            stdscr.addstr(i, left_width - 1, "|")
        except curses.error:
            pass
    try:
        stdscr.addstr(rows - 1, 0, "+" + "-" * (left_width - 2) + "+")
    except curses.error:
        pass

    # Right panel: Outputs
    right_start = left_width
    right_width = cols - left_width
    try:
        stdscr.addstr(0, right_start, "+" + "-" * (right_width - 2) + "+")
    except curses.error:
        pass
    for i in range(1, rows - 1):
        try:
            stdscr.addstr(i, right_start, "|")
            stdscr.addstr(i, right_start + right_width - 1, "|")
        except curses.error:
            pass
    try:
        stdscr.addstr(rows - 1, right_start, "+" + "-" * (right_width - 2) + "+")
    except curses.error:
        pass

    try:
        stdscr.addstr(1, left_width // 2 - 4, "Inputs", curses.A_BOLD)
        stdscr.addstr(1, right_start + right_width // 2 - 5, "Outputs", curses.A_BOLD)
    except curses.error:
        pass

def update(stdscr):
    global was_finger_on, finger_detected_time, last_update_time, first_heartbeat_detected, speed, imu_x, imu_y
    global scenario, speed, imu_x, imu_y, drowsiness_status, last_beat_time
    global current_speed, target_speed, detection_time, was_hands_off
    global last_bpm, current_heart_symbol, bpm_display
    global start_time, finger_off_start_time

    rows, cols = stdscr.getmaxyx()
    if rows < 20 or cols < 80:
        stdscr.clear()
        was_hands_off = False
        try:
            stdscr.addstr(0, 0, "Terminal too small (need at least 80x20)")
        except curses.error:
            pass
        stdscr.refresh()
        return

    ir_value = 0  # Default if read fails
    read_success = False
    for attempt in range(5):
        try:
            mx30.read_sensor()
            ir_value = mx30.ir
            read_success = True
            break
        except BlockingIOError:
            time.sleep(0.001)  # Short delay before retry

    if not read_success:
        # Handle persistent error, perhaps log or set to hands-off
        ir_value = finger_threshold - 1  # Simulate no finger if read fails

    current_time = time.time()

    # Update inputs (left side)
    if scenario in [2, 3]:
        if random.random() < 0.02:
            target_speed = random.uniform(20, 70)
        delta = target_speed - current_speed
        if delta > 0:
            current_speed = min(current_speed + 0.005, target_speed)
        elif delta < 0:
            current_speed = max(current_speed - 0.005, target_speed)
        speed = current_speed
    elif scenario == 1:
        elapsed = current_time - start_time
        speed = min(20.0 * (elapsed / 40.0), 20.0)
    else:
        speed = 0.0

    imu_x = 0.2
    imu_y = 0.2
    hands_off_detection_enabled = scenario != 1 and speed >= 20

    # Sensor logic
    if ir_value < finger_threshold:
        if was_finger_on:
            was_finger_on = False
            first_heartbeat_detected = False
            bpm_history.clear()
            ir_buffer.clear()
            last_update_time = current_time
        bpm_display = "--"
        if finger_off_start_time is None:
            finger_off_start_time = current_time
        if current_time - finger_off_start_time >= 2:
            last_bpm = 0.0
            drowsiness_status = "No Value"
        else:
            pass  # Keep previous for <2 sec
        current_heart_symbol = " "
        measuring_msg = ""
    else:
        if not was_finger_on:
            was_finger_on = True
            finger_detected_time = current_time
            finger_off_start_time = None
        ir_buffer.append(ir_value)
        if current_time - last_update_time >= update_interval and len(ir_buffer) >= sampling_rate * 10:
            finger_off_start_time = None
            ir_array = np.array(ir_buffer, dtype=float)
            ir_array -= np.mean(ir_array)  # Remove DC component
            filtered_ir = bandpass_filter(ir_array)
            peaks, _ = find_peaks(-filtered_ir, height=-np.percentile(filtered_ir, 75), distance=sampling_rate * 0.4, prominence=0.1 * (np.max(filtered_ir) - np.min(filtered_ir)))
            if len(peaks) > 1:
                ibis = np.diff(peaks) / sampling_rate
                if len(ibis) > 0:
                    avg_ibi = np.mean(ibis)
                    if avg_ibi > 0:
                        bpm = 60 / avg_ibi
                        if 40 < bpm < 200:
                            bpm_history.append(bpm)
                    if len(bpm_history) > 0:
                        avg_bpm = np.mean(bpm_history)
                        if scenario == 3:
                            if detection_time is None:
                                detection_time = current_time
                            if current_time - detection_time < 5:
                                last_bpm = 95.0
                                bpm_display = "95.0"
                            else:
                                low_in = 70.0
                                high_in = 100.0
                                low_out = 101.0
                                high_out = 115.0
                                if avg_bpm <= low_in:
                                    mapped_bpm = low_out
                                elif avg_bpm >= high_in:
                                    mapped_bpm = high_out
                                else:
                                    mapped_bpm = low_out + (high_out - low_out) * (avg_bpm - low_in) / (high_in - low_in)
                                last_bpm = mapped_bpm
                                bpm_display = f"{mapped_bpm:.1f}"
                        else:
                            last_bpm = avg_bpm
                            bpm_display = f"{avg_bpm:.1f}"
                        measuring_msg = ""  # Clear measuring after first BPM
                        if not first_heartbeat_detected:
                            first_heartbeat_detected = True
                else:
                    bpm_display = "--"
            else:
                bpm_display = "--"

            last_update_time = current_time
        else:
            bpm_display = f"{last_bpm:.1f}" if last_bpm > 0 else "--"

        # For scenario 3, set drowsiness based on BPM
        if scenario == 3:
            if bpm_display == "--" or last_bpm == 0:
                drowsiness_status = "No Value"
            elif last_bpm <= 100:
                drowsiness_status = "No Warning"
            else:
                drowsiness_status = "Warning"
        measuring_msg = "Measuring" if not first_heartbeat_detected else ""

    # Flashing logic
    if not first_heartbeat_detected:
        beat_interval = 0.5
    else:
        beat_interval = 60 / last_bpm if last_bpm > 0 else 1.0
    if current_time - last_beat_time >= beat_interval:
        current_heart_symbol = "<3 " if current_heart_symbol != "<3 " else " "
        last_beat_time = current_time

    # Unified drowsiness status
    if bpm_display == "--" or last_bpm == 0.0:
        drowsiness_status = "No Value"
    elif scenario == 3 and last_bpm > 100:
        drowsiness_status = "Warning"
    else:
        drowsiness_status = "No Warning"

    # Clear screen and draw borders
    stdscr.clear()
    draw_borders(stdscr, rows, cols)

    left_width = cols // 2
    right_start = left_width
    right_width = cols - left_width

    # Left: Inputs - Center texts
    ignition_text = "IGNITION: ON"
    speed_text = f"Vehicle Speed: {speed:.1f} kmph"
    imu_text = f"IMU: X={imu_x:.2f} Y={imu_y:.2f}"

    try:
        # Ignition
        col = (left_width - len(ignition_text)) // 2
        stdscr.addstr(4, col, ignition_text, curses.color_pair(GREEN) | curses.A_BOLD)

        # Speed
        col = (left_width - len(speed_text)) // 2
        stdscr.addstr(8, col, speed_text, curses.color_pair(BLUE) | curses.A_BOLD)

        # IMU
        col = (left_width - len(imu_text)) // 2
        stdscr.addstr(12, col, imu_text, curses.color_pair(BLUE) | curses.A_BOLD)
    except curses.error:
        pass

    # Right: Outputs
    # Heart Rate
    bpm_text = f"Live Heart Rate (BPM): {bpm_display}"
    try:
        col = right_start + (right_width - len(bpm_text)) // 2
        stdscr.addstr(4, col, bpm_text, curses.color_pair(RED) | curses.A_BOLD)

        # Heart symbol centered
        heart_len = len(current_heart_symbol)
        heart_x = right_start + (right_width - heart_len) // 2
        stdscr.addstr(8, heart_x, current_heart_symbol, curses.color_pair(RED) | curses.A_BOLD | curses.A_BLINK if first_heartbeat_detected else 0)

        # Measuring
        meas_len = len(measuring_msg)
        col = right_start + (right_width - meas_len) // 2
        stdscr.addstr(10, col, measuring_msg, curses.color_pair(RED) | curses.A_BOLD)
    except curses.error:
        pass

    # Hands-off
    if not hands_off_detection_enabled:
        hand_status = "Hands-off Warning OFF"
        hand_color = GRAY
        if was_hands_off:
            was_hands_off = False
    elif ir_value < finger_threshold:
        hand_status = "Hands OFF"
        was_hands_off = True
        hand_color = RED
    else:
        hand_status = "Hands ON"
        if was_hands_off:
            was_hands_off = False
        hand_color = GREEN
    try:
        col = right_start + (right_width - len(hand_status)) // 2
        stdscr.addstr(12, col, hand_status, curses.color_pair(hand_color) | curses.A_BOLD)
    except curses.error:
        pass

    # Drowsiness
    drowsy_text = f"DROWSINESS: {drowsiness_status}"
    drowsy_color = RED if drowsiness_status == "Warning" else GRAY if drowsiness_status == "No Value" else GREEN
    try:
        col = right_start + (right_width - len(drowsy_text)) // 2
        stdscr.addstr(16, col, drowsy_text, curses.color_pair(drowsy_color) | curses.A_BOLD)
    except curses.error:
        pass

    # Now LCD logic
    is_hands_off_warning = (scenario in [2, 3]) and hand_status == "Hands OFF" and hands_off_detection_enabled
    is_drowsiness_warning = (scenario == 3) and drowsiness_status == "Warning"

    if is_hands_off_warning:
        new_text = "HANDS \n OFF"
        new_color = (255, 0, 0)
    elif is_drowsiness_warning:
        new_text = "HIGH \nHeart Rate"
        new_color = (255, 0, 0)
    else:
        if bpm_display == "--":
            new_text = "Heart Rate\n-- bpm"
            new_color = (128, 128, 128)
        else:
            new_text = f"Heart Rate\n{bpm_display} bpm"
            new_color = (0, 255, 0)

    global last_lcd_text, last_lcd_color
    if new_text != last_lcd_text or new_color != last_lcd_color:
        threading.Thread(target=lcd_display.display_text, args=(new_text, new_color)).start()
        last_lcd_text = new_text
        last_lcd_color = new_color

    # Buzzer control
    if is_hands_off_warning or is_drowsiness_warning:
        buzzer.beep(on_time=1, off_time=1, n=None, background=True)
    else:
        buzzer.off()

    stdscr.refresh()

def run_demo(stdscr):
    init_curses(stdscr)
    while True:
        update(stdscr)
        time.sleep(0.01)

# Console for user input
def main():
    threading.Thread(target=lcd_display.display_text, args=("AUMOVIO\n Eng. \n Solutions", (0,255,0))).start()
    global scenario
    global start_time, current_speed, target_speed, detection_time, was_finger_on, first_heartbeat_detected, ir_buffer, bpm_history, last_bpm
    while True:
        print("Place your finger on the sensor. Monitoring live...")
        print("\nDemo Scenarios:")
        print("1: Health monitoring (Speed<20 kmph, No hands-off detection)")
        print("2: Hands off detection, Health Monitoring (Speed>20 kmph)")
        print("3: High heart rate detection (Speed>20 kmph, HR above 100bpm)")
        print("q: Quit")
        choice = input("Enter choice (1/2/3/q): ").strip().lower()
        if choice == 'q':
            buzzer.close()
            sys.exit(0)
        elif choice in ['1', '2', '3']:
            scenario = int(choice)
            was_finger_on = False
            first_heartbeat_detected = False
            detection_time = None
            last_bpm = 0.0
            ir_buffer.clear()
            bpm_history.clear()
            if scenario == 1:
                start_time = time.time()
                current_speed = 0.0
            elif scenario in [2, 3]:
                current_speed = 18.0
                target_speed = random.uniform(20, 70)
            print(f"Running Scenario {scenario}. Press Ctrl+C to return to menu.")
            try:
                curses.wrapper(run_demo)
            except KeyboardInterrupt:
                threading.Thread(target=lcd_display.display_text, args=("AUMOVIO\n Eng. \n Solutions", (0,255,0))).start()
                buzzer.off()
                continue
        else:
            print("Invalid choice. Try again.")
            threading.Thread(target=lcd_display.display_text, args=("AUMOVIO\n Eng. \n Solutions", (0,255,0))).start()

if __name__ == "__main__":
    main()
    threading.Thread(target=lcd_display.display_text, args=("AUMOVIO\n Eng. \n Solutions", (0,255,0))).start()
    buzzer.close()
