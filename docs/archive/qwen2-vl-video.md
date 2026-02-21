# Native Video Support for Qwen2-VL in vLLM (vllm-openai)

vLLM’s OpenAI-compatible server does define a native `video_url` content type, but Qwen2‑VL’s own docs explicitly state that this OpenAI entrypoint does **not** support video for Qwen2‑VL yet; native video for Qwen2‑VL is currently only wired through the Python `LLM` API using `multi_modal_data["video"]` (via `qwen-vl-utils`) rather than `/chat/completions`.[web:7][web:14] In other words, you can use `video_url` today with models like LLaVA‑OneVision, but you cannot reliably trigger Qwen2‑VL’s internal video/M‑RoPE path via `vllm-openai` as of the referenced documentation and issues.[web:14][web:10]

---

## Current vLLM video state

- The multimodal docs for vLLM 0.7.1 show a `video_url` message type for the OpenAI-compatible `/chat/completions` API, demonstrated with `llava-hf/llava-onevision-qwen2-0.5b-ov-hf`.[web:14]  
- The Qwen2‑VL integration docs explicitly note: “Now `vllm.entrypoints.openai.api_server` does not support video input yet. We are actively developing on it.”, even though Qwen2‑VL supports long videos and M‑RoPE at the model level.[web:7][web:9]  
- A GitHub issue for `Qwen2-VL-2B-Instruct`/`Qwen2.5‑VL-7B-Instruct` shows attempts to pass `video_url` to `/chat/completions` failing and the issue being closed as “not planned”, which aligns with the Qwen docs.[web:10]  

---

## 1. API schema: what the server understands

### Supported content types

For the OpenAI-compatible Chat Completions API, vLLM supports multimodal content entries of the form:[web:14]  

- Images:  
  `{"type": "image_url", "image_url": {"url": "<image-url-or-data-uri>"}}`  
- Video (for models that support it, e.g. LLaVA‑OneVision):  
  `{"type": "video_url", "video_url": {"url": "<video-url-or-data-uri>"}}`[web:14][web:2]  
- Audio:  
  `{"type": "input_audio", ...}` or `{"type": "audio_url", "audio_url": {"url": "<audio-url>"}}`.[web:14]  

The key point: `{"type": "video_url", "video_url": {"url": ...}}` is the **only** documented video content type in `messages[n].content`; bare `{"type": "video"}` is **not** part of the OpenAI schema and is only used in Qwen’s own preprocessing utilities (see below).[web:1][web:14]  

### Example JSON payload (generic video model, not Qwen2‑VL)

For a model that supports video via `video_url` (e.g. LLaVA‑OneVision), the payload looks like:[web:14]  

```json
{
  "model": "llava-hf/llava-onevision-qwen2-0.5b-ov-hf",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "What's in this video?"},
        {
          "type": "video_url",
          "video_url": {
            "url": "http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerFun.mp4"
          }
        }
      ]
    }
  ],
  "max_completion_tokens": 64
}
```

vLLM also allows base64‑encoded video by passing a `data:video/mp4;base64,...` URL in the same `video_url.url` field, as shown in LiteLLM’s VLLM integration docs.[web:2]  

### Qwen2‑VL via vllm‑openai

- The Qwen2‑VL toolkit and integration docs only show **offline** usage with `LLM(...)` and `multi_modal_data` or Qwen’s own `qwen-vl-utils`, not `video_url` messages to `/chat/completions`.[web:1][web:7]  
- The same docs warn that the OpenAI-compatible `api_server` does not yet support video input for Qwen2‑VL.[web:7]  
- GitHub issues where users attempt `{"type":"video_url"}` with Qwen2‑VL through `/chat/completions` show failures and are not marked as supported.[web:5][web:10]  

**Conclusion for 1:**  
There *is* a native `video_url` JSON schema in `messages[*].content` for vLLM’s OpenAI-compatible server, but as of the referenced docs and issues there is **no documented, working schema that triggers Qwen2‑VL’s native video path via `/chat/completions`**. For Qwen2‑VL you must go through the Python `LLM` API + `multi_modal_data["video"]` to get native video handling.[web:7][web:14]  

---

## 2. Internal mechanics: slicing vs. real video encoding

### Qwen2‑VL’s native video design

