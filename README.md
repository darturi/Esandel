# Esandel

Esandel is an LLM orchestration project for Q&A. A smaller model drafts an answer, a judge reviews it, and a separate model revises or rewrites it when needed.

## Quickstart

### 1. Install Esandel

Install [Git](https://git-scm.com/install/) and [Python 3.11 or newer](https://www.python.org/downloads/) with `venv` and `pip` support. You'll need internet access to clone the repo and download its Python dependencies. In Bash or Zsh on macOS or Linux, check your tools and install Esandel.

```sh
git --version
python3 --version
git clone https://github.com/darturi/Esandel.git
cd Esandel
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

In a new terminal, return to the `Esandel` directory and run `source .venv/bin/activate` again.

### 2. Verify the installation

Run the CLI with its default stub models. This runs locally without API keys.

```sh
esandel "What is 2 + 2?"
```

You should see this placeholder answer.

```text
Stub draft for 'What is 2 + 2?'.
```

Add `--json` to see the original query, draft, verdict, and final answer. The stub judge defaults to `accept`. Use `--stub-decision tweak` or `--stub-decision regenerate` to exercise the other paths. Run the graph and CLI tests with `python -m unittest discover -s tests -v`.

### 3. Set up live mode

- Create a key in the [DeepInfra dashboard](https://deepinfra.com/dash/keys) for `DEEPINFRA_API_KEY`. The default live draft uses Qwen3.8-27B.
- Create a key on the [OpenAI Platform](https://platform.openai.com/api-keys) for `OPENAI_API_KEY`. Use an API project with access to GPT-6.2 Sol for judging and revisions.

With the virtual environment active, run the following in Bash or Zsh. Paste each key at its prompt and press Enter. The prompts hide the values, and the exported keys are available in the current terminal session.

```sh
DEEPINFRA_API_KEY="$(python -c 'from getpass import getpass; print(getpass("DeepInfra API key: "))')"
OPENAI_API_KEY="$(python -c 'from getpass import getpass; print(getpass("OpenAI API key: "))')"
export DEEPINFRA_API_KEY OPENAI_API_KEY
```

Run the live draft, judge, and any revision selected by the judge.

```sh
esandel --live-draft --live-judge --json "What is 2 + 2?"
```

Check the JSON for the model's draft, the judge's verdict, and the final answer. To try one provider at a time, use `--live-draft` for a live draft with the stub judge or `--live-judge` for a live judge with the stub draft.

#### Load keys from macOS Keychain

With both keys saved in macOS Keychain, load them only for the command. The example uses items named `EsandelOpenAI` and `esandel-deepinfra`.

```sh
OPENAI_API_KEY="$(security find-generic-password -s EsandelOpenAI -w)" \
DEEPINFRA_API_KEY="$(security find-generic-password -s esandel-deepinfra -a "$USER" -w)" \
  esandel --live-draft --live-judge --json "What is 2 + 2?"
```

## Desktop prototype

With Esandel installed in `.venv` as shown above and Node.js 22.12 or newer, run these commands from the repository root.

```sh
npm --prefix desktop ci
npm --prefix desktop start
```

The desktop app uses your live draft endpoint and GPT‑6.2 Sol for review. Launch it from the terminal where you configured the provider credentials and endpoint settings. The question pane shows any missing configuration before you run.

Enter a question and select **Run question**. The **Answer** pane is beside **Run trace**. **Judge input** highlights when the draft is sent. Select it to inspect the question and draft or copy the exact JSON. On narrow windows, the trace opens during the run and the answer preview appears when the run finishes. Select **Read answer** for the full response.

Open **Run settings → Draft model** to switch between Qwen3.8-27B and Gemma 3 4B on DeepInfra. Use Gemma 3 4B with a challenging problem to exercise the judge’s revision paths. With a custom draft endpoint, **Draft model ID** lets you enter a model served by that endpoint.

On macOS, if you saved the keys in Keychain using the item names above, launch the desktop app with them directly.

```sh
OPENAI_API_KEY="$(security find-generic-password -s EsandelOpenAI -w)" \
DEEPINFRA_API_KEY="$(security find-generic-password -s esandel-deepinfra -a "$USER" -w)" \
  npm --prefix desktop start
```

The desktop app uses `.venv` when present. Set `ESANDEL_PYTHON` to the path of a different Python executable with Esandel installed. To inspect the same event stream from the terminal, run `esandel --events "What is 2 + 2?"`. With `--events` and no query argument, Esandel reads the question from standard input.

## How a query is answered

1. A smaller open-weight model receives the query and drafts an answer in one call with built-in reasoning where supported. The CLI's live draft defaults to Qwen3.8-27B on DeepInfra.
2. GPT-6.2 Sol judges the draft against the original query. It checks that factual claims are correct and that subjective answers are relevant, reasonable, and respect the caller’s stated preferences. The CLI enables this with `--live-judge`.
3. The judge accepts or rejects the draft. On rejection, it chooses how to proceed.

   - **Accept.** Return the draft as-is.
   - **Tweak.** For a targeted fix, send the original query, draft, and judge’s guidance to a separate GPT-6.2 Sol call.
   - **Regenerate.** When the core answer needs to be redone, send only the original query to a fresh GPT-6.2 Sol call.

   A tweaked or regenerated answer goes straight to the caller.

## Live draft options

The default output budget is 16,384 tokens. Use `--draft-max-tokens` to change it. For reasoning models this budget also covers thinking tokens. Esandel uses the answer text from the chat completion and reports when the output limit cuts it off.

### Switch the draft endpoint to Torch

Run an [OpenAI-compatible vLLM server on Torch](https://services.rt.nyu.edu/docs/hpc/ml_ai_hpc/LLM%20inference/vLLM/) with `--reasoning-parser qwen3` so vLLM returns Qwen's answer and reasoning in separate fields. Point `ESANDEL_DRAFT_BASE_URL` at the reachable `/v1` URL, for example through a tunnel to the server in your GPU job.

```sh
export ESANDEL_DRAFT_BASE_URL=http://127.0.0.1:8000/v1
esandel --live-draft --json "What is 2 + 2?"
```

Set `ESANDEL_DRAFT_MODEL` if your server advertises a different model ID, and set `ESANDEL_DRAFT_API_KEY` if your endpoint requires bearer authentication.

## Planned IMO evaluation

Run each smaller model on the same International Mathematical Olympiad problems. Save the original proofs and judge decisions before any revision. Measure the **judge rejection rate** as `(tweak + regenerate) / total drafts judged`. Have a math reviewer audit a sample of verdicts, including accepted proofs, to check whether the judge identified substantive proof errors.
