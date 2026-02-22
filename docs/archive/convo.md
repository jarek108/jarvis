<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# I have prepared a feature request doc for my local conversational agent. I want to introduce a flexible, customizable architecture as described in the doc.  we want to create a design section with decisions about architectural, SE and tech stack choices.  for now do not write  yet or do external research, just analyze the doc and ask critical clarification questions to me needed before a deep search

Based on your `CONCEPT_CLIENT_ARCHITECTURE.md`, I have analyzed the proposed "Modular Interaction Pipeline" and identified several critical architectural and technical decisions that need clarification before we can draft the design section.

Here are the key questions grouped by domain:

### 1. Architecture \& Concurrency

* **Communication Protocol:** The doc mentions an API to "load/unload pipelines" and "diverse data types concurrently" (streams vs. messages).
    * *Question:* Are you envisioning a unified **WebSocket** connection for both control signals and media streams, or a hybrid approach (e.g., gRPC for streams, REST for control)?
* **Concurrency Model:** Given Python's GIL and the need for high-throughput streaming (Audio/Video in $\rightarrow$ Audio/Events out), `sts_server.py` might hit bottlenecks.
    * *Question:* Should we design for `asyncio` within a single process, or use **multiprocessing/microservices** to isolate heavy compute (VLM/LLM) from the I/O layer?
* **Event Bus:** You mention pipelines producing "Events" (`audio_chunk`, `control_signal`).
    * *Question:* Is this an internal in-memory event loop (e.g., Python `queue.Queue`), or do we need a formal broker (e.g., ZeroMQ, Redis Pub/Sub) to allow future decoupled clients/services?


### 2. Resource Management (The "Cognitive Loadout")

* **Model Swapping Latency:** You mention "unloading Whisper to load a larger VLM." Even on NVMe, loading 30B+ models takes seconds.
    * *Question:* Is a "loading screen" delay acceptable when switching modes (e.g., from Chat to Deep Dive), or do we need a **Tiered Memory Strategy** (keep models warm in system RAM) to minimize downtime?
* **VRAM Arbitration:** The "Smart Allocator" manages the 24GB+ budget.
    * *Question:* If a "Router Mode" (always on) decides to trigger "Visual Chat," does the router model stay loaded, or is it evicted? Do we need a dedicated "Small Language Model" (SLM) that *always* resides in VRAM for routing?


### 3. State \& Context

* **Context Persistence:** Moving between "pipelines" (e.g., `STS` $\rightarrow$ `Deep Dive`) implies a shift in logic.
    * *Question:* Does conversation history/context persist across pipeline switches? Do we need a shared **State Store** (e.g., a lightweight vector DB or JSON store) that all pipelines read/write to?
* **Client vs. Server Logic:**
    * *Question:* For "VAD-Gated" and "Sentry Mode," does the **Client** perform the initial detection (to save bandwidth/latency) and only send relevant frames/audio, or does the **Server** ingest the raw stream and filter it?


### 4. Tech Stack Specifics

* **Vision Ingestion:**
    * *Question:* For "Active Monitor" (video stream), how should we handle frame ingestion? Sending raw frames via WebSocket is heavy. Should we implement **WebRTC** for video, or is a simple MJPEG/frame-sampling approach sufficient for local LAN usage?
* **Agentic Routing:**
    * *Question:* The "Router Mode" emits `delegate_action`. Does the **Server** execute these actions (e.g., running Python code, web search), or does it send the instruction back to the **Client** to execute?

Once you clarify these points, I can structure the specific **Design \& Decisions** section with appropriate trade-off tables.
<span style="display:none">[^1]</span>

<div align="center">⁂</div>

[^1]: CONCEPT_CLIENT_ARCHITECTURE.md

