<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# how about VL_QuantTrio/Qwen3-VL-30B-A3B? would it change anything?

Yes, switching to Qwen3‑VL‑30B‑A3B *does* change the picture: vLLM now has first‑class, documented OpenAI‑style video support for Qwen3‑VL, whereas Qwen2‑VL is still “Python‑only” for native video. The QuantTrio AWQ variant doesn’t change the API semantics, but it does change VRAM/perf characteristics.[^1][^2][^3]

***

## What Qwen3‑VL‑30B‑A3B adds vs Qwen2‑VL

Key differences relevant to your earlier constraints:

- **OpenAI `/chat/completions` + video is now a documented path.** vLLM’s multimodal docs explicitly show Qwen3‑VL‑30B‑A3B‑Instruct in examples for video handling and media I/O options (e.g. enabling frame recovery for that model).[^2][^3]
- **Qwen3‑VL is designed around Interleaved‑MRoPE** (multi‑dimensional rotary embeddings across time, H, W) for video reasoning and long contexts, similar in spirit to Qwen2‑VL’s M‑RoPE but upgraded for Qwen3‑VL’s DeepStack visual stack.[^4][^5][^1]
- **Video is a “first‑class modality” in recipes and tooling**, with vLLM CLI flags like `--limit-mm-per-prompt '{\"image\":3, \"video\":5}'` used in Qwen3‑VL‑30B‑A3B‑Instruct‑FP8 vLLM deployments.[^6][^7]

So if your goal is: “native video via vllm‑openai, not via custom Python `LLM` + `multi_modal_data`,” Qwen3‑VL‑30B‑A3B is aligned with that in a way Qwen2‑VL currently is not.[^3][^8][^2]

***

## API surface with Qwen3‑VL on vLLM

### JSON schema

There are two slightly different layers:

- **Qwen‑side examples (native tooling)** use entries like:

```json
{
  "role": "user",
  "content": [
    {
      "type": "video",
      "video": "https://.../space_woaudio.mp4",
      "min_pixels": 4 * 32 * 32,
      "max_pixels": 256 * 32 * 32,
      "total_pixels": 20480 * 32 * 32
    },
    { "type": "text", "text": "Describe this video." }
  ]
}
```

where `"video"` can be a URL, a local path, or a list of frame paths.[^1]
- **OpenAI‑compatible servers (SGLang / vLLM style)** use the standard OpenAI schema with `video_url` content:

```json
{
  "model": "Qwen/Qwen3-VL-30B-A3B-Instruct",
  "messages": [
    {
      "role": "user",
      "content": [
        { "type": "text", "text": "What’s happening in this video?" },
        {
          "type": "video_url",
          "video_url": {
            "url": "https://github.com/sgl-project/sgl-test-files/raw/refs/heads/main/videos/jobs_presenting_ipod.mp4"
          }
        }
      ]
    }
  ],
  "max_tokens": 300
}
```

This is shown in the Qwen3‑VL usage guide for SGLang’s OpenAI endpoint, and vLLM’s own multimodal docs describe `video_url` as the standard for video inputs.[^9][^2][^3]

vLLM’s multimodal feature docs further show that, for Qwen3‑VL‑30B‑A3B‑Instruct, you can tweak **media‑I/O behavior** via `--media-io-kwargs`, including `frame_recovery` for video decoding.[^3]

### Passing video parameters (fps, pixels, etc.)

- Qwen3‑VL’s HuggingFace processor API exposes `fps`, `num_frames`, and dynamic resolution settings (similar to Qwen2, but with Qwen3‑VL’s upgraded vision stack).[^10][^11]
- On the vLLM OpenAI path, users are passing extra arguments like:

```python
extra_body={
    "mm_processor_kwargs": {
        "fps": 5
    }
}
```

alongside `video_url`, but one issue reports that these kwargs were not yet fully honored for Qwen3‑VL (e.g., changing fps didn’t visibly affect behavior or resource usage).[^12]

