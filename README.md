# Thesis code: chemical data extraction under prompt ablation

Code for the BSc AI thesis on how reducing prompt information density affects
the accuracy of chemical solubility-data extraction, tested on three LLMs
(DeepSeek V4 Pro, Gemma 4 31B, Qwen3.5-9B).

## Files

| Path | What it is |
|------|------------|
| `run.py` | The runner. Reads a config file, calls the model for every paper and seed, scores each answer, and writes the output plus a summary. Start here. |
| `matcher.py` | The scorer. Parses the model's JSON answer and flattens it into rows (our code), then hands the rows to the published BigMixSolDB matcher to count exact and partial matches and compute row-level F1 (the main metric) plus the extra metrics. |
| `third_party/bigmixsoldb/` | The published BigMixSolDB matcher (Voinea et al., 2026), vendored unchanged except for one marked additive pressure extension. It does the actual row matching. See `third_party/README.md` and `third_party/LICENSE`. |
| `requirements.txt` | The Python packages needed. |
| `prompts/` | The prompts. `expert_canonical.md` is the full baseline prompt. The `no_*.md` files each remove one part of it (the ablation). The `cumulative_*.md` files remove parts one after another. `minimum_baseline.md` is the smallest prompt, and `experiment_config_schema.json` shows the config format. |
| `configs/` | One config file per run. Each result in the thesis comes from one of these. `phase2/` removes one part at a time. `phase3/` removes parts cumulatively. `phase4/` is the chain-of-thought (thinking-on) subsample, DeepSeek V4 Pro only (full prompt and the no_D1 ablation, 8 papers). |

## Running it

Needs Python 3.11+ and the packages in `requirements.txt`
(`pip install -r requirements.txt`). The models are called through OpenRouter,
so set your key first:

```bash
export OPENROUTER_API_KEY=...        # Windows PowerShell: $env:OPENROUTER_API_KEY="..."
python run.py configs/phase2/phase2_deepseek-v4-pro_full.json
```

A run reads the paper text, calls the model, scores the answer against the
correct answers, and writes the results to `out/<experiment_id>/`.

## Not included

The input papers and the correct answer key are not part of this folder, so the
code shows exactly how the experiment was done but needs that data supplied to
run from start to finish.

## License

Copyright (C) 2026 Casper Pijl.

This project's own code (`run.py`, `matcher.py`, the configs, and the prompts) is
released under the GNU Affero General Public License v3.0; see `LICENSE`. It
builds on the published BigMixSolDB matcher in `third_party/bigmixsoldb/`, which
is also AGPL v3 (see `third_party/README.md` and `third_party/LICENSE`).
