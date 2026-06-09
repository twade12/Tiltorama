# System Architecture

## High-Level Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    OPERATOR (Browser / SSH)                 │
│               http://<pi-ip>:5000                           │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP REST (WiFi / LAN)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  Raspberry Pi 4B (Headless)                 │
│                                                             │
│  ┌─────────────────────┐    ┌──────────────────────────┐   │
│  │  stepper_dual_flask  │    │     read_hrt_v3.py        │   │
│  │  (Flask REST API)    │───▶│  (Zigbee packet listener) │   │
│  │                      │IPC │  writes: hrt_samples/     │   │
│  │  profile_status.txt ◀────│  reads:  profile_status   │   │
│  └──────────┬───────────┘    └──────────────────────────┘   │
│             │                          ▲                     │
│             │ GPIO (BCM)               │ USB Serial          │
└─────────────┼──────────────────────────┼─────────────────────┘
              │                          │
    ┌─────────▼──────────┐    ┌──────────┴──────────┐
    │  Stepper Drivers   │    │  Resensys Zigbee     │
    │  Motor 1 (PUL/DIR) │    │  USB Receiver        │
    │  Motor 2 (PUL/DIR) │    └──────────────────────┘
    │  Limit SW 1 (GPIO) │              ▲
    │  Limit SW 2 (GPIO) │              │ 2.4GHz Zigbee
    └─────────┬──────────┘              │
              │                ┌────────┴──────────────────┐
    ┌─────────▼──────────┐     │  Up to 30x Resensys       │
    │  Tilt Stage        │     │  HRT + MRT Wireless Nodes  │
    │  Motor 1 → Ball    │────▶│  (on tilt stage surface)   │
    │    Screw → Z-lift  │     └───────────────────────────┘
    │  Motor 2 → Rotary  │
    │    (pitch / roll)  │
    └────────────────────┘
```

---

## Data Flow

```
Zigbee RF packets
       │
       ▼
read_hrt_v3.py (subprocess)
  - Filters by allowed_ids.txt
  - Reads profile_status.txt → labels axis in CSV
  - Writes: hrt_samples/<device_id>_<date>.csv
       │
       ▼
sigmund.py (per device, triggered via /run_calibration)
  - Loads CSV
  - Converts elapsed time → angle (RATE_DEG_PER_SEC)
  - Fits sigmoid to pitch + roll
  - Computes linear range analytically
  - Extracts counts/degree coefficient
  - 2-point calibration for MRT X/Y
  - Appends *_calibrated columns to CSV
       │
       ▼
Calibrated CSV output (hrt_samples/)
```

---

## IPC: profile_status.txt

The Flask server and the listener subprocess run concurrently. A simple file-based IPC signal coordinates axis labeling in the data files without requiring inter-process sockets:

| Value | Meaning |
|---|---|
| `0` | Idle — no ramp active |
| `1` | Pitch ramp active |
| `2` | Roll ramp active |

The listener reads this file periodically and stamps the current axis into the CSV row metadata, enabling `sigmund.py` to correctly split pitch and roll data during post-processing.

---

## Angular Kinematics

Motor 1 drives a vertical ball screw attached at distance L from the tilt pivot. The relationship between screw linear displacement h and tilt angle θ is:

```
h = L * sin(θ)
```

Steps required for a target angular displacement:

```
steps = h * γ    where γ = SPR / lead = 200 steps/rev ÷ 5 mm/rev = 40 steps/mm
```

This is implemented directly in `move_to_angle()`. The reverse (steps → angle) is not needed in normal operation since the controller tracks `current_angle_deg` in software.

---

## Profile Execution State Machine

```
START
  │
  ▼
home (motor1 + motor2)
  │
  ▼
move (position motor2 to pitch axis)
  │
  ▼
ramp (motor1: 0° → 6°, 600s, axis=pitch)
  │  ← profile_status = 1 during this step
  ▼
move (position motor2 to roll axis, 90° rotation)
  │
  ▼
ramp (motor1: 0° → 6°, 600s, axis=roll)
  │  ← profile_status = 2 during this step
  ▼
home (return to reference)
  │
  ▼
END → /run_calibration triggers sigmund.py for each device
```
