# How-to Guide: UI Automation & Testing

This guide covers how to run automated UI tests to verify window persistence, layout correctness, and state synchronization.

## 1. Quick Start
To verify UI integrity after code changes, run the fast-check suite with full mocking:

```powershell
python tests/client/runner.py tests/client/plans/client_fast.yaml --mock-all
```

## 2. Command Line Flags

| Flag | Purpose | Use Case |
| :--- | :--- | :--- |
| `plan` | Path to Plan YAML | **Required.** Defines scenarios to execute. |
| `--mock-all` | No models, No hardware | Instant UI/Logic verification (no VRAM required). |
| `--mock-models`| Fast stub models | Testing STT/TTS plumbing without heavy weights. |
| `--mock-edge`  | File-based I/O | Testing without a physical Mic or Screen. |
| `--fail-fast`  | Stop on first error | Rapid iterative debugging. |
| `--keep-alive` | No backend cleanup | Running tests against an active cluster. |

## 3. Investigating Failures
Every test run generates a session folder in `tests/logs/CLIENT_RUN_YYYYMMDD_HHMMSS/`.

1.  **Visual Proof**: Check the `images/` subfolder for screenshots taken at specific timeline marks (e.g., `boot_spin.jpg`, `loadout_final_state.jpg`).
2.  **State Snapshots**: Open `client_report.json` to see the exact logical state (Health, VRAM visibility, Maximization status) at the moment of failure.
3.  **Logs**: Review the terminal output for assertion details.

## 4. Scenario Lifecycle (YAML)
Tests are defined in `tests/client/scenarios/client_ui.yaml` using a strict timeline:

```yaml
ui_ux_initial_vram_boot:
  name: "Verify spinner active during initial boot scan"
  timeline:
    - t: 0.2s
      action: assert_ux_state
      condition: "spinner_active"
    - t: 15.0s
      action: assert_ux_state
      condition: "spinner_inactive"
```

*   **t**: Timestamp in seconds relative to app start.
*   **action**: The operation to perform (`click_element`, `select_dropdown`, `assert_system_state`, `assert_ux_state`).
*   **condition**: The logical check to perform.

## 5. Typical Operations

### Full UI Smoke Test
```powershell
python tests/client/runner.py tests/client/plans/client_fast.yaml --mock-all
```

### Verify Persistence after Maximization
```powershell
# Run stage 1 (maximize and save)
python tests/client/runner.py tests/client/plans/client_fast.yaml -s ui_ux_persistence_maximize_stage1 --mock-all
# Run stage 2 (restart and verify anchor)
python tests/client/runner.py tests/client/plans/client_fast.yaml -s ui_ux_persistence_maximize_stage2 --mock-all
```
