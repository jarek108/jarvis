# Feature Plan: Comprehensive Modality and Hardware Testing Audit

## 1. VISION
The "Unified Node Abstraction" established a solid foundation for treating hardware drivers and generative models identically. However, the system currently suffers from missing modalities (Camera, Clipboard Output), a monolithic implementation file, and incomplete hardware smoke tests. 

This feature initiative will complete the multimodal hardware suite, split the monolithic implementation file to isolate fragile OS dependencies, and expand the physical testing suite to guarantee a reliable user experience out-of-the-box.

## 2. ARCHITECTURAL REQUIREMENTS
*   **Dependency Isolation**: A failure to import a specific hardware library (e.g., `mss` for screen capture) MUST NOT prevent the system from loading and executing pipelines that do not require that modality.
*   **Symmetrical I/O**: Every sensory modality must have a corresponding actuator where logically possible (e.g., `ClipboardSensor` and `ClipboardWriter`).
*   **Pre-flight Integrity**: The hardware smoke tests must execute physical actions without requiring complex test scenarios.
*   **Graceful Degradation**: If a hardware driver is missing or lacks OS permissions, the pipeline engine must fail immediately during the validation handshake, not deep into execution.

## 3. IMPLEMENTATION PHASES

### Phase 1: Modality Completion
*   **Task**: Implement `execute_camera_capture` to grab frames from the system webcam.
    *   *Tooling*: Use `opencv-python` (`cv2.VideoCapture`).
    *   *Output*: Yields `IOType.IMAGE_FILE` or `IOType.IMAGE_RAW`.
*   **Task**: Implement `execute_clipboard_writer` to allow the LLM to copy text directly to the user's OS clipboard.
    *   *Tooling*: Use `pyperclip.copy()`.
    *   *Output*: Yields `IOType.SIGNAL` (Success).

### Phase 2: Modularize Implementations (De-Monolith)
*   **Task**: Create a `utils/engine/implementations/` directory.
*   **Task**: Split the current `implementations.py` into targeted modules:
    *   `models.py`: LLM, STT, TTS logic.
    *   `audio.py`: `pyaudio` and `sounddevice` logic.
    *   `vision.py`: `mss` and `opencv` logic.
    *   `os_tools.py`: `pyautogui` and `pyperclip` logic.
*   **Task**: Update `utils/engine/registry.py` to import from these modular files, wrapping imports in standard `try/except` blocks to allow partial engine loading if dependencies fail.

### Phase 3: Expanded Hardware Smoke Suite
*   **Task**: Update `tools/smoke_hardware.py` to become a comprehensive diagnostic tool.
    *   Add `smoke_camera()`: Grabs one frame and saves it for user review.
    *   Add `smoke_keyboard()`: Opens a small `tkinter` window and types a test string into it.
    *   Add `smoke_clipboard()`: Writes a random token, reads it back, and asserts equivalence.
    *   Add `smoke_speaker()`: Synthesizes a generic beep or plays a bundled `.wav` to verify audio out.

### Phase 4: Clean Up & Standardization
*   **Task**: Delete the deprecated `utils/edge/sensors.py` and `utils/edge/actuators.py` files to remove technical debt.
*   **Task**: Standardize the ID and Role naming in `registry.py` (e.g., `InputMic`, `OutputSpeaker`, `InputCamera`).
*   **Task**: Enhance `validate_fn` for hardware nodes to actually check for library presence and device availability (e.g., checking if `cv2.VideoCapture(0).isOpened()`).

## 4. KEY DECISION POINTS & TRADEOFFS

*   **Tradeoff: OpenCV vs. Native APIs for Camera**
    *   *Choice*: `opencv-python` is heavy (large binary size) but universally compatible across Windows/Linux/Mac. 
    *   *Consequence*: We take the binary size hit for the sake of avoiding complex OS-specific camera APIs (like DirectShow or V4L2).
*   **Decision: Lazy Loading vs. Try/Except Imports**
    *   *Choice*: We will use standard top-level `try/except ImportError` blocks in the new modular files, rather than lazy-loading libraries inside the `execute_fn`.
    *   *Consequence*: It keeps the execution loop fast and clean, but means memory is consumed by the imports at startup even if the pipeline doesn't use them. Given Jarvis is a heavy AI application, this memory footprint is negligible.
*   **Tradeoff: Automated Verification vs. Human-in-the-Loop Smoke Tests**
    *   *Choice*: The `smoke_hardware.py` script will remain partially human-in-the-loop (e.g., requiring the user to look at the saved camera frame).
    *   *Consequence*: We cannot run the entire smoke suite completely headlessly in CI without virtualizing the environment, but it provides the most accurate "real world" validation for a physical user setting up their rig.