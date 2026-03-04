# Plan: Hardware Virtualization & Realistic E2E Testing

## 1. Objective
Achieve "Full-Loop" E2E testing where the **actual production code** for hardware interaction (Microphone, Screen, Keyboard) is executed, but the inputs and outputs are driven by a deterministic **Virtual Environment** instead of a physical user.

### Core Principles
- **No Mock Classes**: The production `execute_fn` logic is never swapped or modified for testing.
- **Environment Feeders**: The Test Runner creates "Senders" (e.g., playing audio into a virtual mic) and "Receivers" (e.g., a sandbox window to catch keystrokes).
- **Temporal Synchronization**: The runner orchestrates the timing between hardware triggers (PTT signals) and environment data flow.

---

## 2. Testing Hierarchy

### Level A: Logic/Plumbing (Current `--plumbing`)
- **Goal**: Verify packet flow and model logic.
- **Method**: Swaps implementation for a pure mock (e.g., `mock:text`).
- **Dependencies**: None.

### Level B: Virtualized E2E (New `--e2e` flag)
- **Goal**: Verify real hardware scripts, file-saving, and async loops.
- **Method**: Uses real `execute_fn` + OS-level Virtual Drivers/Feeders.
- **Dependencies**: Virtual Audio Cable (VB-Cable), GUI focus.

### Level C: Hardware Smoke (Standalone Scripts)
- **Goal**: Verify physical hardware state (5090 health, Mic unmuted).
- **Method**: Simple scripts that record real 2-second clips and show/play them back to a human.
- **Dependencies**: Real Hardware + Human.

---

## 3. Implementation Phases

### Phase 1: Edge Logic Migration (Prerequisite)
Migrate all remaining hardware logic from the legacy `utils/edge` classes into the unified `utils/engine/implementations.py` signature:
- **ScreenCapture**: Implement `execute_screen_capture` using `mss`.
- **KeyboardEmulation**: Implement `execute_keyboard_typer` using `pyautogui`.
- **ClipboardCapture**: Implement `execute_clipboard_sensor` using `pyperclip`.

### Phase 2: Environment Simulators (The "Senders")
Create `tests/test_utils/env_simulators.py` to provide cross-platform utilities:
- **Audio Feeder**: Plays a `.wav` file to a specific "Virtual Cable" output device.
- **Screen Feeder**: Opens a borderless, top-most GUI window (via `tkinter`) displaying a test pattern or image.
- **Keyboard Sandbox**: Opens a GUI window with a text area that records and timestamps incoming keystrokes for assertion.

### Phase 3: Runner Synchronization
Update `tests/runner.py` to support the `--e2e` workflow:
1. **Pre-flight**: Ensure virtual drivers are present.
2. **Setup**: Launch the necessary Simulators (e.g., start the Audio Feeder).
3. **Trigger**: Programmatically toggle signals (e.g., `ptt_active: True`).
4. **Execution**: Run the `PipelineExecutor` normally.
5. **Teardown**: Close Simulator windows and verify results.

### Phase 4: Hardware Smoke Suite
Create `tools/smoke_hardware.py` for physical verification.
- `check_mic()`: Records 2s and plays back.
- `check_screen()`: Takes screenshot and opens it in default viewer.
- `check_vram()`: Validates 5090 presence and baseline usage.

---

## 4. Technical Requirements & Dependencies
- **Windows**: [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) (Required for Mic E2E).
- **Linux**: `v4l2loopback` (Camera) and `PulseAudio` loopbacks (Audio).
- **Python**: `sounddevice` (for device-specific playback), `tkinter` (for simulator windows).

---

## 5. Success Criteria
1. A test scenario can run the `execute_ptt_mic` production code and "hear" a specific file played by the Test Runner.
2. A test scenario can run `execute_keyboard_typer` and the Test Runner can assert that the correct text was typed into the "Sandbox" window.
3. Zero "test-only" branches (e.g. `if testing:`) exist in the production implementations.
