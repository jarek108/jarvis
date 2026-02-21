# Tutorial: Contributing to Jarvis

This guide explains the engineering standards and development workflows required to maintain the high performance and reliability of the Jarvis ecosystem.

## 1. The Developer's "Golden Rule"
Before committing ANY code change, you must run the **Refactor Guard**. Jarvis is a complex real-time system; small logic changes can break the STS pipeline in subtle ways.

```powershell
# Run the Refactor Guard (Plumbing Mode)
# This simulates the entire cluster using lightweight stubs (No GPU required)
python tests/runner.py tests/plans/ALL_fast.yaml --plumbing
```

## 2. Strict Path Policy (Anti-Bloat)
To prevent accidental 100GB+ model downloads to the system drive (C:), Jarvis enforces a strict environment policy. It will **exit immediately** if these variables are missing:

*   **`HF_HOME`**: Must point to your HuggingFace cache (e.g., `D:\ML_Cache\huggingface`).
*   **`OLLAMA_MODELS`**: Must point to your Ollama store (e.g., `D:\Ollama\models`).

## 3. Naming & Sanitization
Consistency is critical for automated reporting and cross-platform compatibility.

### Prefixes
*   Use `ol_` for Ollama models (e.g., `ol_qwen2.5:0.5b`).
*   Use `vl_` or `vllm:` for vLLM models (e.g., `vl_qwen--qwen2.5-0.5b`).

### Filenames
When model names are used in file paths (logs, audio artifacts), illegal characters (`/`, `:`) must be replaced with double-hyphens (`--`).
*   **Bad**: `qwen/qwen2.5:0.5b.log`
*   **Good**: `qwen--qwen2.5-0.5b.log`

## 4. Commit Hygiene
Jarvis development often involves multi-file refactors (Logic + Tests + Docs). Follow these steps for every commit:

1.  **Verification**: Run the project-specific linting or type-checking if available.
2.  **Audit**: Run `git status` to ensure renames, deletions, and research artifacts (e.g., `research/` or `utils/test_*.py`) are not left behind.
3.  **Staging**: Use inclusive staging (e.g., `git add -A`) unless atomic commits are specifically requested.
4.  **Messaging**: Focus on **why** the change was made, not just **what** was changed.

## 5. System Health Checks
During development, use the loadout manager to monitor the state of the local cluster:
```powershell
# Check for zombie processes or stuck ports
python manage_loadout.py --status

# Kill everything to reset the GPU state
python manage_loadout.py --kill all
```
