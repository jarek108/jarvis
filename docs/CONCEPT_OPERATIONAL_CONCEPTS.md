# Concept: Operational Concepts & System State

This document defines the core concepts that govern the behavior, logic, and resource management of Jarvis. These elements determine the system's "Status" at any given microsecond.

## 1. Operational Mode (The Behavioral Template)
*   **Role**: A logical blueprint defining how Jarvis interacts with the user.
*   **Definition**: Stored in `operation_modes.yaml`. It determines input/output modalities, trigger strategies, and cognitive constraints.
*   **States**: `text_chat`, `visual_chat`, `sentry_mode`, `active_copilot`.

## 2. Loadout (The Physical Implementation)
*   **Role**: The specific set of AI models loaded into VRAM.
*   **Relation**: Must satisfy the requirements of the active **Operational Mode**.
*   **Management**: Handled by the `ResourceManager` using a "Smart Hot-Swap" strategy to fit within the 32GB VRAM budget.

## 3. Inference Triggering Mode (The Spark)
Determines the logic that initiates a processing turn.
*   **Manual**: Direct user initiation (e.g., Click-to-Speak).
*   **Continuous (Best-Effort)**: A loop at a desired frequency ($N$ Hz). The system is sequential: it only checks for the next frame/input once the current turn is finalized. Missed frames are ignored to prevent lag accumulation.
*   **Event-Based**: Triggered by external tool completions or system signals. These events are queued and processed collectively at the start of the next turn.

## 4. Input Modality (The Senses)
The data channels Jarvis is currently "watching" or "listening" to.
*   **Modality Types**: `text`, `audio_stream` (PCM), `image_payload` (Base64), `video_frame`.
*   **Gating**: Channels are only active if permitted by the current **Operational Mode**.

## 5. Context Composition (The Logic)
Jarvis follows a **Stateless Turn** architecture. It does not maintain an "ongoing" context in the model; instead, it reconstructs the entire context for every single inference turn.
*   **Component A: System Prompt**: Static instructions and persona definitions from the **Operational Mode**.
*   **Component B: History Window**: A sliding window of the last $H$ turns retrieved from the Session Manager ($H=0$ implies a stateless mode).
*   **Component C: Turn Composition**: The logic that flattens the **System Prompt + History + Tool Queue** into a single message list for the LLM.

## 6. Tool Queue (Observations)
*   **Role**: A buffer for asynchronous data arriving from tools (Gemini CLI, local scripts, MCP servers).
*   **Logic**: Observations are added to the queue as they arrive. They are "consumed" and injected into the context during the next **Context Composition** cycle.

## 7. Output Modality (The Expression)
How the system delivers its response.
*   **Modality Types**: `audio_stream` (TTS), `text_token` (Streaming), `hud_metadata` (Overlays), `control_signal` (System Actions).

## 8. Pipeline Phase (Internal Status)
The transient state of the Orchestrator's state machine, broadcasted to the client.
*   **Phases**: `IDLE`, `LOADING` (Resource swap), `THINKING` (Inference), `SPEAKING` (TTS).
