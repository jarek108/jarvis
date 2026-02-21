<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# when I tun vLLM models I measure and store base (weight) VRAM usage and also the remaining VRAM space for KV storage and resulting token count that will fit in. this results in a config like:id: VL_Qwen/Qwen2.5-0.5B-Instruct

constants:
  base_vram_gb: 0.93
  kv_cache_gb_per_10k: 0.114031
metadata:
  calibrated_at: '2026-02-20 10:18:03'
  gpu_vram_total_gb: 31.8427734375
  source_tokens: 73664
  source_cache_gb: 0.84 can I have the same info (base vram use, kv tokens/vram GB) based on Ollama model logs? how

Yes, you can approximate the same metrics from Ollama, but you need to combine Ollama’s server logs (for KV cache size) with knowledge of the context length and, optionally, GPU VRAM readings.

Below is a minimal, “engineering‑useful” way to do it.

***

## What Ollama logs give you

Ollama’s server logs (server.log / journalctl) include lines from llama.cpp like this when a context is created:[^1][^2][^3]

```text
llama_new_context_with_model: KV self size = 1792.00 MiB, K (f16): 896.00 MiB, V (f16): 896.00 MiB
llama_new_context_with_model: CUDA0 compute buffer size = 164.01 MiB
llama_new_context_with_model: CUDA_Host input buffer size = 13.02 MiB
```

You can get these logs via e.g. `~/.ollama/logs/server.log` (mac), `journalctl -u ollama` (Linux), or `%LOCALAPPDATA%\Ollama\server.log` (Windows).[^4][^5]

The “KV self size” is the total reserved KV cache for the configured context length and concurrency (num_ctx × parallel slots), and it scales linearly with context length and depends on KV quantization (f16 vs q8_0 vs q4_0).[^6][^7][^1]

***

## Deriving “KV cache GB per 10k tokens”

Goal: estimate a `kv_cache_gb_per_10k` similar to your vLLM metric.

1. **Fix a known context length and single concurrency**
    - Set a context length explicitly via env or model param, e.g.:
`OLLAMA_CONTEXT_LENGTH=32768 ollama serve`.[^7]
    - Configure Ollama to run with a single parallel request (NUM_PARALLEL=1 / equivalent server settings) so the KV allocation is for one stream; otherwise Ollama may reserve KV for up to 4 parallel requests.[^6][^7]
2. **Trigger context creation and capture the log line**
    - Start the model once (e.g. `ollama run yourmodel`) so Ollama creates the context.
    - Grab the most recent KV line:
`grep "KV self size" ~/.ollama/logs/server.log | tail -n 1`.[^3]
    - Example: `KV self size = 1792.00 MiB`.
3. **Compute KV GB per 10k tokens**

Let:
    - $K_{\text{MiB}}$ = logged “KV self size” in MiB (e.g. 1792).
    - $L$ = effective context length in tokens for that run (num_ctx × parallel slots; with single parallel, this is just num_ctx).[^7][^6]

Then:

$$
K_{\text{GiB}} = \frac{K_{\text{MiB}}}{1024}
$$

$$
\text{kv\_cache\_gb\_per\_10k} \approx K_{\text{GiB}} \cdot \frac{10000}{L}
$$

For example, if `KV self size = 1792 MiB` at `num_ctx = 32768` and 1 parallel stream:
    - $K_{\text{GiB}} \approx 1792 / 1024 \approx 1.75$
    - $\text{kv\_cache\_gb\_per\_10k} \approx 1.75 \cdot 10000 / 32768 \approx 0.534 \text{ GB / 10k tokens}$.

Repeat per KV quantization (f16, q8_0, q4_0) if you use them, since q8_0 ≈ halves KV memory, q4_0 ≈ quarters it.[^7]

***

## Estimating “base VRAM” for weights

Ollama does not log “base weights VRAM” directly; you need one GPU‑side measurement plus the logged KV size.

1. **Run model in a “calibration” config**
    - Fix:
        - `OLLAMA_CONTEXT_LENGTH` to the value you used for the KV measurement above.[^7]
        - Same NUM_PARALLEL / concurrency settings.
        - Same KV quantization (`OLLAMA_KV_CACHE_TYPE`, default f16, or q8_0/q4_0 etc.).[^7]
    - Start `ollama serve` and `ollama run yourmodel`, then wait until it’s idle (no active generation).