- Qwen2‑VL processes videos as sequences of frames with Multimodal Rotary Position Embedding (M‑RoPE), decomposing positional embeddings into temporal and spatial (H, W) components to fuse 1D text, 2D image, and 3D video positions.[web:3][web:9]  
- The paper and blog describe that videos can reach over 20 minutes thanks to M‑RoPE’s improved length extrapolation; training capped tokens per video at 16k but inference can go up to 80k with stable performance.[web:3][web:7][web:9]  
- Qwen’s utilities (`qwen-vl-utils`) expose parameters like `fps`, `nframes`, `min_pixels`, and `total_pixels`, and return `video_inputs` plus `mm_processor_kwargs` (including effective fps) for vLLM.[web:1][web:7]  

When using the Python `LLM` API you typically:[web:1][web:7]  

1. Build a chat template via `AutoProcessor.apply_chat_template(...)`.  
2. Call `process_vision_info(messages, return_video_kwargs=True)` from `qwen-vl-utils` to obtain `image_inputs`, `video_inputs`, and `video_kwargs`.  
3. Pass `{"video": video_inputs}` in `multi_modal_data` and `video_kwargs` in `mm_processor_kwargs` to `LLM.generate(...)`.  

This path yields **true temporal encoding** as Qwen2‑VL sees a sequence of frames with proper 3D M‑RoPE positions, not a bag of disconnected images.[web:1][web:3][web:7]  

### vLLM’s rotary embedding / M‑RoPE support

- vLLM has explicit support for M‑RoPE in its rotary embedding layer; the docs mention Qwen2.5‑VL specifically, noting that maximum positional indices are enlarged (e.g. 4×) because they depend on input video duration.[web:15]  
- For Qwen2‑VL and Qwen2.5‑VL classes (`Qwen2_5_VLForConditionalGeneration` etc.), vLLM wires M‑RoPE so that when multi-modal inputs include videos, temporal positions are handled consistently with the original model.[web:12][web:15]  

### What happens with `video_url` in vLLM‑OpenAI

- For models like LLaVA‑OneVision, vLLM’s server downloads the video from `video_url.url`, decodes it, samples frames, and passes a list/array of frames into the model’s video path (for that model), not just as eight images glued into the prompt.[web:14]  
- However, Qwen2‑VL’s own documentation states that the `api_server` does not yet support video input, implying that the OpenAI server path does **not** call Qwen’s `qwen-vl-utils` pipeline or construct `multi_modal_data["video"]` for Qwen2‑VL.[web:7]  

**Conclusion for 2:**  
- With Qwen2‑VL via `LLM(..., multi_modal_data={"video": ...})`, you get proper M‑RoPE‑based temporal encoding of videos.  
- With Qwen2‑VL via `/chat/completions`, there is currently **no documented path** that converts `video_url` into Qwen’s native video representation; attempts in the wild fail, and the vendor docs say it is not yet supported.[web:7][web:10]  

---

## 3. Infrastructure & configuration requirements

### Video decoding libraries

For Qwen2‑VL’s official ecosystem and vLLM integration, the recommended stack is:[web:7]  

- `qwen-vl-utils[decord]` – this pulls in `decord` for efficient video loading on Linux.  
- If `decord` cannot be installed (e.g. some non‑Linux environments), `qwen-vl-utils` falls back to `torchvision` for video processing.[web:7]  
- Environment variables:  
  - `FORCE_QWENVL_VIDEO_READER=torchvision` or `FORCE_QWENVL_VIDEO_READER=decord` to force a specific backend.[web:7]  
- Underneath, decord/torchvision will rely on system ffmpeg or codec libraries, so your container should include ffmpeg compatible with the chosen decoder.  

For vLLM’s OpenAI server video support in general (e.g. LLaVA‑OneVision):[web:14]  

- vLLM ships utilities to fetch and decode media; for videos it uses a 30‑second HTTP fetch timeout (`VLLM_VIDEO_FETCH_TIMEOUT`).  
- Images and audio have analogous timeouts via `VLLM_IMAGE_FETCH_TIMEOUT` and `VLLM_AUDIO_FETCH_TIMEOUT`.[web:14]  

### vLLM startup flags and limits

Key flags for multimodal serving:[web:14]  

- `--limit-mm-per-prompt`  
  - Controls how many items of a modality are accepted per prompt, e.g. `--limit-mm-per-prompt image=4` for Qwen2‑VL offline multi-frame video-as-images, or `{"video": 1}` in Python API usage.[web:1][web:14]  
