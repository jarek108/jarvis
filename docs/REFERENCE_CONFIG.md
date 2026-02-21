# Configuration Reference (`config.yaml`)

This document explains the settings available in the `config.yaml` file, which controls the behavior of the Jarvis infrastructure.

## 1. System Settings
```yaml
device: cuda  # Primary compute device ("cuda" or "cpu")
system:
  health_check_interval: 1.0  # Seconds between status polls in the dashboard
```

## 2. Paths
```yaml
paths:
  venv_python: "jarvis-venv/Scripts/python.exe" # Path to the specific Python executable to use for servers
```

## 3. Network Ports
Defines the static ports for various services. **Do not change these unless you have a conflict.**
```yaml
ports:
  ollama: 11434  # Native Ollama service
  vllm: 8300     # Dockerized vLLM
  sts: 8002      # Main pipeline server
```

## 4. Model Loadouts (Port Maps)
Maps specific model variants to dedicated ports. This allows running multiple models simultaneously if needed (e.g., during testing).
```yaml
stt_loadout:
  faster-whisper-tiny: 8100
  # ...
tts_loadout:
  chatterbox-eng: 8200
  # ...
```

## 5. vLLM Configuration
Controls the Dockerized inference engine behavior using **Model Physics** discovery.

```yaml
vllm:
  check_docker: true        # If false, skips Docker daemon checks
  model_startup_timeout: 800 # Seconds to wait for vLLM to become ready
  
  # Default context window for all models
  default_context_size: 16384
  
  # Safety net settings for models without a calibration YAML
  uncalibrated_safe_ctx: 8192
  uncalibrated_safe_vram_gb: 4.0
    
  # Specific context window overrides (if needed)
  model_max_len_map:
    "default": 16384
    
  # Multi-modal limits (JSON string)
  model_mm_limit_map:
    "default": '{"image": 8}'
```

## 6. Mock Mode
Settings for the simulated testing mode (`--mock`).
```yaml
mock:
  setup_range: [2.0, 5.0]     # Simulated startup time (seconds)
  execution_range: [0.3, 1.0] # Simulated inference time (seconds)
  failure_chance: 0.1         # Probability of a simulated error (0.0 - 1.0)
```
