from flask import Flask, render_template, request, jsonify
from time import sleep
import RPi.GPIO as GPIO
import math
import os
from datetime import datetime
import subprocess
import threading
from threading import Thread

app = Flask(__name__)

listener_process = None
listener_lock = threading.Lock()

# State control variables
profile_thread = None
pause_flag = False
stop_flag = False
resume_flag = False
current_profile_name = None

# ─── GPIO CONFIG ─────────────────────────────────────────────
DIR = 20
STEP = 21
ENABLE_MOTOR1 = 18
DIR2 = 12
STEP2 = 16
LIMIT_SWITCH_PIN = 17
LIMIT_SWITCH_2_PIN = 24
ENABLE_MOTOR2 = 25

CW = 0
CCW = 1
SPR = 200
SPR2 = 400
LEAD_MM = 5
# LENGTH_L = 610  # mm
LENGTH_L = 618 # corrected 7/28/25

GPIO.setmode(GPIO.BCM)
GPIO.setup(DIR, GPIO.OUT)
GPIO.setup(STEP, GPIO.OUT)
GPIO.setup(ENABLE_MOTOR1, GPIO.OUT)
GPIO.output(ENABLE_MOTOR1, GPIO.HIGH)
GPIO.setup(ENABLE_MOTOR2, GPIO.OUT)
GPIO.output(ENABLE_MOTOR2, GPIO.HIGH)
GPIO.setup(DIR2, GPIO.OUT)
GPIO.setup(STEP2, GPIO.OUT)
GPIO.setup(LIMIT_SWITCH_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(LIMIT_SWITCH_2_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Track current angle and motor2 position
current_angle_deg = 0.0
current_motor2_position = 0

PROFILE_DIR = "./profiles"
LOG_FILE = "execution_log.txt"
os.makedirs(PROFILE_DIR, exist_ok=True)

def step_motor1(direction, steps, delay=0.005, check_limit=True):
    GPIO.output(ENABLE_MOTOR1, GPIO.LOW)
    GPIO.output(DIR, direction)
    for _ in range(steps):
        if check_limit and GPIO.input(LIMIT_SWITCH_PIN) == GPIO.HIGH:
            GPIO.output(ENABLE_MOTOR1, GPIO.HIGH)
            return False
        GPIO.output(STEP, GPIO.HIGH)
        sleep(delay)
        GPIO.output(STEP, GPIO.LOW)
        sleep(delay)
    # GPIO.output(ENABLE_MOTOR1, GPIO.HIGH)
    return True

def home_motor1():
    global current_angle_deg
    GPIO.output(ENABLE_MOTOR1, GPIO.LOW)
    GPIO.output(DIR, CCW)
    while GPIO.input(LIMIT_SWITCH_PIN) == GPIO.LOW:
        GPIO.output(STEP, GPIO.HIGH)
        sleep(0.002)
        GPIO.output(STEP, GPIO.LOW)
        sleep(0.002)
    sleep(2)
    GPIO.output(DIR, CW)
    for _ in range(200):
        GPIO.output(STEP, GPIO.HIGH)
        sleep(0.002)
        GPIO.output(STEP, GPIO.LOW)
        sleep(0.002)
    # GPIO.output(ENABLE_MOTOR1, GPIO.HIGH)
    current_angle_deg = 0.0

def home_motor2():
    global current_motor2_position
    GPIO.output(ENABLE_MOTOR2, GPIO.LOW)
    GPIO.output(DIR2, CCW)
    while GPIO.input(LIMIT_SWITCH_2_PIN) == GPIO.LOW:
        GPIO.output(STEP2, GPIO.HIGH)
        sleep(0.05)
        GPIO.output(STEP2, GPIO.LOW)
        sleep(0.05)
    sleep(2)
    GPIO.output(DIR2, CW)
    for _ in range(2):
        GPIO.output(STEP2, GPIO.HIGH)
        sleep(0.05)
        GPIO.output(STEP2, GPIO.LOW)
        sleep(0.05)
    current_motor2_position = 0

def step_motor2(direction, steps, delay=0.08, check_limit=True):
    GPIO.output(ENABLE_MOTOR2, GPIO.LOW)
    GPIO.output(DIR2, direction)
    for _ in range(steps):
        if check_limit and GPIO.input(LIMIT_SWITCH_2_PIN) == GPIO.HIGH:
            GPIO.output(ENABLE_MOTOR2, GPIO.HIGH)
            return False
        GPIO.output(STEP2, GPIO.HIGH)
        sleep(delay)
        GPIO.output(STEP2, GPIO.LOW)
        sleep(delay)
    return True

def quarter_turn(direction):
    GPIO.output(ENABLE_MOTOR1, GPIO.LOW)
    step_motor2(direction, int(0.5 * SPR2))

def move_to_angle(target_angle):
    global current_angle_deg
    delta_angle = target_angle - current_angle_deg

    # device calibration correction
    # delta_angle = (delta_angle + 0.133)/(0.975)
    # delta_angle = (delta_angle + 0.2755)/(0.9749)

    if abs(delta_angle) < 0.01:
        return 0
    theta_rad = math.radians(abs(delta_angle))
    h = LENGTH_L * math.sin(theta_rad)
    steps = int(h * 40)
    print(f"Moving {steps} steps for angle {target_angle}.")
    direction = CW if delta_angle > 0 else CCW
    step_motor1(direction, steps)
    current_angle_deg = target_angle
    return steps

def move_motor2_to_position(target_position):
    global current_motor2_position
    steps_needed = (target_position - current_motor2_position) % 4
    direction = CW if steps_needed <= 2 else CCW
    quarter_turns = steps_needed if direction == CW else 4 - steps_needed
    for _ in range(quarter_turns):
        quarter_turn(direction)
    current_motor2_position = target_position

def log_execution(step_str):
    with open(LOG_FILE, 'a') as log:
        log.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {step_str}\n")

def set_profile_status(status: int):
    try:
        with open("profile_status.txt", "w") as f:
            f.write(str(status))
    except Exception as e:
        print(f"Failed to write profile status: {e}")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/home", methods=["POST"])
def home():
    home_motor1()
    print(f"Current angle is {current_angle_deg}.")
    log_execution("Homed motor 1.")
    return jsonify({"status": "homed", "angle": current_angle_deg})

@app.route("/home2", methods=["POST"])
def home2():
    home_motor2()
    log_execution("Homed motor 2.")
    return jsonify({"status": "homed", "position": current_motor2_position})

@app.route("/rotate", methods=["POST"])
def rotate():
    direction = request.json.get("direction")
    if direction == "CW":
        quarter_turn(CW)
    elif direction == "CCW":
        quarter_turn(CCW)
    log_execution(f"Rotated stage {direction}.")
    return jsonify({"status": "rotated", "direction": direction})

@app.route("/angle", methods=["POST"])
def set_angle():
    angle = float(request.json.get("angle"))
    steps = move_to_angle(angle)
    log_execution(f"Set angle to {angle}º requiring {steps} steps.")
    return jsonify({"status": "moved", "angle": angle, "steps": steps})

@app.route("/fine_adjust", methods=["POST"])
def fine_adjust():
    direction = request.json.get("direction")
    adjustment_deg = 0.1
    if direction == "UP":
        move_to_angle(current_angle_deg + adjustment_deg)
    elif direction == "DOWN":
        move_to_angle(current_angle_deg - adjustment_deg)
    return jsonify({"status": "fine adjusted", "angle": current_angle_deg})

@app.route("/motor2_position", methods=["POST"])
def motor2_position():
    position = int(request.json.get("position"))
    move_motor2_to_position(position)
    log_execution(f"Setting motor 2 position to {position}.")
    return jsonify({"status": "positioned", "position": position})

@app.route("/status", methods=["GET"])
def status():
    return jsonify({"angle": current_angle_deg, "position": current_motor2_position})

@app.route("/cleanup", methods=["POST"])
def cleanup():
    GPIO.output(ENABLE_MOTOR1, GPIO.HIGH)
    GPIO.cleanup()
    return jsonify({"status": "GPIO cleaned up"})

# @app.route("/save_profile", methods=["POST"])
# def save_profile():
#     name = request.json.get("name")
#     steps = request.json.get("steps")
#     profile_path = os.path.join(PROFILE_DIR, name)
#     with open(profile_path, 'w') as file:
#         for step in steps:
#             line = f"{step['command']},{step['position']},{step['angle']},{step['duration']},{step['log']}\n"
#             file.write(line)
#     log_execution(f"Saved profile {name} complete.")
#     return jsonify({"status": "saved", "profile": name})

@app.route("/save_profile", methods=["POST"])
def save_profile():
    data = request.get_json()
    name = data.get("name")
    steps = data.get("steps", [])

    if not name:
        return jsonify({"error": "Profile name is required"}), 400

    path = os.path.join(PROFILE_DIR, name)
    with open(path, 'w') as f:
        for step in steps:
            axis = step.get("axis", "").strip()
            if step['command'].lower() == "ramp":
                line = f"{step['command']},{step['position']},{step['angle']},{step['duration']},{step['log']},{axis}\n"
            else:
                line = f"{step['command']},{step['position']},{step['angle']},{step['duration']},{step['log']}\n"
            f.write(line)

    log_execution(f"Saved profile {name} complete.")
    return jsonify({"status": "saved"})

@app.route("/list_profiles", methods=["GET"])
def list_profiles():
    profiles = os.listdir(PROFILE_DIR)
    return jsonify({"profiles": profiles})

@app.route("/load_profile", methods=["POST"])
def load_profile():
    name = request.json.get("name")
    profile_path = os.path.join(PROFILE_DIR, name)
    if not os.path.exists(profile_path):
        return jsonify({"status": "error", "message": "Profile not found."}), 404
    steps = []
    with open(profile_path, 'r') as file:
        for line in file:
            parts = line.strip().split(',')
            if len(parts) >= 4:
                steps.append({
                    "command": parts[0],
                    "position": int(parts[1]),
                    "angle": float(parts[2]),
                    "duration": float(parts[3]),
                    "log": parts[4].strip().lower() == 'true' if len(parts) > 4 else False
                })
    log_execution(f"Loaded profile {name} complete.")
    return jsonify({"status": "loaded", "profile": name, "steps": steps})

# @app.route("/run_profile", methods=["POST"])
# def run_profile():
    # name = request.json.get("name")
    # index = request.json.get("index")  # Optional for full run

    # profile_path = os.path.join(PROFILE_DIR, name)
    # if not os.path.exists(profile_path):
    #     return jsonify({"error": "Profile not found"}), 404

    # with open(profile_path, 'r') as f:
    #     lines = f.readlines()

    # steps = [line.strip().split(',') for line in lines if line.strip()]
    # if index is not None:
    #     steps = [steps[int(index)]]

    # for parts in steps:
    #     command, pos, angle, dur, log_flag = parts[0], int(parts[1]), float(parts[2]), float(parts[3]), parts[4].lower() == 'true'
    #     if command == 'home':
    #         home_motor1(); home_motor2()
    #     else:
    #         move_motor2_to_position(pos)
    #         move_to_angle(angle)
    #     if log_flag:
    #         log_execution(f"Moved to pos {pos}, angle {angle}")
    #     sleep(dur)

    # return jsonify({"status": "step complete"})

# @app.route("/run_profile", methods=["POST"])
# def run_profile():
#     name = request.json.get("name")
#     index = request.json.get("index")  # Optional index to run a single step

#     profile_path = os.path.join(PROFILE_DIR, name)
#     if not os.path.exists(profile_path):
#         return jsonify({"error": "Profile not found"}), 404

#     with open(profile_path, 'r') as f:
#         lines = f.readlines()

#     steps = [line.strip().split(',') for line in lines if line.strip()]
#     if index is not None:
#         steps = [steps[int(index)]]

#     log_execution(f"Running profile {name}...")

#     for parts in steps:
#         command = parts[0].strip().lower()
#         pos = int(parts[1])
#         angle = float(parts[2])
#         duration = float(parts[3])
#         log_flag = parts[4].lower() == 'true'

#         if command == 'home':
#             home_motor1()
#             home_motor2()
#         elif command == 'move':
#             move_motor2_to_position(pos)
#             move_to_angle(angle)
#         elif command == 'ramp':
#             # Perform a smooth ramp
#             global current_angle_deg
#             start = current_angle_deg
#             step_delay = duration / 100
#             for i in range(1, 101):
#                 intermediate = start + (angle - start) * (i / 100)
#                 move_to_angle(intermediate)
#                 sleep(step_delay)
#         else:
#             print(f"Unknown command: {command}")
#             continue

#         if log_flag:
#             log_execution(f"{command.upper()} to pos {pos}, angle {angle}, duration {duration}s")

#     log_execution(f"Running profile {name} complete.")
#     return jsonify({"status": "step complete"})

@app.route("/run_profile", methods=["POST"])
def run_profile():
    name = request.json.get("name")
    index = request.json.get("index")  # Optional index to run a single step

    profile_path = os.path.join(PROFILE_DIR, name)
    if not os.path.exists(profile_path):
        return jsonify({"error": "Profile not found"}), 404

    with open(profile_path, 'r') as f:
        lines = f.readlines()

    steps = [line.strip().split(',') for line in lines if line.strip()]
    if index is not None:
        steps = [steps[int(index)]]

    log_execution(f"Running profile {name}...")

    def set_profile_status(value: int):
        try:
            with open("profile_status.txt", "w") as f:
                f.write(str(value))
        except Exception as e:
            print(f"Failed to write profile status: {e}")

    set_profile_status(0)

    for parts in steps:
        if len(parts) < 5:
            print("Invalid step format:", parts)
            continue

        command = parts[0].strip().lower()
        pos = int(parts[1])
        angle = float(parts[2])
        duration = float(parts[3])
        log_flag = parts[4].lower() == 'true'
        axis = parts[5].strip().lower() if len(parts) > 5 else "none"  # optional axis field

        if command == 'home':
            home_motor1()
            home_motor2()
        elif command == 'move':
            move_motor2_to_position(pos)
            move_to_angle(angle)
        elif command == 'ramp':
            # Set profile status for logging: 1 = pitch, 2 = roll
            if axis == "pitch":
                set_profile_status(1)
            elif axis == "roll":
                set_profile_status(2)
            else:
                set_profile_status(0)

            global current_angle_deg
            start = current_angle_deg
            step_delay = duration / 100
            for i in range(1, 101):
                intermediate = start + (angle - start) * (i / 100)
                move_to_angle(intermediate)
                sleep(step_delay)

            # Reset profile status after ramp is complete
            set_profile_status(0)
        else:
            print(f"Unknown command: {command}")
            continue

        if log_flag:
            log_execution(f"{command.upper()} to pos {pos}, angle {angle}, duration {duration}s")

    log_execution(f"Running profile {name} complete.")
    return jsonify({"status": "step complete"})



@app.route("/ramp_angle", methods=["POST"])
def ramp_angle():
    data = request.get_json()
    target_angle = float(data.get("angle"))
    duration = float(data.get("duration"))

    global current_angle_deg
    print(f"Current angle is {current_angle_deg}")
    log_execution(f"Ramping to angle {target_angle}º from current angle {current_angle_deg}º...")
    steps = 100
    start = current_angle_deg
    step_delay = duration / steps
    for i in range(1, steps + 1):
        intermediate_angle = start + (target_angle - start) * (i / steps)
        move_to_angle(intermediate_angle)
        sleep(step_delay)
    log_execution(f"Ramping to angle {target_angle}º from current angle {current_angle_deg}º complete.")
    return jsonify({"status": "ramped", "angle": target_angle})

@app.route('/start_listener', methods=['POST'])
def start_listener():
    global listener_process
    with listener_lock:
        if listener_process and listener_process.poll() is None:
            return jsonify({"status": "already_running"})
        
        data = request.json
        ids = data.get('device_ids', '').strip().splitlines()
        ids = [id.strip() for id in ids if id.strip()]
        if not ids:
            return jsonify({"status": "no_ids"})

        # Save device list to temp file
        with open("allowed_ids.txt", "w") as f:
            for device_id in ids:
                f.write(device_id + "\n")

        log_execution(f"Listening on listed filtered devices for packet capture.")

        def set_profile_status(value: int):
            try:
                with open("profile_status.txt", "w") as f:
                    f.write(str(value))
            except Exception as e:
                print(f"Failed to write profile status: {e}")

        set_profile_status(0)

        listener_process = subprocess.Popen(['python3', 'read_hrt_v3.py', 'allowed_ids.txt'])
        return jsonify({"status": "started"})

@app.route('/stop_listener', methods=['POST'])
def stop_listener():
    global listener_process
    with listener_lock:
        if listener_process and listener_process.poll() is None:
            listener_process.terminate()
            listener_process.wait()
            return jsonify({"status": "stopped"})
        log_execution(f"Stopped listening for packet capture.")
        return jsonify({"status": "not_running"})

@app.route("/run_calibration", methods=["POST"])
def run_calibration_for_all():
    try:
        with open("allowed_ids.txt", 'r') as f:
            device_ids = [line.strip() for line in f if line.strip()]

        for did in device_ids:
            print(f"Running calibration for {did}...")
            log_execution(f"Running calibration for {did}...")
            result = subprocess.run(["python3", "sigmund.py", did], capture_output=True, text=True)
            print(result.stdout)
            log_execution(f"Calibration for {did} complete.")
            if result.stderr:
                print(f"Error for {did}: {result.stderr}")

        return jsonify({"status": "calibration complete", "devices": device_ids})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/toggle_motors", methods=["POST"])
def toggle_motors():
    data = request.get_json()
    motor1_enabled = data.get("motor1", True)
    motor2_enabled = data.get("motor2", True)

    # Example: You can use global flags or GPIO logic to enable/disable motors
    if motor1_enabled:
        print("Motor 1 enabled")
        log_execution(f"Motor 1 enabled")
        GPIO.output(ENABLE_MOTOR1, GPIO.LOW)
    else:
        print("Motor 1 disabled")
        log_execution(f"Motor 1 disabled")
        GPIO.output(ENABLE_MOTOR1, GPIO.HIGH)

    if motor2_enabled:
        print("Motor 2 enabled")
        log_execution(f"Motor 2 enabled")
        GPIO.output(ENABLE_MOTOR2, GPIO.LOW)
    else:
        print("Motor 2 disabled")
        log_execution(f"Motor 2 disabled")
        GPIO.output(ENABLE_MOTOR2, GPIO.HIGH)

    return jsonify({"motor1": motor1_enabled, "motor2": motor2_enabled})

@app.route("/log_tail", methods=["GET"])
def log_tail():
    lines = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            lines = f.readlines()[-5:]  # Last 10 lines
    return jsonify({"log": lines})



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