So: **you gain native video_url support on `/chat/completions`**, but fine‑grained control over fps / pixel budgets via `mm_processor_kwargs` may still be evolving.

***

## QuantTrio AWQ flavor vs official Qwen3‑VL

The VL_QuantTrio repo (`QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ`) is an **AWQ‑quantized** variant of the official Qwen3‑VL‑30B‑A3B‑Instruct.[^13]

From the HF discussion:

- It *does* run under vLLM once the environment is configured correctly (`vllm >= 0.11.0`, `qwen-vl-utils`, etc.).[^14]
- A user initially hit vLLM issues due to `uv pip`, then resolved them by switching to plain `pip` and installing dependencies; after that, vLLM served the original Qwen3‑VL A3B fine.[^14]
- They note that VRAM usage was higher than expected (OOM on a 48 GB L40 for some configs) and recommend tuning `--limit-mm-per-prompt.video` and other parameters per the Qwen3‑VL usage guide.[^6][^14]

Important points for you:

- **Quantization doesn’t change modality support.** If the base model supports video via vLLM’s OpenAI server, the AWQ quant version will too, assuming vLLM supports that quantization (AWQ) for the architecture.[^7][^14]
- What quantization *does* change is:
    - VRAM footprint and batch sizes
    - Throughput and potentially latency
    - Sometimes edge‑case numerical stability

So **VL_QuantTrio/Qwen3‑VL‑30B‑A3B will not unlock any new API features beyond what Qwen/Qwen3‑VL‑30B‑A3B already has, but it may make the model fit your GPUs more comfortably (or not, depending on your constraints and config).**[^7][^14]

***

## Qwen2‑VL vs Qwen3‑VL‑30B‑A3B for your use case

Given your original goal (native video via `vllm-openai`), the delta looks roughly like this:


| Aspect | Qwen2‑VL via vLLM | Qwen3‑VL‑30B‑A3B via vLLM |
| :-- | :-- | :-- |
| Native video on `/chat/completions` | Not supported; Qwen docs say `api_server` doesn’t handle video yet. [^8] | Supported via `video_url` in OpenAI‑style requests. [^2][^9][^3] |
| Recommended video path | Python `LLM` + `multi_modal_data["video"]` + `qwen-vl-utils`. [^15][^8] | OpenAI‑compatible `video_url` + optional `mm_processor_kwargs` + Qwen3‑VL vLLM recipe. [^2][^9][^3] |
| Temporal embeddings | M‑RoPE for image+video (3D positions). [^16][^17] | Interleaved‑MRoPE with DeepStack for upgraded video temporal reasoning. [^1][^4][^5] |
| Official vLLM recipe with video flags | No OpenAI video recipe; only Python examples. [^8] | Yes, recipe + CLI flags (e.g. `--limit-mm-per-prompt '{\"image\":3, \"video\":5}'`, `--media-io-kwargs` for frame recovery). [^6][^3][^7] |
| Client‑side vs server‑side frame logic | Client‑side slicing recommended if using OpenAI path (images only). [^8] | Both paths discussed: direct `video_url` and advanced client‑side preprocessing to override vLLM’s frame recovery (issue \#1932). [^18][^2][^3] |
| Quantized variants (AWQ/FP8) | Available but largely Python‑centric for video. | QuantTrio AWQ and FP8 variants used with vLLM; tuning of `--limit-mm-per-prompt.video`, `--max-model-len`, etc. is important. [^14][^6][^7] |


***

## Practical guidance for your system

Given all of the above:

- **If you’re willing to move from Qwen2‑VL → Qwen3‑VL‑30B‑A3B**, you can reasonably design around **native video via `vllm-openai`** using `video_url` in the Chat Completions JSON, without having to own the lower‑level `multi_modal_data["video"]` plumbing yourself.[^2][^9][^3]
- **VL_QuantTrio’s AWQ model** is a *deployment choice*, not a feature enabler. Choose it if you need 4‑bit/low‑precision to hit your VRAM/batch targets, but validate first on the official `Qwen/Qwen3-VL-30B-A3B-Instruct` so you’re debugging fewer variables.[^13][^14][^7]
- You should still expect to:
    - Tune `--limit-mm-per-prompt.video`, `--max-model-len`, and `--gpu-memory-utilization` per your hardware.[^19][^6][^7]
    - Potentially accept that `mm_processor_kwargs` knobs (e.g. fps) may not yet be perfectly honored, depending on your vLLM/Qwen3‑VL versions; track issues like Qwen3‑VL \#1517.[^12]

So, **yes: moving to Qwen3‑VL‑30B‑A3B (official or QuantTrio) is the first point where your desired “native video via OpenAI‑compatible vLLM server” becomes aligned with what the ecosystem actually supports.**
<span style="display:none">[^20][^21][^22][^23][^24][^25][^26][^27][^28][^29][^30][^31][^32]</span>

<div align="center">⁂</div>

[^1]: https://openlm.ai/qwen3-vl/

[^2]: https://docs.vllm.ai/en/stable/features/multimodal_inputs/

[^3]: https://docs.vllm.com.cn/en/latest/features/multimodal_inputs/

[^4]: https://immers.cloud/ai/Qwen/qwen3-vl-30b-a3b-thinking/

[^5]: https://skywork.ai/blog/models/qwen-qwen3-vl-30b-a3b-instruct-free-chat-online-2/

[^6]: https://discuss.vllm.ai/t/weird-benchmarking-results-regardin-qwenvl-30b-8b-4b-solved-moe-xd/1757

[^7]: https://huggingface.co/Qwen/Qwen3-VL-30B-A3B-Instruct-FP8/discussions/4

[^8]: https://openlm.ai/qwen2-vl/

[^9]: https://docs.sglang.ai/basic_usage/qwen3_vl.html

[^10]: https://huggingface.co/docs/transformers/main/model_doc/qwen3_vl

[^11]: https://huggingface.co/docs/transformers/en/model_doc/qwen3_vl

[^12]: https://github.com/QwenLM/Qwen3-VL/issues/1517

[^13]: https://huggingface.co/QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ

[^14]: https://huggingface.co/QuantTrio/Qwen3-VL-30B-A3B-Instruct-AWQ/discussions/1

[^15]: https://discuss.vllm.ai/t/qwen-2-5-vl-for-videos/1460

[^16]: https://arxiv.org/html/2409.12191v1

[^17]: https://qwenlm.github.io/blog/qwen2-vl/

[^18]: https://github.com/QwenLM/Qwen3-VL/issues/1932

[^19]: https://blog.csdn.net/qq_39780701/article/details/155498906

[^20]: https://discuss.vllm.ai/t/does-vllm-inference-work-with-qwen3-vl-30b/2053

[^21]: https://apxml.com/models/qwen3-30b-a3b

[^22]: https://www.reddit.com/r/LocalLLaMA/comments/1mjggjx/trying_to_run_qwen330ba3bfp8_coder_in_vllm_and_i/

[^23]: https://github.com/pydantic/pydantic-ai/issues/3306

[^24]: https://www.siliconflow.com/models/qwen3-30b-a3b

[^25]: https://www.reddit.com/r/LocalLLaMA/comments/1nyd512/vllm_qwen3vl30ba3b_is_so_fast/

[^26]: https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen3-VL.html

[^27]: https://huggingface.co/Qwen/Qwen3-VL-30B-A3B-Instruct

[^28]: https://www.reddit.com/r/LocalLLaMA/comments/1nzg48q/qwenqwen3vl30ba3binstructfp8_on_dual_3090/

[^29]: https://modelscope.csdn.net/68f6f13b8867235e1394ef16.html

[^30]: https://github.com/QwenLM/Qwen3-VL/issues/1617

[^31]: https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-Nano-12B-v2-VL.html

[^32]: https://ollama.com/library/qwen3-vl:30b-a3b-instruct

