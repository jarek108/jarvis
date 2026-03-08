# Concept: Client UI Automation & Testing Suite

## 1. Vision & Objective
Jarvis requires a robust client-side testing framework to verify UI responsiveness, visual correctness, and state synchronization within the monolithic architecture. 

The goal is to move away from manual "click-and-watch" verification and establish an automated **"Puppet Master"** test runner. This runner will orchestrate fixed-timeline scenarios, simulating human interaction (clicks, holds) while performing non-blocking assertions on the UI's state and rendering performance.

---

## 2. Core Capabilities

### A. Strict Fixed-Timeline Scenarios (YAML)
Tests will be defined using a declarative YAML format structured around a strict, time-based execution loop (e.g., `t: 1.5s`). 
- **Why Fixed Timing?** If the UI is expected to display a status change 1.5 seconds after a button click, and it fails to do so, it represents a latency or responsiveness failure. The strict timeline explicitly enforces performance expectations.
- **Action Execution**: The runner will simulate events exactly at the requested timestamp relative to the start of the test.

### B. Real UI Action Automation
The runner will simulate human interaction directly against the Tkinter objects in the main thread.
- **Deterministic Invocation**: Actions will utilize direct widget invocation (e.g., `button.invoke()`, `event_generate("<Button-1>")`) rather than brittle, screen-resolution-dependent mouse emulation tools like `pyautogui`.
- **Supported Actions**: Clicking buttons, selecting dropdown options, holding/releasing the Push-to-Talk button.

### C. Tiered Status Dumps & Assertions
The suite will perform assertions by capturing "snapshots" of the application state at specific timeline marks.
- **System State Dumps**: Capturing the backend controller's internal state (e.g., `controller.health_state`, loaded model manifests, active pipeline ID).
- **UI Content Dumps (Shallow)**: Extracting text values from specific, high-value UI elements (Terminal output, Health Card statuses, Mode indicators). 
    - *Constraint*: To prevent the act of testing from artificially freezing the UI loop, deep recursive tree-walking is prohibited. Dumps must be shallow and targeted.
- **Visual Dumps (Screenshots)**: Capturing the bounding box of the active Jarvis window (using `mss`/`PIL`) to visually verify layout structures or graphical glitches.

### D. Self-Monitoring Test Infrastructure
The testing framework must not corrupt the results it measures.
- **Dump Latency Tracking**: Every `action: dump_ui_state` will be timed (`time.perf_counter()`).
- If extracting the UI state takes longer than a strict threshold (e.g., `5ms`), the test suite will emit a "Testing Infrastructure Overhead" warning to ensure the measurements remain reliable.

### E. Orthogonal Backend Mocking
The Client Test Runner will fully support the existing engine flags (`--mock-all`, `--mock-edge`, `--mock-models`).
- **Fast UI Verification**: Running with `--mock-all` will allow instant verification of UI logic (like Loadout switching or graph rendering) without waiting for 30B models to load.
- **Full E2E Client Tests**: Running without flags will allow the automated UI script to interact with physical hardware drivers and real GPU loadouts, verifying true end-to-end integration from the "Submit" button to the real Model API.

---

## 3. Example Scenario Schema
This schema demonstrates how the capabilities merge into a readable, executable test definition.

## 4. Implementation Phases

### Phase 1: The Asynchronous Puppet Master
The first goal is to prove we can reliably drive the Tkinter UI from a test script without blocking the main thread or causing rendering glitches.

*   **Actions:**
    1.  Create `tests/client_runner.py`.
    2.  Implement a custom asynchronous run loop that interleaves `app.update()` (for Tkinter rendering) with `asyncio.sleep()` and timeline tracking.
    3.  Implement the basic command-line interface, mirroring the backend runner flags (`--mock-all`, `--mock-models`).
    4.  Create a "dummy" test script that simply launches the app, waits 2 seconds, and closes it programmatically.
*   **Status at End of Phase:** The `client_runner.py` can successfully launch, render, and cleanly exit the `JarvisApp` entirely under programmatic control.

### Phase 2: Core Automations & Shallow Dumps
Enable the test runner to actually interact with the UI and measure the immediate state.

*   **Actions:**
    1.  Implement `AutomationController` with methods for programmatic interaction:
        *   `click_button(widget_path)` (using `.invoke()`)
        *   `select_dropdown(widget_path, value)`
    2.  Implement the `StatusDumper`:
        *   System state extractor (reads `app.controller.health_state`).
        *   UI state extractor (reads specific `.cget("text")` properties based on widget paths).
    3.  Implement the latency self-monitor wrapper for the dump functions.
*   **Status at End of Phase:** The test runner can programmatically change the loadout via the dropdown, verify the resulting internal health state, and confirm that the "Testing Infrastructure Overhead" remains under 5ms.

### Phase 3: Visual Verification
Implement the ability to capture exact visual states for layout regression testing.

*   **Actions:**
    1.  Integrate `mss` into the `client_runner`.
    2.  Implement `take_screenshot(filename)`: Calculate the absolute screen coordinates of the `JarvisApp` window (`winfo_rootx`, `winfo_width`) and crop the `mss` capture to exactly match the app boundaries.
    3.  Create a visual test scenario that forces a layout change (e.g., toggling between MAPPING and STATUS modes) and saves the resulting JPEGs.
*   **Status at End of Phase:** The test runner can generate pixel-perfect screenshots of the UI at specific timeline intervals, independent of the host monitor's resolution.

### Phase 4: YAML Scenario Parser & Integration
Unify the actions into the declarative YAML format to allow non-programmers to define complex UI tests.

*   **Actions:**
    1.  Create the `ClientScenarioParser` to ingest the YAML schema.
    2.  Implement the timeline execution engine that binds the `t: X.Xs` timestamps to the actual `AutomationController` and `StatusDumper` actions.
    3.  Author the `ui_loadout_switch_latency` and `ui_hold_to_talk_flow` scenarios.
    4.  Update the master `tests/plans/` to include a `client_fast.yaml` suite.
*   **Status at End of Phase:** A single CLI command (`python tests/client_runner.py tests/plans/client_fast.yaml`) will automatically launch the UI, execute a complex sequence of clicks and holds, verify textual and visual states, and generate a final Pass/Fail report.
