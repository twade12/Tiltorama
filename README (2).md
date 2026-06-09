# HRT Tilt Sensor Calibration Fixture

A Raspberry Pi 4B-controlled automated calibration platform for electrolytic tilt sensors and MEMS accelerometers. Supports simultaneous calibration of up to 30 wireless devices via Zigbee, with full remote control via a Flask REST API and automated sigmoid-based curve fitting.

---

## Overview

Electrolytic tilt sensors (narrow-range HRT type) have a characteristic sigmoid-shaped ADC output as a function of input angle. Their useful linear range is only ±0.5–1°, embedded within a full operating swing of ±3°. Accurate calibration requires:

1. Applying a **known, constant angular rate of change** as a stimulus
2. Capturing raw ADC counts across the full sigmoid
3. Fitting a 4-parameter sigmoid to identify the inflection point and linear range
4. Extracting a counts-per-degree coefficient within the linear region
5. Cross-calibrating secondary (MRT MEMS) axes via 2-point calibration against the primary calibrated axis

This fixture automates all of the above for batch production calibration.

---

## Hardware

### Tilt Stage
- **Frame:** 80/20 aluminum extrusion
- **Motor 1 (Vertical Lift):** Stepper motor + 5mm lead ball screw, L = 618 mm arm → converts linear displacement to angular tilt
- **Motor 2 (Rotation):** Stepper motor, 90°-indexed turntable → switches stage between pitch and roll calibration axes
- **Limit switches:** Homing on both axes at startup
- **Stage surface:** Plywood platform, leveled, accommodates up to ~30 sensor units

### Electronics
- **Controller:** Raspberry Pi 4B (headless, SSH + Flask API)
- **Stepper drivers:** Dual closed-loop stepper drivers (PUL/DIR/ENA interface, encoder feedback)
- **Wireless receiver:** Resensys Zigbee USB receiver → SenStream CLI for data capture
- **Sensors:** Resensys HRT (electrolytic, narrow-range) + MRT (3-axis MEMS accelerometer) wireless nodes

### Mechanical Constants (derived)
```
L       = 618 mm          (arm length, corrected 7/28/25)
SPR     = 200 steps/rev   (Motor 1, vertical lift)
SPR2    = 400 steps/rev   (Motor 2, rotation)
lead    = 5 mm/rev        (ball screw)
γ       = 40 steps/mm     (Motor 1 linear resolution)
Δθ_actual = 5.7945°       (over 100 stages, integer-rounded)
RATE    = 0.0092712°/sec  (empirically verified against calibrated sensors)
```

---

## Software

### `stepper_dual_flask.py` — Raspberry Pi Controller

Flask REST API running on the Pi (port 5000). Exposes full remote control of the fixture over the local network — no dedicated client software required.

**Endpoints:**

| Route | Method | Description |
|---|---|---|
| `/` | GET | Web UI (index.html) |
| `/home` | POST | Home Motor 1 (vertical lift) to limit switch |
| `/home2` | POST | Home Motor 2 (rotation) to limit switch |
| `/angle` | POST | Move to absolute angle (degrees) |
| `/fine_adjust` | POST | ±0.1° fine adjustment |
| `/ramp_angle` | POST | Smooth ramp to target angle over specified duration |
| `/rotate` | POST | Quarter-turn CW or CCW on Motor 2 |
| `/motor2_position` | POST | Index Motor 2 to named position (0–3) |
| `/save_profile` | POST | Save a named calibration profile |
| `/load_profile` | POST | Load a named calibration profile |
| `/list_profiles` | GET | List saved profiles |
| `/run_profile` | POST | Execute a named profile (home / move / ramp sequences) |
| `/start_listener` | POST | Start Zigbee packet capture (spawns `read_hrt_v3.py`) |
| `/stop_listener` | POST | Stop Zigbee packet capture |
| `/run_calibration` | POST | Run sigmoid calibration for all registered device IDs |
| `/toggle_motors` | POST | Enable/disable individual motor drivers |
| `/status` | GET | Return current angle and Motor 2 position |
| `/log_tail` | GET | Return last 5 lines of execution log |
| `/cleanup` | POST | GPIO cleanup and shutdown |

