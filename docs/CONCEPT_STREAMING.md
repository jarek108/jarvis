# Concept: Streaming vs. Batch Performance

This document analyzes the architectural trade-offs between **Streaming** (token-by-token) and **Batch** (atomic) inference in the Jarvis ecosystem.

## 1. The Latency-Throughput Trade-off

| Metric | Streaming Mode | Batch Mode |
| :--- | :--- | :--- |
| **TTFT** (Time to First Token) | **Minimized**. User sees response immediately. | **High**. User waits for full completion. |
| **TPS** (Tokens Per Second) | Slightly lower (protocol overhead). | **Maximized**. Pure engine throughput. |
| **User Experience** | Fluid, "Alive." | Staccato, "Think-then-Speak." |

## 2. Domain Architectures

### STS (Speech-to-Speech)
Jarvis uses a custom binary protocol to stream mixed JSON metadata and raw PCM audio chunks. This allows TTS to begin speaking as soon as the first LLM sentence is completed, bypassing the need for the entire response to finish.

### LLM / VLM
Engines (Ollama/vLLM) support Server-Sent Events (SSE) for streaming. Jarvis benchmarks measure the TTFT delta to quantify the "Interaction Gap"—the time a user spends in silence before the AI starts responding.

### TTS (Text-to-Speech)
Jarvis keeps the TTS engine **Stateless and Atomic**. We do not stream raw audio bytes from the synthesizer because conversational turns are short. Instead, we achieve a streaming effect by chunking the LLM output into sentences and requesting atomic audio files for each.

## 3. Benchmarking Significance
By appending `#stream` to a model ID in a test plan, Jarvis runs the exact same scenario twice. This provides the empirical data needed to decide if a model's TTFT is low enough for a "Natural" conversation (typically < 800ms).
