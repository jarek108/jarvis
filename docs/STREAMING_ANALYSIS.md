# System Streaming Capabilities Analysis

This document details the current state of "Streaming" vs "Non-Streaming" implementations across the Jarvis domains (STS, LLM, VLM, TTS). It evaluates the capability to benchmark these modes side-by-side to measure latency (TTFT) and throughput (TPS) trade-offs.

## Executive Summary

| Domain | Streaming Support | Non-Streaming Support | 1:1 Benchmarking | Status |
| :--- | :--- | :--- | :--- | :--- |
| **STS** | ✅ **Yes** | ✅ **Yes** | ✅ **Active** | Fully implemented in server & tests. |
| **LLM** | ✅ **Yes** | ⚠️ **Partial** | 🔄 **In Progress** | Client refactored to support `stream=False`. |
| **VLM** | ✅ **Yes** | ⚠️ **Partial** | 🔄 **In Progress** | Client refactored to support `stream=False`. |
| **TTS** | ❌ **No** | ✅ **Yes** | ❌ **N/A** | Atomic generation only. "Streaming" handled via STS pipeline. |

---

## 1. Domain: STS (Speech-to-Speech)
**The Pipeline:** `Audio Input -> STT -> LLM -> TTS -> Audio Output`

*   **Current Status:** **Excellent.**
    *   **Server:** Implements distinct endpoints:
        *   `/process` (Non-Streaming): Sequential execution. Returns a single WAV file.
        *   `/process_stream` (Streaming): Pipelined execution. Returns a custom binary stream of JSON events and raw PCM/WAV chunks.
    *   **Testing:** `tests/sts/test.py` automatically executes both modes for every scenario, providing direct latency comparisons.
*   **Recommendation:** No changes needed. This is the reference implementation.

## 2. Domain: LLM (Large Language Model)
**The Engine:** `Ollama` or `vLLM` (Text Generation)

*   **Current Status:** **Streaming Only.**
    *   **Server:** Supports both modes via the OpenAI-compatible API (`stream=True/False`).
    *   **Testing:** The test client (`tests/llm/test.py`) is currently **hardcoded** to request `stream=True` and parse Server-Sent Events (SSE). It cannot handle standard JSON responses.
*   **Path to 1:1 Benchmarking:**
    *   **Refactor Client:** Update `tests/llm/test.py` to accept a `stream` toggle.
    *   **Update Runner:** Configure the test lifecycle to run the suite twice (once for each mode).
*   **Expected Gains:**
    *   **Throughput (TPS):** Non-streaming often yields slightly higher TPS due to reduced protocol overhead.
    *   **TTFT Baseline:** Establishes a "worst-case" latency baseline to contrast with streaming.

## 3. Domain: VLM (Vision Language Model)
**The Engine:** `Ollama` or `vLLM` (Text Generation from Images)

*   **Current Status:** **Streaming Only.**
    *   Mirrors the LLM domain issues. `tests/vlm/test.py` is hardcoded to `stream=True`.
*   **Path to 1:1 Benchmarking:**
    *   Apply the same refactoring logic as the LLM domain.
    *   *Note:* Validation required to ensure `vLLM` and `Ollama` image payload formats remain compatible in non-streaming mode.

## 4. Domain: TTS (Text-to-Speech)
**The Engine:** `Chatterbox` (Audio Synthesis)

*   **Current Status:** **Non-Streaming Only.**
    *   **Server:** The `/tts` endpoint is atomic. It accepts text and returns a complete WAV file.
    *   **"Streaming" via STS:** The system achieves a streaming user experience by chunking text at the **STS Server** level. The STS server splits LLM output into sentences and requests individual, atomic TTS generations.
*   **Analysis of Server-Side Chunking:**
    *   **Concept:** The TTS server could theoretically accept a long text and return a list of WAV files (or a multipart stream) as they are generated.
    *   **Critical Constraints:**
        1.  **Redundancy for STS:** The primary conversational loop receives text *token-by-token*. The STS server *must* perform sentence buffering itself. A TTS chunker would sit idle waiting for input, negating any benefit.
        2.  **Protocol Complexity:** Streaming audio is complex. You cannot simply concatenate WAV files (headers break players). You must use raw PCM, a container format (OGG/MP3), or a custom framing protocol.
        3.  **Use Case Mismatch:** Server-side chunking benefits *long-form reading* (e.g., "Read this PDF"), not conversational turns.
*   **Recommendation:** **Keep TTS Atomic.**
    *   Maintain the TTS server as a high-speed, stateless "sentence-to-audio" engine.
    *   Handle "Long Text" chunking at the **Client** or **Orchestrator** level (e.g., the STS server or Client App), where the full text state is managed.

---

## 5. Workplan: Streaming Parity & Verification

### Phase 1: VLM Refactoring (Immediate)
Bring VLM to parity with LLM.
*   **Task:** Refactor `tests/vlm/test.py` to support `stream=True/False` toggling.
*   **Detail:** Implement robust JSON parsing for both Ollama (standard JSON) and vLLM (OpenAI-compatible) payloads in non-streaming mode, handling image payload nuances.

### Phase 2: Scenario-Level Configuration
Empower the test plan to explicitly control streaming behavior.
*   **Task:** Update `tests/llm/scenarios.yaml` and `tests/vlm/scenarios.yaml`.
*   **Detail:** Introduce a `stream` parameter (default: `true`).
*   **Integration:** Update `tests/llm/test.py` and `tests/vlm/test.py` to respect this parameter.
*   **Refactor Runner:** Ensure `run_test_suite` can iterate over scenario configurations rather than hardcoded dual execution, or provide a "compare" mode that forces both.

### Phase 3: Long-Form Test Scenarios
Add scenarios designed to highlight the TTFT advantage of streaming.
*   **Task:** Create new scenarios in `tests/llm/scenarios.yaml`.
*   **Detail:** Add "Long Story" (1000+ tokens) and "Code Generation" tasks.
*   **Goal:** Demonstrate the massive latency delta between Streaming (TTFT < 1s) and Batch (TTFT > 10s) for long outputs.

### Phase 4: Plan Updates
Update all standard plans to utilize the new capabilities.
*   **Task:** Update `tests/plans/ALL_exhaustive.yaml` and domain-specific plans.
*   **Detail:** Include explicit comparisons (e.g., `Story Gen [Stream]` vs `Story Gen [Batch]`) to visualize the performance trade-offs in the dashboard.
