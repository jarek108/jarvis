# Plan: System-Wide URI Convention Migration

This document outlines the strategy and implementation steps to unify the Jarvis ecosystem under the strict URI-style model definition string: `engine://canonical_id#params`. This migration resolves critical bugs related to model ID sanitization (e.g., vLLM failing to load models due to `--` in the repo ID) and removes legacy technical debt.

## 1. The Core Issue (vLLM Hub Error)
The error `huggingface_hub.errors.HFValidationError: Cannot have -- or .. in repo_id` is caused by a mix-up between **Canonical IDs** and **Sanitized (Safe) IDs**.

*   **The Problem:** The system was passing a sanitized ID (like `qwen--qwen2-vl-2b-instruct`) directly to vLLM via the `--model` flag. Hugging Face rejected this because `--` is an invalid sequence for repository names.
*   **The Solution:** The `engine://id#params` convention dictates that the `id` must always be the **Canonical ID** (e.g., `Qwen/Qwen2-VL-2B-Instruct`). The `safe_filename()` utility should only be used internally by Jarvis to generate local filenames (like logs and calibration YAMLs), never passed to the inference engine.

## 2. Implementation Phases

### Phase 1: Unify YAML Configurations (Test Plans)
All configurations in `tests/plans/*.yaml` must be updated to use strict URIs with Canonical IDs.
*   **vLLM:** `VL_qwen--qwen2-vl-2b-instruct#stream` $ightarrow$ `vllm://Qwen/Qwen2-VL-2B-Instruct#stream`
*   **vLLM (QuantTrio):** `VL_quanttrio--qwen3-vl-30b-a3b-instruct-awq#stream` $ightarrow$ `vllm://QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ#stream`
*   **Ollama:** `OL_qwen2.5:0.5b` $ightarrow$ `ollama://qwen2.5:0.5b`
*   **Ollama (GPT):** `OL_gpt-oss-20b` $ightarrow$ `ollama://gpt-oss-20b`
*   **Native STT:** `faster-whisper-tiny` $ightarrow$ `native://faster-whisper-tiny`
*   **Native TTS:** `chatterbox-turbo` $ightarrow$ `native://chatterbox-turbo`

### Phase 2: Refactor Test Infrastructure (`lifecycle.py`)
The test runner must be updated to treat the `engine://` URI as the absolute source of truth.
*   **Remove Engine Guessing:** Remove the logic in `identify_models` that guesses if a model is STT or TTS by checking `cfg['stt_loadout']`. The `native://` engine prefix, combined with the ID, provides this context.
*   **Standardize Display Names:** Update `format_models_for_display` to stop artificially prepending `OL_` and `VL_`. It should render the true engine and canonical ID.
*   **Update Resolution IDs:** Update the `res_id` generation to map to the new format (e.g., `vllm_Qwen/Qwen2-VL-2B-Instruct#CTX=8192`) instead of the legacy `VL_` format.

### Phase 3: Remove Tech Debt (Deprecate Fallbacks)
Once the YAMLs and test runner are natively speaking the URI language, we must remove the legacy fallback block (`if "://" not in entry:`) in `utils/config.py` to enforce the standard globally.

## 3. Key Decision Points & Trade-offs

*   **Strictness vs. Convenience:** Removing the legacy fallbacks in `config.py` will break custom `loadouts.yaml` files. *Decision:* Enforcing the URI standard eliminates "magic" parsing errors and reduces cognitive load. The short-term migration pain is worth the long-term stability.
*   **Historical Benchmark Continuity:** Changing `res_id` formatting will break the historical continuity of Excel benchmark reports. *Decision:* Accept this break. The new naming scheme accurately reflects the architecture.
*   **Canonical vs. Local Folder Names:** vLLM handles absolute/relative paths natively. As long as the raw string is passed after `vllm://`, vLLM will correctly interpret it as either a repo ID or a local path.