# How-To: Realistic Hardware Testing

This guide explains how to verify Jarvis hardware interaction logic using either virtualized environments or physical verification.

## 1. Running Virtualized E2E Tests
Virtualized E2E tests run the **actual production code** for hardware interaction but drive it using deterministic virtual devices.

### Prerequisites (Windows)
1. Install **[VB-Audio Virtual Cable](https://vb-audio.com/Cable/)**.
2. Set your system "Default Recording Device" to **CABLE Output**.
3. Set your system "Default Playback Device" to **CABLE Input**.

### Execution
Run the test runner with the `--e2e` flag:
```bash
python tests/runner.py tests/plans/abstraction_verification.yaml --e2e
```

### What happens?
- The runner spawns an **Audio Feeder** task.
- It programmatically plays `tests/data/polish.wav` into the Virtual Cable.
- It programmatically toggles the `ptt_active` signal.
- The production `execute_ptt_mic` script "hears" the file and captures it exactly as if you spoke.

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

## 3. Injecting Mocks for Logic Verification
If you only want to test the logical flow (plumbing) without any hardware or real models, use mock injection in your test plan.

### YAML Schema
In your test plan, add a `mapping` block:
```yaml
execution:
  - domain: "core"
    pipeline: "my_pipeline"
    mapping:
      proc_stt: "mock:This is a mock transcription."
      proc_llm: "mock:This is a mock AI response."
```

### Execution
```bash
python tests/runner.py tests/plans/my_plan.yaml --plumbing
```