2. **Measure total VRAM usage**
    - Use `nvidia-smi`, `rocm-smi`, or equivalent to read GPU memory used by the Ollama process at that idle point (VRAM_total_gb).
3. **Subtract pre‑allocated KV size**
    - Convert KV self size: `KV_gb = K_MiB / 1024`.
    - Estimate base:

$$
\text{base\_vram\_gb} \approx \text{VRAM\_total\_gb} - K_{\text{GiB}}
$$

This “base_vram_gb” captures model weights plus runtime buffers (compute buffers, input buffer, etc.), but is stable across context lengths for fixed quantization and architecture, similar in spirit to what you log for vLLM.[^8][^3]

***

## Lightweight automation idea

You can script this once and generate per‑model calibration similar to vLLM:

- Inputs per run: model name, num_ctx, KV type, measured VRAM_total_gb.
- Extract last `KV self size` via a simple `grep` on server.log.
- Compute:
    - `kv_cache_gb_per_10k` using the formula above.
    - `base_vram_gb` from VRAM_total_gb − KV_gb.

Store that in your config block:

```yaml
id: ollama/qwen2.5-0.5b-instruct-f16
constants:
  base_vram_gb: <computed>
  kv_cache_gb_per_10k: <computed>
metadata:
  calibrated_at: '...'
  num_ctx: 32768
  kv_type: f16
  gpu_vram_total_gb: <physical card size>
```

If you want, a minimal Python or shell script can read `server.log`, parse “KV self size”, and spit these numbers given `num_ctx` and a manual VRAM_total_gb measurement; the formulas above are all you need to match your existing vLLM calibration style.
<span style="display:none">[^10][^11][^12][^13][^14][^15][^16][^17][^18][^19][^20][^21][^22][^23][^24][^25][^9]</span>

<div align="center">⁂</div>

[^1]: https://blog.peddals.com/en/ollama-vram-fine-tune-with-kv-cache/

[^2]: https://www.reddit.com/r/ollama/comments/1cv3nu8/how_does_ollama_manage_vram_fitting_47gb_model_on/

[^3]: https://www.reddit.com/r/ollama/comments/1axxjnq/more_visibility_on_ollama_processing/

[^4]: https://www.llamafactory.cn/ollama-docs/en/troubleshooting.html

[^5]: https://docs.ollama.com/troubleshooting

[^6]: https://www.reddit.com/r/LocalLLaMA/comments/1j7r1sm/understanding_context_length_and_memory_usage/

[^7]: https://docs.ollama.com/faq

[^8]: https://geekbacon.com/2025/05/03/understanding-vram-usage-in-ollama-with-large-models/

[^9]: https://localllm.in/blog/ollama-vram-requirements-for-local-llms

[^10]: https://www.tigertriangle.tech/2024/11/check-if-ollama-is-using-your-gpu-or-cpu.html

[^11]: https://docs.ollama.com/context-length

[^12]: https://www.youtube.com/watch?v=on3rtyPWSgA

[^13]: https://localllm.in/blog/local-llm-increase-context-length-ollama

[^14]: https://windowsforum.com/threads/speed-up-local-llms-on-windows-11-by-tuning-context-length-with-ollama.377297/

[^15]: https://github.com/ollama/ollama/issues/7629

[^16]: https://www.reddit.com/r/LocalLLaMA/comments/1j6s34q/what_is_the_link_between_vram_and_context_length/

[^17]: https://github.com/ollama/ollama/issues/9555

[^18]: https://github.com/ollama/ollama/issues/7323

[^19]: https://github.com/ollama/ollama/issues/9774

[^20]: https://github.com/ollama/ollama/issues/11871

[^21]: https://github.com/ollama/ollama/issues/11619

[^22]: https://github.com/ollama/ollama/issues/9890

[^23]: https://www.reddit.com/r/SillyTavernAI/comments/1i794qk/kv_cache_size_of_each_model_per_token/

[^24]: https://www.rohan-paul.com/p/how-to-calculate-size-of-kv-cache

[^25]: https://github.com/home-assistant/core/issues/119946