- `--max-model-len`  
  - Sets the maximum token context; for video models this must be set high enough to cover text + visual tokens. LLaVA‑OneVision example uses `--max-model-len 8192`, and Phi‑3.5‑Vision uses `4096` in docs.[web:14]  
- `--allowed-local-media-path`  
  - Controls which local paths can be referenced in `image_url.url` or `video_url.url` so you can serve from local files instead of HTTP URLs.[web:14]  

For **Qwen2‑VL native video** you additionally need:[web:1][web:7]  

- Qwen’s processor and utilities: `transformers` `AutoProcessor` and `qwen-vl-utils`.  
- Python‑side logic to call `process_vision_info(...)` and build `multi_modal_data` and `mm_processor_kwargs`.  

No special “enable video” flag exists beyond these; the main distinction is whether you are using the Python `LLM` API or the OpenAI `api_server`, and only the former is currently officially wired for Qwen2‑VL video.[web:7]  

---

## 4. Performance, VRAM, and context implications

### Tokenization and context window

- Qwen2‑VL uses Naive Dynamic Resolution (NDR): each frame is resized such that total pixels fall within `[min_pixels, max_pixels]`, and then patched into a variable number of visual tokens depending on effective resolution.[web:7][web:9]  
- A typical preprocessor config for Qwen2‑VL shows `min_pixels` ≈ 50k and `max_pixels` ≈ 1M, which effectively bounds the tokens per frame and per image.[web:7]  
- M‑RoPE is designed to allow length extrapolation well beyond training; the Qwen2‑VL paper shows that although training limited each video to 16k tokens, inference with up to 80k “video length” tokens remains robust.[web:3][web:9]  

### 10‑second clip vs 16 static images (qualitative)

Given dynamic resolution and 1–2 FPS sampling:  

- A 10‑second clip at 1 FPS yields ~10 frames; at 2 FPS yields ~20 frames.  
- If your current “bag of 8 images” baseline uses similar resolutions, the number of **visual tokens** for 10–20 frames is on the same order as 8–16 static images when NDR is active, so VRAM and latency scale roughly linearly with total frames compared to your existing setup.[web:7][web:9]  
- The major difference is that in the native video path, those tokens carry **consistent 3D positional encodings** across time; in the bag‑of‑images path they are treated as independent images with only textual hints about ordering.[web:3][web:9]  

Practical implications:  

- For a 10‑second 1–2 FPS clip, expect something like a **1–2×** increase in visual tokens vs 8 static frames at comparable resolutions, hence similar factor increase in attention compute and VRAM, depending on exact frame resolution and NDR behavior.  
- For longer clips, you will need to either:  
  - Lower FPS (`fps` parameter in Qwen’s utilities) or cap `nframes`, or  
  - Accept more aggressive NDR down‑sampling per frame to stay within `max_model_len` and `max_pixels`, especially if you keep high‑resolution frames.[web:1][web:7][web:9]  

### Dynamic resolution for video frames

- Qwen2‑VL applies the same NDR scheme to video frames as to images, mapping higher‑resolution frames to more tokens but clamping with `min_pixels`/`max_pixels`.[web:3][web:7][web:9]  
- M‑RoPE ensures that temporal IDs increment per frame, while height/width IDs follow the same pattern as images, enabling Qwen2‑VL to treat frames at different resolutions within the same video consistently.[web:3][web:9]  

---

## 5. Implementation examples

### 5.1. vLLM‑OpenAI `video_url` example (non‑Qwen model)

This is the canonical way to send a video to vLLM’s OpenAI server for a model that actually supports `video_url` (e.g. LLaVA‑OneVision):[web:14]  

```python
from openai import OpenAI

client = OpenAI(
    api_key="EMPTY",
    base_url="http://localhost:8000/v1",
)

model = "llava-hf/llava-onevision-qwen2-0.5b-ov-hf"
video_url = "http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerFun.mp4"

resp = client.chat.completions.create(
    model=model,
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What's in this video?"},
                {
                    "type": "video_url",
                    "video_url": {"url": video_url},
                },
            ],
        }
    ],
    max_completion_tokens=64,
)

print(resp.choices[0].message.content)
```

Server side, you would launch something like:[web:14]  

```bash
vllm serve llava-hf/llava-onevision-qwen2-0.5b-ov-hf \
  --task generate \
  --max-model-len 8192
```

**Caveat:** substituting `model="Qwen/Qwen2-VL-2B-Instruct"` or `Qwen/Qwen2.5-VL-7B-Instruct` here is **not documented to work**; GitHub issues confirm errors when trying to do exactly this.[web:7][web:10]  

