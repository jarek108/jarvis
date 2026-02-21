# How-to Guide: Using the Jarvis GUI

This guide explains how to interact with the Speech-to-Speech (STS) assistant via the `jarvis_client.py` graphical interface.

## 1. Starting the Assistant

Before launching the client, ensure your Jarvis cluster is running with a compatible STS loadout:

```powershell
# Apply a Speech-to-Speech loadout
python manage_loadout.py --apply base-qwen30-multi

# Launch the client
python jarvis_client.py
```

## 2. Interaction Patterns

### Talking to the Assistant
1.  **Click and Hold**: The assistant uses a **Push-to-Talk (PTT)** interaction model.
2.  **Speak**: While holding the "TALK" button, your voice is captured and buffered.
3.  **Release**: Releasing the button triggers the transcription (STT) and sends the request to the LLM.

### Visual Feedback
*   **VU Meter**: A real-time wave/level indicator shows your microphone's input volume.
*   **Status Indicators**:
    *   **LISTENING**: Currently capturing audio.
    *   **THINKING**: STT/LLM processing is underway.
    *   **SPEAKING**: The TTS engine is generating and playing response audio.

### Video Analysis (VLM Mode)
If your loadout includes a Vision-Language Model (VLM), the assistant can "see" your screen or a specific window.
1.  Ensure the "VIDEO" or "SCREEN" toggle is active in the interface.
2.  While talking, the assistant will slice frames from the active source and include them in the LLM prompt.

## 3. Configuration & Audio

### Selecting Devices
The client uses the default system audio devices. If you need to switch microphones or speakers:
1.  Change your default input/output device in the **Windows Sound Settings**.
2.  Restart the `jarvis_client.py`.

### Audio Buffering
Jarvis uses a 10-second ring buffer. This means if you start speaking *just before* pressing the talk button, the "pre-roll" (roughly 500ms) is often captured, ensuring your first word isn't clipped.

## 4. Troubleshooting the UI

*   **No Audio**: Check if another application (like Discord or Zoom) has exclusive control over the microphone.
*   **Laggy Response**: Verify that your GPU is not being throttled and that the `sts_server.py` is reachable on port `8002`.
*   **GUI Not Opening**: Ensure `customtkinter` and `PIL` are installed in your `jarvis-venv`.
