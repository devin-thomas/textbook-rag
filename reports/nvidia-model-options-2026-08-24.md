# NVIDIA Hosted Model Options for Textbook Desk

Date: 2026-08-24
Scope: NVIDIA-hosted generation models only; no application code changed.

## Bottom line

Keep `nvidia/nemotron-3-super-120b-a12b` as the correctness baseline. A two-tier NVIDIA experiment is justified for latency: test `nvidia/nemotron-3.5-lightning-30b-a3b` as the default for short, straightforward questions and keep Super for multi-source, code-heavy, comparative, or otherwise difficult questions. Do not add a routing mix based on context length alone: Textbook Desk currently sends at most eight retrieved chunks, far below the 1M-token capability of either model (`SPEC.md`; `src/textbook_rag/providers.py`).

The catalog does not publish reliable per-model hosted latency, throughput, token pricing, or an SLA. The speed and cost conclusions below are therefore estimates to validate with the application's own benchmark, not guarantees.

## Current availability

An authenticated `GET https://integrate.api.nvidia.com/v1/models` probe on 2026-08-24 returned Super, Nano, Lightning, Ultra, Llama 3.3, GPT-OSS 120B, and DeepSeek V4 Flash. NVIDIA's model pages also currently mark these models as having a Free Endpoint, while the API Catalog describes hosted endpoints as preview/prototyping access. Availability and quotas can change, so the live `/v1/models` response should be treated as the final entitlement check. ([NVIDIA LLM API reference](https://docs.api.nvidia.com/nim/reference/llm-apis), [NVIDIA hosted API guidance](https://docs.api.nvidia.com/nim/docs/run-anywhere))

## Comparison

| Model | Official capabilities relevant here | Textbook RAG fit | Latency/availability judgment |
| --- | --- | --- | --- |
| `nvidia/nemotron-3-super-120b-a12b` | 120B total / 12B active; up to 1M context; explicitly lists RAG, long-context reasoning, tool use, and configurable reasoning; trained on structured-output and long-range retrieval data. ([model card](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/modelcard), [hosted page](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b?nim=hosted&section=deploy)) | Best current quality-first baseline. Its 1M context is more than the current application needs, but its RAG and multi-document training are directly relevant. | Free Endpoint currently available. Likely more expensive/slower than the smaller tiers in capacity terms, but NVIDIA publishes no hosted latency or price comparison. |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | 30B total / 3B active; up to 1M context; NVIDIA describes it as its fastest 30B A3B MoE and lists RAG, structured outputs, long-range retrieval, and multi-document aggregation in the model card. It is version `1.0-preview`, released August 11, 2026. ([model card](https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b/modelcard), [hosted page](https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b/build)) | Best candidate for a fast route, provided it matches Super on groundedness, abstention, citations, and JSON validity. | Free Endpoint currently available. The smaller active count and NVIDIA's Lightning/MTP design suggest a latency advantage, but the hosted endpoint must be measured; preview status increases change risk. |
| `nvidia/nemotron-3-nano-30b-a3b` | 30B total / 3.5B active in the model card; the hosted page lists 262K context; intended for RAG, reasoning, tool calling, and structured outputs. ([model card](https://build.nvidia.com/nvidia/nemotron-3-nano-30b-a3b/modelcard), [hosted page](https://build.nvidia.com/nvidia/nemotron-3-nano-30b-a3b/deploy)) | Viable smaller Nemotron baseline, but Lightning is the more relevant first speed experiment because it is newer and explicitly optimized for fast generation. | Free Endpoint currently available. Treat as a fallback experiment, not a third production route, unless its measured quality/latency profile is clearly better than Lightning. |
| `meta/llama-3.3-70b-instruct` | 70B text model; 128K in the model card and 131K on the hosted page; instruction following, reasoning, math, code generation, and function calling. ([model card](https://build.nvidia.com/meta/llama-3_3-70b-instruct/modelcard), [hosted page](https://build.nvidia.com/meta/llama-3_3-70b-instruct/deploy)) | Useful conventional instruct baseline and more than enough context for the current eight-chunk prompt. NVIDIA documents function calling, but that is not the same as guaranteed answer-schema JSON. | Free Endpoint currently available and widely used. It may be a stable comparison point, but there is no NVIDIA evidence that it is more grounded for textbook QA than Super or Lightning. |
| `openai/gpt-oss-120b` | 117B text-only MoE reasoning model; 131K context; hosted example exposes a separate `reasoning_content` field. ([hosted page](https://build.nvidia.com/openai/gpt-oss-120b)) | Plausible quality comparison for difficult questions, but not a clearly better fit for this small, retrieved context. Its reasoning output needs model-specific response checks. | Free Endpoint currently available. No published hosted latency or price advantage; keep it out of the first routing design. |
| `deepseek-ai/deepseek-v4-flash-0731` | 284B total / 13B active; 1M context; long-context, reasoning, chat, and agentic workloads. ([hosted page](https://build.nvidia.com/deepseek-ai/deepseek-v4-flash-0731)) | Interesting future long-context experiment, not necessary for the current page-aware retrieval design. | Free Endpoint currently available, but the page was modified only days before this research and the model is not downloadable. Higher catalog/availability uncertainty. |

Nemotron 3 Ultra is also present in the live model list and is aimed at frontier reasoning and high-stakes RAG, but its 550B total / 55B active footprint makes it a poor first choice for short textbook answers. ([model card](https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b/modelcard), [hosted page](https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b/build))

## Grounding and JSON reliability

Model selection alone will not solve the recent invalid-JSON failure. The current NVIDIA request in `src/textbook_rag/providers.py` sends a plain prompt, `temperature: 0.1`, and `max_tokens: 900`; it does not send a JSON schema or `response_format`. The server then parses and validates the returned object and may fall back in `Auto` mode.

NVIDIA's NIM documentation recommends schema-constrained `guided_json` over a generic `response_format` JSON object for structured generation, but that documentation describes NIM runtime behavior and does not guarantee that every hosted API Catalog model accepts every structured-output option. ([NVIDIA structured generation](https://docs.nvidia.com/nim/large-language-models/latest/structured-generation.html), [NVIDIA NIM API reference](https://docs.nvidia.com/nim/large-language-models/latest/api-reference.html))

Super and Lightning are both explicitly trained with structured-output and tool-calling data, which is a positive signal, not a contract. Their NVIDIA examples also use `temperature=1.0`, `top_p=0.95`, and thinking/reasoning settings, so the current low-temperature, 900-token application configuration is not an apples-to-apples comparison with the reference setup. Test a deliberate no-thinking or bounded-reasoning configuration before concluding that another model is more reliable.

## Recommended decision

1. Keep Super as the single NVIDIA model until a generation benchmark says otherwise.
2. Benchmark Lightning first as a second tier. Route only after it meets Super's grounded-answer, citation, abstention, and valid-JSON rates on the existing 18-case evaluation plus repeated latency/error measurements.
3. If it passes, use Lightning for short/simple questions and Super for multi-source, code, comparison, low-confidence, or Lightning-failure cases. Keep Ollama fallback semantics separate.
4. Do not add Nano, Llama, GPT-OSS, DeepSeek, or Ultra to the production router yet. Use them as comparison arms only if Lightning versus Super leaves an unresolved quality/latency tradeoff.

The missing evidence is application-specific: NVIDIA publishes general, long-context, agentic, and model-card benchmarks, but not this textbook corpus's citation faithfulness, abstention quality, JSON validity, or hosted p50/p95 latency. Those measurements should decide whether the mix is worth the added routing complexity.
