"""Runs one experiment. It reads a config file, runs every paper and seed
through the pipeline, saves the output and scores for each paper, and adds
it all up into one summary.

A config file says which model to use, which prompt, which papers and which
seeds to run. The file experiment_config_schema.json shows the exact format.

Run it from the command line with python run.py and the path to a config file.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

from matcher import (
    VLM_DIR,
    parse_response, flatten, load_ref_csv, score_paper,
)

# on Windows, printing some special characters can crash the console, so we force utf-8
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# normal settings go straight to the API call, and the rest like top_k go in extra_body
OPENAI_STANDARD_PARAMS = {
    "temperature", "top_p", "presence_penalty", "frequency_penalty",
    "max_tokens", "n", "stop", "logprobs", "top_logprobs",
}

def build_extra_body(model_cfg):
    """Build the extra_body for OpenRouter. It holds the provider choice,
    the reasoning setting, and any other settings like top_k."""
    params = dict(model_cfg.get("params", {}))
    extra_body = {k: v for k, v in params.items() if k not in OPENAI_STANDARD_PARAMS}

    slug = model_cfg["slug"].lower()
    if slug.startswith("deepseek/"):
        # use DeepSeek's own server, it is the cheapest and listens to the reasoning setting
        extra_body["provider"] = {"order": ["deepseek"]}
    else:
        extra_body["provider"] = {"sort": "price"}

    if "reasoning" in model_cfg:
        # for the Phase 4 chain of thought runs, ask the model to send its reasoning back
        extra_body["reasoning"] = model_cfg["reasoning"]
        extra_body["include_reasoning"] = True
    elif slug.startswith("deepseek/"):
        # DeepSeek thinks by default, so we turn that off for the normal runs
        thinking_on = bool(model_cfg.get("thinking_mode", False))
        extra_body["reasoning"] = {"enabled": thinking_on, "exclude": True}

    # Gemma and Qwen take no thinking flag here. For Qwen3.5-9B the config carries
    # thinking_mode=false, but it is inert: only the deepseek branch above reads it, and
    # no OpenRouter provider could disable Qwen's reasoning at usable quality, so Qwen ran
    # reasoning-on (provider-forced; see thesis section 3.3).
    return extra_body


def make_meta(resp):
    """Keep the response id, the token usage and a timestamp so we can track cost."""
    usage = resp.usage.model_dump() if getattr(resp, "usage", None) else {}
    return {
        "id": resp.id,
        "sdk_usage": usage,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def call_llm_from_config(system_prompt, user_text, model_cfg, seed):
    """Call the model from model_cfg and give back the raw text and metadata.

    We only use OpenRouter. Normal settings are passed straight in, the rest
    go through build_extra_body. The metadata holds the response id and token
    usage so we can look up the cost later.
    """
    provider = model_cfg.get("provider", "openrouter")
    if provider != "openrouter":
        raise ValueError(f"Unsupported provider: {provider}")

    # give each call a long timeout and a few retries, short timeouts sometimes hung on stuck calls
    client = OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
        timeout=180,
        max_retries=3,
    )

    params = dict(model_cfg.get("params", {}))
    std_params = {k: v for k, v in params.items() if k in OPENAI_STANDARD_PARAMS}
    extra_body = build_extra_body(model_cfg)

    resp = client.chat.completions.create(
        model=model_cfg["slug"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        seed=seed,
        extra_body=extra_body,
        **std_params,
    )
    if not resp.choices:
        err = getattr(resp, "error", None)
        raise RuntimeError(f"OpenRouter returned no choices. error={err!r}")
    # if the model sends back nothing, make it an empty string so it counts as a fail
    msg = resp.choices[0].message
    raw = msg.content or ""
    reasoning_text = getattr(msg, "reasoning", None) or ""
    reasoning_details = getattr(msg, "reasoning_details", None) or []
    meta = make_meta(resp)
    meta["reasoning"] = reasoning_text
    meta["reasoning_details"] = reasoning_details
    return raw, meta


def read_prompt(path):
    """Return the prompt text that comes after the System prompt heading."""
    text = Path(path).read_text(encoding="utf-8")
    marker = "## System prompt"
    if marker in text:
        text = text.split(marker, 1)[1]
    return text.strip()


def failed_result(doi, llm_text, parsed, n_gt_rows, error):
    """Result dict for a paper we could not read or flatten: the scores are None."""
    return {
        "doi": doi,
        "raw": llm_text,
        "valid_strict": parsed["valid_strict"],
        "valid_recovered": parsed["valid_recovered"],
        "parsed": parsed["data"],
        "flat": None,
        "row_level": None,
        "per_field": None,
        "unmatched_row_rate": None,
        "n_llm_rows": 0,
        "n_gt_rows": n_gt_rows,
        "error": error,
    }


def score_one(llm_text, doi):
    """Read, flatten and score one model answer against the correct answers.

    Gives back a dict with the raw text, the parsed data, the flat rows and all
    the scores. If reading or flattening fails, it returns the same dict but with
    an error message and the scores set to None.
    """
    ref_rows = load_ref_csv(doi)
    parsed = parse_response(llm_text)

    if parsed["data"] is None:
        return failed_result(doi, llm_text, parsed, len(ref_rows), "non-parseable response")

    try:
        llm_flat = flatten(parsed["data"])
    except (AttributeError, TypeError, KeyError) as e:
        return failed_result(doi, llm_text, parsed, len(ref_rows),
                             f"flatten failed: {type(e).__name__}: {e}")

    scores = score_paper(llm_flat, doi)

    return {
        "doi": doi,
        "raw": llm_text,
        "valid_strict": parsed["valid_strict"],
        "valid_recovered": parsed["valid_recovered"],
        "parsed": parsed["data"],
        "flat": llm_flat,
        "row_level": scores["row_level"],
        "per_field": scores["per_field"],
        "unmatched_row_rate": scores["unmatched_row_rate"],
        "n_llm_rows": len(llm_flat),
        "n_gt_rows": len(ref_rows),
        "error": None,
    }


def extract_metrics(result, seed, model_slug):
    """Drop the big fields from a result so the saved metrics file stays small."""
    return {
        "doi": result["doi"],
        "seed": seed,
        "model": model_slug,
        "valid_strict": result["valid_strict"],
        "valid_recovered": result["valid_recovered"],
        "row_level": result["row_level"],
        "per_field": result["per_field"],
        "unmatched_row_rate": result["unmatched_row_rate"],
        "n_llm_rows": result["n_llm_rows"],
        "n_gt_rows": result["n_gt_rows"],
        "error": result.get("error"),
    }


def compute_summary(all_metrics, dois, seeds):
    """Average the scores over every paper and seed.

    Every planned paper counts. A paper with no usable output gets an F1 of 0 and
    stays in the average, because leaving it out would make the model look better
    than it is, since the failures are usually the biggest papers. The score for
    each field is only averaged over papers that were read and that have that field.
    """
    n_grid = len(dois) * len(seeds)
    if n_grid == 0:
        return {}
    n_present = len(all_metrics)
    n_missing = max(0, n_grid - n_present)

    # one pass over the papers we actually have, adding up each metric
    n_valid = 0
    urr_sum = 0.0
    rl_sum = 0.0
    for m in all_metrics:
        if m.get("valid_strict") or m.get("valid_recovered"):
            n_valid += 1
        urr = m.get("unmatched_row_rate")
        urr_sum += 1.0 if urr is None else urr
        rl = m.get("row_level")
        if rl and rl.get("f1") is not None:
            rl_sum += rl["f1"]
    # a missing or failed paper counts as unmatched-row-rate 1.0 and F1 0.0
    urr_sum += n_missing

    # average each value field's score over the papers that had matched rows for it
    field_sums = {}
    field_counts = {}
    for m in all_metrics:
        if not m.get("per_field"):
            continue
        for field, score in m["per_field"].items():
            field_sums[field] = field_sums.get(field, 0.0) + score
            field_counts[field] = field_counts.get(field, 0) + 1

    per_field = {f: field_sums[f] / field_counts[f] for f in field_sums}
    per_field_macro = (sum(per_field.values()) / len(per_field)) if per_field else 0.0

    return {
        "n_calls": n_present,
        "n_grid": n_grid,
        "n_missing": n_missing,
        "n_unique_papers": len({m["doi"] for m in all_metrics}),
        "valid_json_rate": n_valid / n_grid,
        "row_level_f1": rl_sum / n_grid,
        "unmatched_row_rate": urr_sum / n_grid,
        "per_field_f1": per_field,
        "per_field_f1_macro": per_field_macro,
    }


def run_experiment(config_path):
    """Run one experiment from a config file and give back the summary."""
    config_path = Path(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))

    experiment_id = config["experiment_id"]
    model_cfg = config["model"]
    dois = config["corpus"]["subset"]
    prompt_path = Path(config["prompt"])
    seeds = config["seeds"]

    out_dir = Path("out") / experiment_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # save a copy of the config so the run can be repeated later
    (out_dir / "config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )

    log_path = out_dir / "run.log"
    log_f = log_path.open("a", encoding="utf-8")

    def log(msg):
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        print(line)
        log_f.write(line + "\n")
        log_f.flush()

    log(f"=== Experiment {experiment_id} ===")
    log(f"Model: {model_cfg['slug']}")
    log(f"Prompt: {prompt_path}")
    log(f"Corpus: {len(dois)} papers, seeds: {seeds}")

    system_prompt = read_prompt(prompt_path)

    all_metrics = []
    total_calls = len(dois) * len(seeds)
    i = 0
    for seed in seeds:
        for doi in dois:
            i += 1
            log(f"[{i}/{total_calls}] {doi} seed={seed}")

            result_path = out_dir / f"{doi}_seed{seed}.json"
            metrics_path = out_dir / f"{doi}_seed{seed}_metrics.json"

            # if we already scored this paper before, just reuse it
            if metrics_path.exists():
                log("  already done, skipping")
                all_metrics.append(
                    json.loads(metrics_path.read_text(encoding="utf-8"))
                )
                continue

            paper_path = VLM_DIR / f"{doi}.md"
            if not paper_path.exists():
                log(f"  ERROR: missing paper {paper_path}")
                continue
            paper_md = paper_path.read_text(encoding="utf-8")

            try:
                raw, meta = call_llm_from_config(
                    system_prompt, paper_md, model_cfg, seed=seed
                )
            except Exception as e:
                log(f"  LLM call ERROR: {type(e).__name__}: {e}")
                continue

            (out_dir / f"{doi}_seed{seed}_id.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )

            result = score_one(raw, doi)
            # keep the reasoning trace if the model returned one, used for the Phase 4 runs
            if meta.get("reasoning") or meta.get("reasoning_details"):
                result["reasoning"] = meta.get("reasoning", "")
                result["reasoning_details"] = meta.get("reasoning_details", [])
            result_path.write_text(
                json.dumps(result, indent=2, default=str), encoding="utf-8"
            )

            metrics = extract_metrics(result, seed, model_cfg["slug"])
            metrics_path.write_text(
                json.dumps(metrics, indent=2), encoding="utf-8"
            )
            all_metrics.append(metrics)

            rl = metrics.get("row_level")
            rl_f1 = f"{rl['f1']:.3f}" if rl else "None"
            urr = metrics.get("unmatched_row_rate")
            urr_s = f"{urr:.3f}" if urr is not None else "None"
            log(f"  RL-F1={rl_f1} URR={urr_s} "
                f"valid_strict={metrics['valid_strict']}")

    summary = compute_summary(all_metrics, dois, seeds)
    summary["experiment_id"] = experiment_id
    summary["model"] = model_cfg["slug"]
    summary["prompt"] = str(prompt_path)
    summary["seeds"] = seeds
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    log("=== Summary ===")
    log(f"Valid-JSON rate: {summary.get('valid_json_rate', 0):.3f}")
    log(f"Row-level F1:    {summary.get('row_level_f1', 0):.3f}")
    log(f"Unmatched-row:   {summary.get('unmatched_row_rate', 0):.3f}")
    log(f"Per-field F1 (macro): {summary.get('per_field_f1_macro', 0):.3f}")
    log(f"Output: {out_dir}")
    log_f.close()
    return summary


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run.py <config.json>")
        sys.exit(1)
    run_experiment(sys.argv[1])
