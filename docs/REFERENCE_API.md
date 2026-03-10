# Jarvis API Reference

This document details the HTTP endpoints exposed by the internal Jarvis servers. These APIs are used for inter-service communication (STS Pipeline) and can be used to build custom clients.

## Data IO Ontology
The system categorizes all inputs and outputs into specific "Channels." These names are used in `OperationMode` definitions and Client/Server message schemas.

| Channel Name | Type | Input | Output | Priority | Usage Example |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **Microphone** | `aud` | ✔ | | **P0** | Voice commands/dictation. |
| **Selection** | `txt` | ✔ | | **P0** | Active window text context. |
| **Clipboard** | `txt` | ✔ | ✔ | **P0** | Direct OS-level read/write. |
| **Text File** | `txt` | ✔ | ✔ | **P0** | Local document manipulation. |
| **Chat UI** | `txt` | ✔ | ✔ | **P1** | Internal application state. |
| **Speaker** | `aud` | | ✔ | **P1** | Hardware audio output. |
| **Notification** | `txt` | | ✔ | **P1** | System toast/tray alerts. |
| **Screenshot** | `img` | ✔ | | **P2** | Static desktop capture. |
| **Image File** | `img` | ✔ | | **P2** | Static media ingestion. |
| **Video File** | `vid` | ✔ | | **P2** | Pre-recorded clip analysis. |
| **Camera** | `vid` | ✔ | | **P3** | Live webcam stream. |
| **Screen** | `vid` | ✔ | | **P3** | Live display monitoring. |

## 1. Speech-to-Text (STT) Server
**Default Port:** `8100` (Tiny), `8101` (Base), etc. (See `system_config/config.yaml`)

### `POST /transcribe`
Transcribes audio to text.

- **Content-Type:** `multipart/form-data`
- **Parameters:**
    - `file` (File): Audio file (WAV preferred).
    - `language` (String, optional): ISO language code (e.g., "en", "pl").
- **Response (JSON):**
    ```json
    {
      "text": "Hello world",
      "language": "en",
      "detected_language": "en"
    }
    ```
- **Headers:**
    - `X-Inference-Time`: Processing duration in seconds.

---

## 2. Text-to-Speech (TTS) Server
**Default Port:** `8200` (Eng), `8201` (Multi), etc.

### `POST /tts`
Synthesizes text into audio.

- **Content-Type:** `application/json`
- **Body:**
    ```json
    {
      "text": "Hello world",
      "voice": "default",
      "language_id": "en"
    }
    ```
- **Response (Binary):** `audio/wav` file.
- **Headers:**
    - `X-Inference-Time`: Processing duration in seconds.

---

## 3. Speech-to-Speech (STS) Server
**Default Port:** `8002`

### `POST /process` (Batch Mode)
Performs the full STT -> LLM -> TTS pipeline sequentially.

- **Content-Type:** `multipart/form-data`
- **Parameters:**
    - `file` (File): Input audio.
    - `language_id` (String, optional): Target language.
- **Response (Binary):** `audio/wav` (The final spoken response).
- **Headers:**
    - `X-Result-STT`: The transcribed input.
    - `X-Result-LLM`: The generated text.
    - `X-Model-*`: Metadata about models used.
    - `X-Metric-*`: Latency metrics.

### `POST /process_stream` (Streaming Mode)
Performs the pipeline with streaming. Returns a custom binary stream of mixed events and audio.

- **Content-Type:** `multipart/form-data`
- **Parameters:** Same as `/process`.
- **Response:** `application/octet-stream` (Custom framing protocol).
- **Stream Protocol:**
    - **Header:** `[Type: 1 byte][Length: 4 bytes]`
    - **Type 'T' (Text):** JSON payload `{role, text, start, end}`.
    - **Type 'A' (Audio):** Raw WAV bytes (chunk).
    - **Type 'M' (Metrics):** JSON payload (Final metrics).

---

## 4. Loadout Daemon
**Default Port:** `5555`

The Daemon manages the lifecycle of model engine processes (Whisper, Ollama, etc.) and provides centralized health monitoring.

### `GET /status`
Returns the current system health and daemon activity state.

- **Response (JSON):**
    ```json
    {
      "loadout_id": "Speech-to-Speech, light",
      "global_state": "READY",
      "ready": true,
      "active_task": null,
      "models": [
        {
          "id": "faster-whisper-base",
          "port": 8101,
          "state": "ON"
        }
      ],
      "vram": {
        "used": 1.2,
        "total": 31.8,
        "external": 0.0
      }
    }
    ```
- **Fields:**
    - `ready`: (Boolean) True if the Daemon is idle and can accept new lifecycle commands.
    - `active_task`: (String|null) "APPLYING" or "KILLING" if a background operation is ongoing.

### `POST /loadout`
Requests the activation of a named model suite.

- **Status Code:** `202 Accepted` (Success), `409 Conflict` (Busy)
- **Body:**
    ```json
    {
      "name": "Speech-to-Speech, light",
      "soft": true
    }
    ```

### `DELETE /loadout`
Shuts down all managed model processes.

- **Status Code:** `202 Accepted` (Success), `409 Conflict` (Busy)
- **Parameters:**
    - `force` (Boolean, default `false`): If true, ignores the busy lock and attempts an immediate cleanup.
