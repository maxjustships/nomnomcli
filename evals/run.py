from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import threading
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = Path(__file__).with_name("corpus.json")
PROHIBITED_PLAN_KEYS = {"calories", "carbs", "fat", "kcal", "macros", "nutrition", "protein"}


def load_corpus() -> dict:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


class ReplayState:
    def __init__(self, case: dict) -> None:
        self.case = case
        self.requests: list[dict] = []
        self.lock = threading.Lock()

    def record(self, path: str, query: str) -> None:
        parameters = {
            key: values
            for key, values in parse_qs(query).items()
            if key.casefold() not in {"api_key", "token", "authorization"}
        }
        with self.lock:
            self.requests.append({"path": path, "parameters": parameters})


class ReplayServer:
    def __init__(self, case: dict) -> None:
        self.state = ReplayState(case)
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                state.record(parsed.path, parsed.query)
                providers = state.case["synthetic_providers"]
                candidates = providers["candidates"]
                responses = providers["responses"]
                if parsed.path == "/off/search":
                    self._json(
                        responses["openfoodfacts_search_status"],
                        {"products": candidates["openfoodfacts"]},
                    )
                    return
                if parsed.path == "/off/product-probe":
                    self._json(200, {"status": 1})
                    return
                if parsed.path.startswith("/off/product/"):
                    barcode = parsed.path.rsplit("/", 1)[-1]
                    record = next(
                        (
                            item
                            for item in candidates["openfoodfacts"]
                            if str(item.get("code")) == barcode
                        ),
                        None,
                    )
                    self._json(
                        200,
                        {"status": 1, "product": record}
                        if record is not None
                        else {"status": 0},
                    )
                    return
                if parsed.path == "/usda/search":
                    query = parse_qs(parsed.query).get("query", [""])[0]
                    status = responses.get("usda_search_status_by_term", {})
                    matched_status = next(
                        (
                            value
                            for term, value in status.items()
                            if term.casefold() in query.casefold()
                        ),
                        responses["usda_search_status"],
                    )
                    self._json(
                        matched_status,
                        {"foods": candidates["usda"]},
                    )
                    return
                if parsed.path.startswith("/usda/food/"):
                    source_id = parsed.path.rsplit("/", 1)[-1]
                    override = responses["refetch_overrides"].get(source_id)
                    record = override or next(
                        (
                            item
                            for item in candidates["usda"]
                            if str(item.get("fdcId")) == source_id
                        ),
                        None,
                    )
                    self._json(200 if record is not None else 404, record or {})
                    return
                self._json(404, {"error": "unknown replay path"})

            def _json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> ReplayServer:
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def render_command(template: str, values: dict[str, str]) -> list[str]:
    return [part.format(**values) for part in shlex.split(template)]


def default_actor_command() -> str:
    return f"{shlex.quote(sys.executable)} -m evals.fake_actor --prompt {{prompt}}"


def read_events(db_path: Path) -> list[dict]:
    if not db_path.exists():
        return []
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        if connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='log_entries'"
        ).fetchone()[0] == 0:
            return []
        return [
            {
                "id": int(row["id"]),
                "kind": str(row["kind"]),
                "items": json.loads(row["items_json"]),
                "totals": {
                    key: float(row[key]) for key in ("kcal", "protein", "fat", "carbs")
                },
            }
            for row in connection.execute("SELECT * FROM log_entries ORDER BY id")
        ]
    finally:
        connection.close()


def source_ref(item: dict) -> str | None:
    if item.get("selected_source_ref"):
        return str(item["selected_source_ref"])
    source_id = item.get("source_id")
    if source_id is None:
        return None
    prefix = "off" if item.get("source") == "openfoodfacts" else item.get("source")
    return f"{prefix}:{source_id}"


