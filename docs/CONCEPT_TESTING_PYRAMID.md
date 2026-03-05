# Concept: The Jarvis Testing Pyramid

To ensure both rapid development and rock-solid production reliability, Jarvis employs a multi-tiered testing strategy. This "Pyramid" ensures that errors are caught at the lowest possible cost (VRAM and time).

---

## 1. The Pyramid Tiers

### Tier 0: Fast Infra Check (Unit/Logic)
**Command:** `python tests/backend/runner.py tests/backend/plans/integration_fast.yaml --mock-all`
*   **Goal**: Verify the "Plumbing."
*   **Realism**: Low. Replaces heavy models with stubs and hardware drivers with file-readers.
*   **Cost**: Near zero. No VRAM required.
*   **When**: Every code change.

### Tier 1: Component Audit (Integration/Isolation)
**Command:** `python tests/backend/runner.py tests/backend/plans/components_exhaustive.yaml --mock-edge`
*   **Goal**: Verify individual AI kernels (STT, LLM, TTS) in isolation.
*   **Realism**: Medium. Uses real models but bypasses hardware timing/IO.
*   **Cost**: Moderate VRAM.
*   **When**: When changing model versions or calibration data.

### Tier 2: Fast Deployment Check (Virtualized E2E)
**Command:** `python tests/backend/runner.py tests/backend/plans/integration_fast.yaml`
*   **Goal**: Smoke test the full production stack.
*   **Realism**: High. Uses real models and real hardware drivers (e.g., `pyaudio`). The environment is virtualized (e.g., Virtual Audio Cables).
*   **Cost**: Full VRAM for a single loadout.
*   **When**: Before a commit or pull request.

### Tier 3: Comprehensive Load Audit (Full E2E)
**Command:** `python tests/backend/runner.py tests/backend/plans/integration_exhaustive.yaml`
*   **Goal**: Stress test all model combinations and edge cases.
*   **Realism**: Maximum.
*   **Cost**: High. Loads multiple 30B+ models sequentially.
*   **When**: Before a major release or hardware change.

---

## 2. Hard-Crash Philosophy

Jarvis testing is designed to **underline deficiencies, not hide them.**

Unlike many CI systems that silently skip tests if hardware is missing, Jarvis tests (Tier 2 and above) will **hard-crash or fail loudly** if:
1.  **VRAM is insufficient** for the requested loadout.
2.  **Virtual Audio Cables** (e.g., VB-Cable) are not configured.
3.  **Webcam/Display** permissions are not granted.

**Why?** A successful test in Tier 2 or 3 is a guarantee of **Hardware Readiness**. Silent passes lead to false confidence and broken production deployments.

---

## 3. Mocking vs. Virtualizing

| Method | Flag | Target | Use Case |
| :--- | :--- | :--- | :--- |
| **Mocking** | `--mock-all` | The **Node** | Testing logic when hardware/models are unavailable. |
| **Virtualizing** | *(Default)* | The **Environment** | Testing the *real* code by feeding it fake inputs (WAV files). |

By default, the Test Runner acts as a **Virtual User**. It "presses" the PTT button and "speaks" into the virtual microphone using the `E2EOrchestrator`, ensuring that the code path tested is 100% identical to the one the user experiences.
