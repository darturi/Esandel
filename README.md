# Esandel

Esandel is an LLM orchestration project for Q&A. A smaller model drafts an answer, a judge reviews it, and a separate model revises or rewrites it when needed.

## How a query is answered

1. A smaller open-weight model receives the query and drafts an answer in one call with built-in reasoning where supported. The CLI's live draft defaults to Qwen3.8-27B on DeepInfra.
2. GPT-6.2 Sol judges the draft against the original query. It checks that factual claims are correct and that subjective answers are relevant, reasonable, and respect the caller’s stated preferences. The CLI enables this with `--live-judge`.
3. The judge accepts or rejects the draft. On rejection, it chooses how to proceed.

   - **Accept.** Return the draft as-is.
   - **Tweak.** For a targeted fix, send the original query, draft, and judge’s guidance to a separate GPT-6.2 Sol call.
   - **Regenerate.** When the core answer needs to be redone, send only the original query to a fresh GPT-6.2 Sol call.

   A tweaked or regenerated answer goes straight to the caller.

## Run the CLI with stub models

Install with Python 3.11 or newer.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

The stub judge defaults to `accept`. Select a verdict to exercise another path. The CLI prints the final answer by default. Add `--json` to see the original query, draft, verdict, and final answer together. The stub models run locally without API keys.

```sh
esandel --stub-decision accept --json "What is 2 + 2?"
esandel --stub-decision tweak --json "What is 2 + 2?"
esandel --stub-decision regenerate --json "What is 2 + 2?"
```

Run the graph and CLI tests with `python -m unittest discover -s tests -v`.

## Run a live draft

Set `DEEPINFRA_API_KEY` in your environment and add `--live-draft` to use Qwen3.8-27B. Without `--live-judge`, the stub judge defaults to `accept`. Add `--json` to inspect the original draft and verdict.

```sh
esandel --live-draft --json "What is 2 + 2?"
```

The default output budget is 16,384 tokens. Use `--draft-max-tokens` to change it. For reasoning models this budget also covers thinking tokens. Esandel uses the answer text from the chat completion and reports when the output limit cuts it off.

### Switch the draft endpoint to Torch

Run an [OpenAI-compatible vLLM server on Torch](https://services.rt.nyu.edu/docs/hpc/ml_ai_hpc/LLM%20inference/vLLM/) with `--reasoning-parser qwen3` so vLLM returns Qwen's answer and reasoning in separate fields. Point `ESANDEL_DRAFT_BASE_URL` at the reachable `/v1` URL, for example through a tunnel to the server in your GPU job.

```sh
export ESANDEL_DRAFT_BASE_URL=http://127.0.0.1:8000/v1
esandel --live-draft --json "What is 2 + 2?"
```

Set `ESANDEL_DRAFT_MODEL` if your server advertises a different model ID, and set `ESANDEL_DRAFT_API_KEY` if your endpoint requires bearer authentication.

## Run the live judge and revision steps

Set `OPENAI_API_KEY` in your environment and add `--live-judge` to have GPT-6.2 Sol evaluate the draft and handle any tweak or regeneration. Combine it with `--live-draft` to start with a real Qwen draft. `--live-judge` by itself starts with the stub draft. Use `--json` to inspect the original draft, verdict, and final answer.

With both keys saved in macOS Keychain, load them only for the command. The example uses items named `EsandelOpenAI` and `esandel-deepinfra`.

```sh
OPENAI_API_KEY="$(security find-generic-password -s EsandelOpenAI -w)" \
DEEPINFRA_API_KEY="$(security find-generic-password -s esandel-deepinfra -a "$USER" -w)" \
  esandel --live-draft --live-judge --json "What is 2 + 2?"
```

## Planned IMO evaluation

Run each smaller model on the same International Mathematical Olympiad problems. Save the original proofs and judge decisions before any revision. Measure the **judge rejection rate** as `(tweak + regenerate) / total drafts judged`. Have a math reviewer audit a sample of verdicts, including accepted proofs, to check whether the judge identified substantive proof errors.