def plan_has_injected_nutrition(value) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).casefold() in PROHIBITED_PLAN_KEYS
            or plan_has_injected_nutrition(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(plan_has_injected_nutrition(child) for child in value)
    return False


def expected_per_100(case: dict) -> dict[str, dict[str, float]]:
    result = {}
    providers = case["synthetic_providers"]["candidates"]
    for record in providers["usda"]:
        values = {}
        mapping = {1008: "kcal", 1003: "protein", 1004: "fat", 1005: "carbs"}
        for nutrient in record.get("foodNutrients", []):
            if nutrient.get("nutrientId") in mapping:
                values[mapping[nutrient["nutrientId"]]] = float(nutrient["value"])
        result[f"usda:{record['fdcId']}"] = values
    for record in providers["openfoodfacts"]:
        nutrients = record["nutriments"]
        result[f"off:{record['code']}"] = {
            "kcal": float(nutrients["energy-kcal_100g"]),
            "protein": float(nutrients["proteins_100g"]),
            "fat": float(nutrients["fat_100g"]),
            "carbs": float(nutrients["carbohydrates_100g"]),
        }
    return result


def evaluate(
    case: dict,
    actor_runs: list[dict],
    events: list[dict],
    requests: list[dict],
) -> dict:
    hard: list[str] = []
    ux: list[str] = []
    expected_outcome = case["expected"]["outcome"]
    cli_payloads = [run.get("cli", run) for run in actor_runs]
    cli_codes = [int(run.get("cli_returncode", 0)) for run in actor_runs]
    if expected_outcome == "error":
        if not any(code != 0 for code in cli_codes):
            hard.append("expected_error_missing")
        if events:
            hard.append("atomic_no_write_failed")
    elif any(code != 0 for code in cli_codes):
        hard.append("unexpected_cli_error")

    stored_items = [item for event in events for item in event["items"]]
    expected_inputs = [item["input"] for item in case["items"]]
    represented = {str(item.get("input")) for item in stored_items}
    if any(step.get("action_after") == "remove_logged_event" for step in case["steps"]):
        represented.update(
            str(item.get("input"))
            for payload in cli_payloads
            for item in payload.get("items", [])
        )
    if expected_outcome != "error" and not set(expected_inputs) <= represented:
        hard.append("lost_input_item")

    pending = [item for item in stored_items if item.get("status") == "pending_capture"]
    resolved = [item for item in stored_items if item.get("status") == "resolved"]
    actual_outcome = (
        "error"
        if any(code != 0 for code in cli_codes)
        else "pending"
        if pending
        else "complete"
    )
    if actual_outcome != expected_outcome:
        hard.append("incorrect_complete_status")
    if len(pending) > case["expected"]["max_followups"]:
        ux.append("max_followups_exceeded")

    allowed_refs = set(case["allowed_source_refs"])
    allowed_modes = set(case["allowed_resolution_modes"])
    allowed_names = {name.casefold() for name in case["allowed_semantic_identities"]}
    forbidden_names = {name.casefold() for name in case["forbidden_identities"]}
    forbidden_tokens = {token.casefold() for token in case["forbidden_tokens"]}
    nutrition = expected_per_100(case)
    envelopes = dict(zip(expected_inputs, case["gram_envelopes"], strict=True))
    for item in resolved:
        ref = source_ref(item)
        if ref not in allowed_refs:
            hard.append(f"source_not_allowed:{ref}")
        mode = item.get("resolution_mode")
        if mode not in allowed_modes:
            hard.append(f"resolution_mode_not_allowed:{mode}")
        name = str(item.get("name", "")).casefold()
        semantic_name = name.split(" — ", 1)[0]
        if allowed_names and semantic_name not in allowed_names:
            hard.append(f"semantic_identity_not_allowed:{name}")
        if name in forbidden_names or any(
            re.search(rf"\b{re.escape(token)}\b", name) for token in forbidden_tokens
        ):
            hard.append(f"catastrophic_semantic_substitution:{name}")
        envelope = envelopes.get(str(item.get("input")))
        grams = float(item.get("grams", 0))
        if envelope is not None and not float(envelope[0]) <= grams <= float(envelope[1]):
            ux.append(f"grams_outside_envelope:{grams}")
        if not item.get("source") or not ref or not item.get("provenance"):
            hard.append("source_or_provenance_missing")
        if (
            mode in {"generic_proxy", "probable_product"} or item.get("approximate")
        ) and not item.get("assumption"):
            hard.append("approximation_assumption_missing")
        facts = nutrition.get(ref or "")
        if facts:
            for key, per_100 in facts.items():
                expected_value = round(per_100 * grams / 100 + 1e-12, 2)
                if abs(float(item[key]) - expected_value) > 0.011:
                    hard.append(f"invented_nutrition:{ref}:{key}")

    if any(plan_has_injected_nutrition(run.get("plan", {})) for run in actor_runs):
        hard.append("agent_nutrition_injection")
    search_attempts = sum(
        request["path"] in {"/off/search", "/usda/search"} for request in requests
    )
    if case["expected"]["text_search_must_be_attempted"] and search_attempts == 0:
        ux.append("text_search_not_attempted")
    if case["category"] == "branded" and pending and search_attempts == 0:
        ux.append("immediate_capture_without_search")

    return {
        "id": case["id"],
        "category": case["category"],
        "profile": case["profile"],
        "pass": not hard and not ux,
        "hard_failures": sorted(set(hard)),
        "ux_failures": sorted(set(ux)),
        "outcome": actual_outcome,
        "followups": len(pending),
        "text_search_attempts": search_attempts,
        "resolved_items": len(resolved),
        "event_count": len(events),
    }


def run_actor(
    *,
    actor_command: str,
    prompt: str,
    env: dict[str, str],
    episode_dir: Path,
    suffix: str,
) -> dict:
    actor_result = episode_dir / f"actor-{suffix}.json"
    actor_env = {
        **env,
        "NOMNOM_ACTOR_TRACE_PATH": str(actor_result),
    }
    command = render_command(
        actor_command,
        {
            "prompt": prompt,
            "sandbox": str(episode_dir),
            "db_path": env["NOMNOM_DB_PATH"],
            "actor_result": str(actor_result),
            "max_turns": "6",
        },
    )
    completed = subprocess.run(
        command,
        cwd=episode_dir,
        env=actor_env,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    def persist(payload: dict) -> dict:
        actor_result.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return payload

    if completed.returncode != 0:
        return persist({
            "cli_returncode": completed.returncode,
            "actor_process_error": "actor command returned a nonzero status",
        })
    candidates = [completed.stdout.strip()]
    candidates.extend(
        line.strip().removeprefix("```json").removesuffix("```").strip()
        for line in reversed(completed.stdout.splitlines())
        if line.strip()
    )
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return persist(payload)
    return persist({
        "cli_returncode": 70,
        "actor_process_error": "actor stdout did not contain one parseable JSON object",
    })


def run_episode(
    case: dict,
    *,
    repeat_index: int,
    actor_command: str,
    output_root: Path,
    judge_command: str | None,
) -> dict:
    episode_id = f"{case['id']}-r{repeat_index + 1:02d}"
    episode_dir = output_root / "episodes" / episode_id
    episode_dir.mkdir(parents=True, exist_ok=True)
    db_path = episode_dir / "nomnom.sqlite3"
    checkout_cli = episode_dir / "nomnom"
    actor_runs = []
    with ReplayServer(case) as replay:
        environment = {
            **os.environ,
            "NOMNOM_DB_PATH": str(db_path),
            "NOMNOM_ACCURACY_PROFILE": case["profile"],
            "NOMNOM_USDA_KEY": "synthetic-eval-placeholder",
            "NOMNOM_EVAL_MODE": "1",
            "NOMNOM_EVAL_PROVIDER_URL": replay.url,
            "NOMNOM_EVAL_CLI": f"{shlex.quote(sys.executable)} -m nomnomcli",
            "XDG_CONFIG_HOME": str(episode_dir / "config"),
            "XDG_CACHE_HOME": str(episode_dir / "cache"),
            "XDG_DATA_HOME": str(episode_dir / "data"),
            "XDG_STATE_HOME": str(episode_dir / "state"),
            "PYTHONPATH": str(ROOT),
            "PATH": f"{episode_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        }
        checkout_cli.write_text(
            "#!/bin/sh\n"
            f"export NOMNOM_DB_PATH={shlex.quote(str(db_path))}\n"
            f"export NOMNOM_ACCURACY_PROFILE={shlex.quote(case['profile'])}\n"
            "export NOMNOM_USDA_KEY=synthetic-eval-placeholder\n"
            "export NOMNOM_EVAL_MODE=1\n"
            f"export NOMNOM_EVAL_PROVIDER_URL={shlex.quote(replay.url)}\n"
            f"export PYTHONPATH={shlex.quote(str(ROOT))}\n"
            f"exec {shlex.quote(sys.executable)} -m nomnomcli \"$@\"\n",
            encoding="utf-8",
        )
        checkout_cli.chmod(0o700)
        prompts = (
            [step["raw_input"] for step in case["steps"]]
            if case["steps"]
            else [case["raw_input"]]
        )
        for index, prompt in enumerate(prompts):
            step = case["steps"][index] if case["steps"] else {}
            if step.get("action_before") == "seed_poisoned_cache":
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "nomnomcli",
                        "add",
                        "--name",
                        "apple",
                        "--brand",
                        "Synthetic Poison",
                        "--kcal",
                        "999",
                        "--protein",
                        "99",
                        "--fat",
                        "99",
                        "--carbs",
                        "99",
                        "--json",
                    ],
                    cwd=episode_dir,
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            actor_runs.append(
                run_actor(
                    actor_command=actor_command,
                    prompt=(
                        prompt
                        if "evals.fake_actor" in actor_command
                        else (
                            "Use the nomnom skill to log exactly this meal. Run only the "
                            f"sandbox CLI {checkout_cli}; do not run setup or doctor. Return "
                            f"only the final machine-readable CLI JSON. User input: {prompt}"
                        )
                    ),
                    env=environment,
                    episode_dir=episode_dir,
                    suffix=f"{index + 1:02d}",
                )
            )
            if step.get("action_after") == "remove_logged_event":
                log_id = actor_runs[-1].get("cli", {}).get("log_id")
                if log_id is not None:
                    subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "nomnomcli",
                            "log",
                            "remove",
                            str(log_id),
                            "--confirm",
                            "--json",
                        ],
                        cwd=episode_dir,
                        env=environment,
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
        events = read_events(db_path)
        result = evaluate(case, actor_runs, events, list(replay.state.requests))

        if judge_command and result["outcome"] == "pending":
            actor_path = episode_dir / "actor-01.json"
            judge_path = episode_dir / "judge.json"
            if actor_path.resolve() == judge_path.resolve():
                result["hard_failures"].append("actor_judge_result_path_collision")
            else:
                judge_prompt = (
                    "Review only unresolved semantic ambiguity for this user input: "
                    f"{case['raw_input']}"
                )
                command = render_command(
                    judge_command,
                    {
                        "prompt": judge_prompt,
                        "sandbox": str(episode_dir),
                        "db_path": str(db_path),
                        "actor_result": str(actor_path),
                        "judge_result": str(judge_path),
                        "max_turns": "4",
                    },
                )
                completed = subprocess.run(
                    command,
                    cwd=ROOT,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                result["judge"] = {
                    "returncode": completed.returncode,
                    "result_path": str(judge_path.relative_to(output_root)),
                }
        trace = {
            "case_id": case["id"],
            "repeat": repeat_index + 1,
            "actor_runs": actor_runs,
            "requests": replay.state.requests,
            "events": events,
            "evaluation": result,
        }
        (episode_dir / "trace.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    result["trace"] = str((episode_dir / "trace.json").relative_to(output_root))
    result["pass"] = not result["hard_failures"] and not result["ux_failures"]
    return result


def summarize(results: list[dict], repeats: int) -> dict:
    categories = defaultdict(lambda: {"passed": 0, "total": 0})
    for result in results:
        category = categories[result["category"]]
        category["total"] += 1
        category["passed"] += int(result["pass"])
    practical = [result for result in results if result["profile"] == "practical"]
    complete = sum(result["outcome"] == "complete" for result in practical)
    followup = sum(result["followups"] > 0 for result in practical)
    hard_counts = Counter(
        failure for result in results for failure in result["hard_failures"]
    )
    ux_counts = Counter(failure for result in results for failure in result["ux_failures"])
    portion_results = [
        result
        for result in practical
        if result["category"] == "fuzzy_portion" and result["resolved_items"]
    ]
    portion_inside = sum(
        not any(failure.startswith("grams_outside_envelope") for failure in result["ux_failures"])
        for result in portion_results
    )
    practical_metrics = {
        "catastrophic_semantic_substitutions": sum(
            count
            for failure, count in hard_counts.items()
            if failure.startswith("catastrophic_semantic_substitution")
        ),
        "invented_nutrition_or_source": sum(
            count
            for failure, count in hard_counts.items()
            if failure.startswith(("invented_nutrition", "source_not_allowed"))
        ),
        "lost_input_items": hard_counts["lost_input_item"],
        "incorrect_complete_status": hard_counts["incorrect_complete_status"],
        "one_pass_completion_rate": complete / len(practical) if practical else 0,
        "meals_requiring_followup_rate": followup / len(practical) if practical else 0,
        "max_followups_per_meal": max(
            (result["followups"] for result in practical), default=0
        ),
        "portion_inside_envelope_rate": (
            portion_inside / len(portion_results) if portion_results else 1
        ),
        "approximation_provenance_rate": (
            0 if hard_counts["approximation_assumption_missing"] else 1
        ),
    }
    release_gate = {
        "catastrophic_semantic_substitutions": (
            practical_metrics["catastrophic_semantic_substitutions"] == 0
        ),
        "invented_nutrition_or_source": (
            practical_metrics["invented_nutrition_or_source"] == 0
        ),
        "lost_input_items": practical_metrics["lost_input_items"] == 0,
        "incorrect_complete_status": practical_metrics["incorrect_complete_status"] == 0,
        "one_pass_completion": practical_metrics["one_pass_completion_rate"] >= 0.95,
        "followup_rate": practical_metrics["meals_requiring_followup_rate"] <= 0.05,
        "max_followups": practical_metrics["max_followups_per_meal"] <= 1,
        "portion_envelope": practical_metrics["portion_inside_envelope_rate"] >= 0.90,
        "approximation_provenance": (
            practical_metrics["approximation_provenance_rate"] == 1
        ),
    }
    return {
        "schema_version": 1,
        "episodes": len(results),
        "repeats": repeats,
        "passed": sum(result["pass"] for result in results),
        "failed": sum(not result["pass"] for result in results),
        "categories": dict(sorted(categories.items())),
        "hard_failures": dict(sorted(hard_counts.items())),
        "ux_failures": dict(sorted(ux_counts.items())),
        "practical_metrics": practical_metrics,
        "release_gate": release_gate,
        "release_gate_passed": all(release_gate.values()),
        "results": results,
    }


def markdown_report(report: dict) -> str:
    lines = [
        "# nomnom universal approximation eval",
        "",
        f"- Episodes: {report['episodes']}",
        f"- Passed: {report['passed']}",
        f"- Failed: {report['failed']}",
        f"- Practical release gate: {'PASS' if report['release_gate_passed'] else 'FAIL'}",
        "",
        "| Category | Passed | Total | Rate |",
        "|---|---:|---:|---:|",
    ]
    for name, values in report["categories"].items():
        rate = values["passed"] / values["total"]
        lines.append(f"| {name} | {values['passed']} | {values['total']} | {rate:.1%} |")
    lines.extend(["", "## Hard failures", ""])
    lines.append(
        "- None"
        if not report["hard_failures"]
        else "\n".join(
            f"- `{name}`: {count}" for name, count in report["hard_failures"].items()
        )
    )
    lines.extend(["", "## UX failures", ""])
    lines.append(
        "- None"
        if not report["ux_failures"]
        else "\n".join(
            f"- `{name}`: {count}" for name, count in report["ux_failures"].items()
        )
    )
    lines.extend(["", "## Reproduction", "", "```sh"])
    lines.append(
        "PYTHONPATH=. python -m evals.run --mode full --repeat 1 --concurrency 4"
    )
    lines.extend(["```", ""])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the synthetic nomnom subprocess eval")
    parser.add_argument("--mode", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--actor-command", default=default_actor_command())
    parser.add_argument("--judge-command")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.repeat < 1:
        raise SystemExit("--repeat must be at least 1")
    if not 1 <= args.concurrency <= 16:
        raise SystemExit("--concurrency must be between 1 and 16")
    corpus = load_corpus()
    cases = corpus["cases"][:3] if args.mode == "smoke" else corpus["cases"]
    (ROOT / "evals" / "artifacts").mkdir(parents=True, exist_ok=True)
    if args.output is not None and args.output.exists() and any(args.output.iterdir()):
        raise SystemExit("--output must be absent or an empty directory")
    output_root = args.output or Path(
        tempfile.mkdtemp(prefix="nomnom-eval-", dir=ROOT / "evals" / "artifacts")
    )
    output_root.mkdir(parents=True, exist_ok=True)
    jobs = [
        (case, repeat_index)
        for repeat_index in range(args.repeat)
        for case in cases
    ]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(
                run_episode,
                case,
                repeat_index=repeat_index,
                actor_command=args.actor_command,
                output_root=output_root,
                judge_command=args.judge_command,
            )
            for case, repeat_index in jobs
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda result: (result["id"], result["trace"]))
    report = summarize(results, args.repeat)
    (output_root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "summary.md").write_text(markdown_report(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output_root),
                "episodes": report["episodes"],
                "passed": report["passed"],
                "failed": report["failed"],
                "release_gate_passed": report["release_gate_passed"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["failed"] == 0 and report["release_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