**Profile format** (CSV-like, stored in `./profiles/`):
```
command, position, angle, duration, log, axis
home,0,0.0,0,true
move,1,0.0,0,true
ramp,1,6.0,600,true,pitch
move,2,0.0,0,true
ramp,2,6.0,600,true,roll
```

Supported commands: `home`, `move`, `ramp`. The `axis` field (`pitch` / `roll`) writes to `profile_status.txt` as an IPC signal to the data listener for correct file labeling.

**IPC:** `profile_status.txt` — written by the Flask server to signal the active ramp axis to the concurrent listener process:
- `0` = idle
- `1` = pitch ramp active
- `2` = roll ramp active

---

### `sigmund.py` — Sigmoid Calibration Script

Runs per-device after data collection. Called automatically via `/run_calibration` endpoint.

**Algorithm:**
1. Load raw CSV (timestamp, pitch, roll, mrt_x, mrt_y, mrt_z)
2. Convert elapsed time to angular degrees using `RATE_DEG_PER_SEC`
3. Isolate sigmoid regions by timestamp for pitch and roll
4. Fit 4-parameter sigmoid: `σ(θ) = a / (1 + exp(-b(θ - c))) + d`
5. Compute linear range analytically: `x = c ± (1/b) * ln(√((1 + √(1-r)) / (1 - √(1-r))))` at `r = 0.6`
6. Extract counts-per-degree coefficient within linear range
7. 2-point cross-calibration for MRT X/Y axes against calibrated primary axis
8. Append calibrated columns to output CSV

**Dependencies:** `numpy`, `pandas`, `scipy`, `matplotlib`

---

## Calibration Procedure

1. Place sensors on stage, record device IDs
2. SSH into Pi or navigate to `http://<pi-ip>:5000` in a browser
3. Home both axes (`/home`, `/home2`)
4. Enter device IDs and start listener (`/start_listener`)
5. Run calibration profile (`/run_profile`) — executes pitch ramp, rotation, roll ramp automatically
6. Stop listener (`/stop_listener`)
7. Run calibration fitting (`/run_calibration`) — processes all device CSVs
8. Retrieve calibrated output CSVs

---

## Results

Empirically verified against calibrated reference sensors:

```
RATE_actual     = 0.009258°/sec  (narrow-range calibrated HRT reference)
PITCH COEFF     = 4.906e-05 deg/count
ROLL COEFF      = 5.844e-05 deg/count
MRT_X:  coeff = -3.997e-03,  offset = 917.50
MRT_Y:  coeff =  3.814e-03,  offset = -2587.05
```

---

## Repository Structure

```
/
├── stepper_dual_flask.py     # Main Flask controller (runs on Pi)
├── read_hrt_v3.py            # Zigbee packet listener + CSV logger
├── sigmund.py                # Sigmoid fitting + calibration
├── profiles/                 # Saved calibration profiles
├── hrt_samples/              # Raw and calibrated CSV data
├── docs/
│   ├── HRT_Sigmoid.pdf       # Calibration theory and sigmoid math
│   ├── HRT_Calibrate.pdf     # Mechanical constants derivation
│   └── architecture.md       # System architecture overview
├── templates/
│   └── index.html            # Browser-based control UI
├── allowed_ids.txt           # Active device ID list
├── profile_status.txt        # IPC: active ramp axis signal
├── execution_log.txt         # Timestamped operation log
└── README.md
```

---

## Dependencies

```
# On Raspberry Pi
pip install flask RPi.GPIO

# For calibration (can run off-Pi)
pip install numpy pandas scipy matplotlib
```

---

## License

MIT
