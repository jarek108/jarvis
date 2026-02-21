# Concept: Benchmark Reporting & Artifact Lifecycle

This document explains the architectural logic behind the Jarvis reporting system and how it manages large-scale benchmark data.

## 1. The Reporting Goal
The primary goal of Jarvis reporting is to provide **portable, highly visual, and deterministic** evidence of system performance. We translate raw execution traces into stylized Excel reports that link directly to the cloud-hosted media artifacts (audio/video) that generated them.

## 2. Artifact Categorization
Jarvis distinguishes between two types of artifacts to balance speed and reproducibility:

### A. Input Artifacts (Static Evidence)
*   **Examples**: Source `.wav` files for STT, `.mp4` files for VLM.
*   **Lifecycle**: Persistent and highly reused across different benchmark runs.
*   **Sync Logic**: Jarvis uses a "Link-if-Exists" strategy. It checks the cloud manifest once and only uploads missing files.

### B. Output Artifacts (Transient Results)
*   **Examples**: Synthesized `.wav` files from TTS, log files.
*   **Lifecycle**: Unique to a specific run ID. Never reused.
*   **Sync Logic**: Opt-in only. Because these can be massive, they are linked to **local paths** by default and only pushed to the cloud if explicitly requested via `--upload-outputs`.

## 3. "Turbo Sync" Architecture
To handle benchmarks with hundreds of scenarios, Jarvis uses a specialized synchronization engine:

1.  **Discovery Phase**: Scans the session's JSON results to build a list of all required local files before touching the network.
2.  **Manifest Pre-fetch**: Downloads the list of filenames already on Google Drive in one bulk request per folder.
3.  **Parallel Parallelism**: Uses a thread pool (default: 10 workers) to upload new files simultaneously, saturating bandwidth rather than waiting on sequential network round-trips.
4.  **Zero-Latency Linking**: The Excel generation phase uses the pre-fetched manifest to create hyperlinks instantly, without any further API calls.

## 4. Google Drive Hierarchy
Jarvis organizes its data into a clean, hierarchical structure:
*   `Jarvis/`: The master folder.
    *   `Inputs/`: Centralized store for reusable test media (audio/video).
    *   `Outputs/`: Parent for all benchmark results.
        *   `[RunID]/`: Unique folder per session containing generated audio and service logs.
    *   `Jarvis_Benchmark_Report_[RunID].xlsx`: The polished final reports.

## 5. Self-Healing Metrics
The Jarvis reporting engine is designed to be resilient. If a benchmark run fails to capture specific metrics (e.g., due to an older version of the runner or a network glitch), the generator implements **On-the-fly Recovery**:

*   **Audio Duration**: If missing, the engine locally opens the `.wav` files to calculate their exact length.
*   **RTF (Real-Time Factor)**: Calculated using the discovered duration and the execution time.
*   **WPS/CPS**: Derived from the character/word count of the input or result text and the inference duration.

This ensures that legacy logs can be re-processed into modern, data-rich reports.
