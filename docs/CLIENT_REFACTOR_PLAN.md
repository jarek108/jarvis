# Jarvis Client Refactor Plan

**Status:** Proposed
**Date:** February 11, 2026
**Target:** `jarvis_client.py` and associated UI components.

## 1. Diagnosis: Why the current UI is "Not Responsive"

The current client suffers from two primary issues affecting user experience:

1.  **Blocking I/O on Main Thread:** The current implementation processes heavy operations (like waiting for audio playback to finish via `sd.wait()` or handling large text logs) on the same thread as the UI rendering loop. In Python, despite threading, the **GIL (Global Interpreter Lock)** causes the UI to stutter during these CPU-bound or blocking I/O operations.
2.  **Hardware Initialization Latency:** The "Talk Delay" occurs because the microphone stream is opened (`p.open(...)`) *after* the user clicks the button. On Windows, initializing hardware audio drivers can take 200ms to 800ms, resulting in "dead air" and a perceived lack of responsiveness.

## 2. Architecture Proposal: Producer-Consumer Model

To solve this, we will restructure the client into three distinct, decoupled layers.

### Layer 1: The Engine (Headless)
*   **Role:** Handles all heavy lifting. Knows nothing about the UI.
*   **Components:**
    *   **Audio Engine:** Runs a continuous background thread ("Hot Mic") writing to a Ring Buffer.
    *   **Network Client:** Handles REST API calls to the S2S server.
    *   **State Monitor:** Polling loop for system health (`/health` endpoints).
*   **Communication:** Pushes events to a thread-safe `Queue`.

### Layer 2: The State Manager
*   **Role:** The "Single Source of Truth."
*   **Responsibility:** Holds the current state of the application (e.g., `current_loadout`, `active_models`, `selected_language`, `is_recording`).
*   **Logic:** Receives events from the UI and dispatches commands to the Engine.

### Layer 3: The UI (Consumer)
*   **Role:** Visualization and User Input.
*   **Responsibility:**
    *   Consumes the `Queue` every 50ms to update labels, text boxes, and indicators.
    *   Sends user intents (clicks) to the State Manager.
    *   **Zero Logic:** The UI code should contain almost no business logic.

## 3. Feature Implementation Plan

### A. "Hot Mic" Architecture (Zero Latency)
*   **Concept:** Open the audio stream *once* at application startup.
*   **Mechanism:** Maintain a 5-second "Rolling Buffer" in memory.
*   **Action:** When "Talk" is clicked, we instantly slice the buffer from `t-0.5s` (pre-roll) to capture the start of the utterance that might have slightly preceded the click.

### B. Loadout Management
*   **Location:** "Config" Tab.
*   **Features:**
    *   **Scanner:** Auto-populate a dropdown with YAML files from `tests/loadouts/`.
    *   **Editor:** An embedded text editor to modify loadout YAMLs directly.
    *   **Apply:** A button to trigger `manage_loadout.py --apply` with the selected config.

### C. Detailed Status Dashboard
*   **Goal:** Replace static labels with a "Smart Heartbeat."
*   **Logic:** Parse `config.yaml` to identify expected ports for the active loadout.
*   **Visuals:**
    *   🟢 **STT:** `faster-whisper-large-v3` (Online)
    *   🟢 **LLM:** `qwen2.5-72b` (Online)
    *   🔴 **TTS:** `chatterbox-turbo` (Offline/Error)

### D. TTS Language Selection
*   **UI:** Dropdown in Config tab (🇺🇸 EN, 🇵🇱 PL, 🇫🇷 FR, 🇨🇳 ZH).
*   **Data Flow:** This selection is passed as the `language_id` parameter in the JSON payload to the S2S server, routing the request to the appropriate synthesis logic.

### E. Interaction Modes
*   **Hold-to-Talk:** Standard walkie-talkie behavior (Mouse Down / Mouse Up).
*   **Toggle Mode:** Click to start, Click to stop. Useful for hands-free or long dictation.

## 4. Bonus "Pro" Functionalities

### Visual Audio Feedback (VU Meter)
*   **Why:** User confidence. "Is it hearing me?"
*   **Impl:** A simple progress bar or canvas rectangle that animates based on the RMS amplitude of the audio buffer.

### "Interrupt" Capability
*   **Why:** UX control.
*   **Impl:** Sending a cancellation signal to the S2S server to abort generation or stop audio playback immediately if the user speaks or clicks "Stop."

### Auto-VAD (Voice Activity Detection)
*   **Why:** Convenience.
*   **Impl:** Monitor audio energy levels. If silence > 1.5s while recording, automatically stop and send.

## 5. Next Steps
1.  **Refactor Audio Engine:** Implement the `AudioHandler` class with Ring Buffer support.
2.  **Refactor UI:** Split `JarvisClient` into `View` and `Controller` classes.
3.  **Implement Features:** Add the Loadout Editor and Status Dashboard.