### 5.2. Recommended “native Qwen2‑VL video” via Python LLM API

To actually exercise Qwen2‑VL’s internal video logic and M‑RoPE today, the path that *is* documented is:[web:1][web:7]  

```python
from transformers import AutoProcessor
from vllm import LLM, SamplingParams
from qwen_vl_utils import process_vision_info

model_name = "Qwen/Qwen2-VL-7B-Instruct"

llm = LLM(
    model=model_name,
    sampling_params=SamplingParams(
        temperature=0.1,
        top_p=0.95,
        max_tokens=512,
    ),
    limit_mm_per_prompt={"video": 1},
)

messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "Describe the video content in detail."},
            {
                "type": "video",
                "video": "/path/to/local/video.mp4",
                "nframes": 32,
            },
        ],
    },
]

processor = AutoProcessor.from_pretrained(model_name)
prompt = processor.apply_chat_template(
    messages,
    tokenize=False,
    add_generation_prompt=True,
)

image_inputs, video_inputs, video_kwargs = process_vision_info(
    messages,
    return_video_kwargs=True,
)

mm_data = {}
if video_inputs is not None:
    mm_data["video"] = video_inputs

outputs = llm.generate(
    {
        "prompt": prompt,
        "multi_modal_data": mm_data,
        "mm_processor_kwargs": video_kwargs,
    }
)

print(outputs[0].outputs[0].text)
```

This gives you:  

- Proper video decoding (via decord or torchvision) and frame sampling (`nframes`, `fps`).[web:1][web:7]  
- True Qwen2‑VL NDR + M‑RoPE handling inside the model.  
- Full control over temporal resolution and visual token budget.  

You can then front this Python API with your own lightweight HTTP service if you need an OpenAI‑style façade; internally you’ll still be using `multi_modal_data["video"]` rather than `video_url`.  

---

## 6. Approaches and tradeoffs

A concise comparison of realistic options for you right now:

| Approach                               | API surface                  | Temporal modelling           | vLLM/Qwen2‑VL support status            | Pros                                                | Cons                                                                 |
|----------------------------------------|------------------------------|------------------------------|-----------------------------------------|-----------------------------------------------------|----------------------------------------------------------------------|
| Client‑side 8‑frame bag‑of‑images      | `/chat/completions` + `image_url` | Pseudo‑temporal via text only | Fully supported for Qwen2‑VL           | Simple; works today; OpenAI‑compatible              | Loses explicit time axis; no M‑RoPE video semantics                 |
| `video_url` via vllm‑openai (Qwen2‑VL) | `/chat/completions` + `video_url` | Undefined for Qwen2‑VL        | Not supported / issues closed “not planned”[web:7][web:10] | Uses neat schema; works for other models (LLaVA‑OV) | Currently unreliable/non‑functional for Qwen2‑VL                    |
| Native Qwen2‑VL video via `LLM`        | Python `LLM(..., multi_modal_data["video"])` | Full M‑RoPE video positions    | Officially supported path for Qwen2‑VL[web:1][web:7][web:15] | True temporal awareness; long videos; fine control  | Not OpenAI‑compatible; you must run your own thin HTTP wrapper      |

---

## Reasoning gains vs. your current setup

If you switch from an 8‑frame bag‑of‑images to Qwen2‑VL’s native video path (using `multi_modal_data["video"]`):  

- The model will see a **proper temporal dimension** with consistent 3D positional embeddings across frames, not a flat set of unrelated images.[web:3][web:9][web:15]  
- This is especially beneficial for actions, state changes, temporal ordering, and causal reasoning (e.g., “who picked up what when?”, “did the person fall before or after crossing the line?”), where M‑RoPE and the unified image+video processing show strong gains in Qwen’s benchmarks.[web:3][web:7][web:9]  
- For simple static‑scene questions, gains will be smaller; you mainly pay a modest VRAM/latency increase for more frames and positional structure, but get robustness on longer clips and more complex temporal tasks.[web:3][web:9][web:15]  

**Bottom line:** if you need real temporal awareness from Qwen2‑VL today, design around the **Python `LLM` + `multi_modal_data["video"]` path with `qwen-vl-utils`**, and front it with your own API; relying on `video_url` via `vllm-openai` for Qwen2‑VL is not yet viable according to the current docs and issue trackers.[web:1][web:7][web:10][web:14][web:15]
