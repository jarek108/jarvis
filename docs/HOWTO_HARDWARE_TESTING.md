# How-To: Realistic Hardware Testing

This guide explains how to verify Jarvis hardware interaction logic using either virtualized environments or physical verification.

## 1. Running Virtualized Tests (The Default)
By default, the test runner drives your **actual production code** using deterministic virtual devices. No flags are required to enable this.

### Prerequisites (Windows)
1. Install **[VB-Audio Virtual Cable](https://vb-audio.com/Cable/)**.
2. Set your system "Default Recording Device" to **CABLE Output**.
3. Set your system "Default Playback Device" to **CABLE Input**.

### Execution
```bash
python tests/runner.py tests/plans/abstraction_verification.yaml
```

### What happens?
- The runner automatically spawns **Audio Feeders** to simulate a user speaking.
- It programmatically toggles the `ptt_active` signal.
- The production `execute_ptt_mic` script "hears" the virtual file and captures it.

---

## 2. Running Physical Smoke Tests
Physical smoke tests verify that your real hardware (RTX 5090, Microphone, Screen) is healthy and recognized by the OS.

### Execution
Run the standalone smoke suite:
```bash
python tools/smoke_hardware.py
```

### Tests Performed
1. **GPU Check**: Verifies the RTX 5090 is active and reports VRAM baseline.
2. **Screen Check**: Captures a screenshot and opens it in your default viewer.
3. **Mic Check**: 
    - Prompts you to hold the **SPACE BAR**.
    - Records 2 seconds of real audio.
    - Plays it back to you via the speakers.

---

## 3. Mocking Components for Speed
If you only want to test logic without hardware or real models, use the orthogonal mock flags.

| Goal | Command |
| :--- | :--- |
| Test without 5090 (Mock Models) | `python tests/runner.py [plan] --mock-models` |
| Test without Drivers (Mock Edge) | `python tests/runner.py [plan] --mock-edge` |
| Fast Plumbing (Both) | `python tests/runner.py [plan] --mock-all` |

