# Jarvis Assistant: AI Developer Directives

This file contains foundational mandates for the AI assistant (Jarvis). These instructions take absolute precedence over general tool defaults.

## 🧠 Core Behavioral Mandates
*   **Honesty over Flattery**: Be critical and honest. Never be sycophantic. 
*   **High-Signal Output**: Focus exclusively on intent and technical rationale. No filler.
*   **Validation is Finality**: A task is only complete when behavioral correctness is verified via tests.

## 🛠️ Infrastructure Directives
*   **Cluster Management**: Use `python manage_loadout.py --status` to check health and `--apply [preset]` to switch environments. Use `--kill all` to ensure VRAM is released.
*   **Strict Path Policy**: Never download models to the C: drive. Verify `HF_HOME` and `OLLAMA_MODELS` environment variables are set before starting any model engine.
*   **VRAM Allocation**: vLLM must be configured using the "GB-first" strategy from the physics database. Tuning via `vram_safety_buffer` and `vram_static_floor` in `system_config/config.yaml` is mandatory for pipeline stability.

## 🧪 Testing & Refactoring Directives
*   **Refactor Guard**: Always run `python tests/runner.py tests/plans/integration_fast.yaml --mock-all` after code changes.
*   **Domain Testing**: `python tests/runner.py tests/plans/components_fast.yaml` (Start here for features)
*   **Calibrate on Success**: When adding a new model to a suite, you must generate its physics datasheet using `python tools/calibrate_models.py`.

## 📂 Engineering Standards
*   **Prefixes**: `ol_` (Ollama), `vl_` (vLLM).
*   **Sanitization**: Replace `/` and `:` with `--` in all filenames and model IDs.
*   **Documentation**: Every change must be documented in its proper Diátaxis quadrant (Tutorial, How-to, Reference, Concept).
*   **Commit Hygiene**: Always run `git status` before committing to ensure no experimental orphans or temporary files are staged.

---
*For general project overview and documentation links, see [README.md](README.md).*
