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
Controls the Dockerized inference engine behavior.

```yaml
vllm:
  check_docker: true        # If false, skips Docker daemon checks (useful for native vLLM)
  model_startup_timeout: 800 # Seconds to wait for vLLM to become ready
  
  # Default VRAM usage (0.0 - 1.0) if no specific map entry exists
  gpu_memory_utilization: 0.5 
  
  # Specific VRAM allocation per model (in GB).
  # Used to calculate the --gpu-memory-utilization flag dynamically.
  model_vram_map:
    "qwen2.5-0.5b": 3.0
    "qwen3-vl-30b": 30.0
    "default": 30.0
    
  # Context window overrides (max tokens)
  model_max_len_map:
    "qwen3-vl-30b": 16384
    "default": 32768
    
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
