## Overview

This script automates the execution of four REST API testing tools against a [Defects4REST](https://github.com/ANSWER-OSU/Defects4REST) project:

- **EvoMaster** — runs via Docker, no local install needed
- **Schemathesis** — runs on the host machine
- **RESTler** — runs via Docker, no local install needed
- **AutoRestTest** — runs on the host machine via Poetry

For each tool and each seed, the script calls `defects4rest checkout` to start the correct version of the API before running the tool. Output is stored in separate directories: `evomaster/`, `schemathesis/`, `restler/`, `autorest/`.

---

## Requirements

| Requirement | Notes |
|---|---|
| Python 3.10.x | Host machine (`>=3.10,<3.11`) |
| Docker (running) | Required for EvoMaster and RESTler — no local install of either tool needed |
| `defects4rest` CLI | Must be on `PATH` — [Defects4REST](https://github.com/ANSWER-OSU/Defects4REST) |
| `schemathesis` | `pip install schemathesis` |
| AutoRestTest + Poetry | Only needed with `--run autorest` — [setup below](#autoresttest-setup) |

> **EvoMaster and RESTler do not need to be installed on the host.** The script pulls their official Docker images automatically:
> - EvoMaster: `webfuzzing/evomaster`
> - RESTler: `mcr.microsoft.com/restlerfuzzer/restler:v8.5.0`

---

## Docker networking

EvoMaster and RESTler run inside Docker and need to reach the API server on your host machine.

- **Pass `http://localhost:<port>` as `--url`** — the script automatically rewrites `localhost` → `host.docker.internal` inside Docker commands.
- **macOS / Windows** (Docker Desktop): `host.docker.internal` is built in, nothing extra needed.
- **Linux** (Docker Engine): the script adds `--add-host=host.docker.internal:host-gateway` automatically.

---

## Usage

### Minimal example

```bash
python3 run_all.py \
  --project podman \
  --bug 1 \
  --version buggy \
  --schema api.json \
  --url http://localhost:8080
```

### Full example

```bash
python3 run_all.py \
  --run all \
  --project podman \
  --bug 1 \
  --version buggy \
  --schema api.json \
  --url http://localhost:8080 \
  --header "Authorization: Bearer TOKEN" \
  --seeds 21 23 33 42 2 \
  --evomaster-hours 1 \
  --restler-hours 1 \
  --autorest-runs 5 \
  --autorest-time 3600 \
  --autorest-workdir /path/to/AutoRestTest
```

### Run a single tool

```bash
# Only EvoMaster
python3 run_all.py --run evomaster --project podman --bug 1 --version buggy \
  --schema api.json --url http://localhost:8080

# Only RESTler
python3 run_all.py --run restler --project podman --bug 1 --version buggy \
  --schema api.json --url http://localhost:8080

# Only Schemathesis
python3 run_all.py --run schemathesis --project podman --bug 1 --version buggy \
  --schema api.json --url http://localhost:8080

# Only AutoRestTest
python3 run_all.py --run autorest --project podman --bug 1 --version buggy \
  --schema api.json \
  --autorest-workdir /path/to/AutoRestTest \
  --autorest-time 3600
```

---

## All arguments

### Required

| Argument | Description |
|---|---|
| `--project` | Defects4REST project name (e.g. `podman`, `dolibarr`, `flowable`) |
| `--bug` | Bug number in Defects4REST (e.g. `1`) |
| `--version` | `buggy` or `patched` |
| `--schema` | Path to local OpenAPI/Swagger JSON or YAML file |

### Common optional

| Argument | Default | Description |
|---|---|---|
| `--run` | `all` | Which tools to run: `evomaster`, `schemathesis`, `restler`, `autorest`, `all` |
| `--smoke` | off | Smoke-test mode: 2 min per tool, 1 seed — verifies connectivity and output before a full run |
| `--url` | — | Base API URL — required for EvoMaster, Schemathesis, RESTler |
| `--header` | — | HTTP header e.g. `--header "DOLAPIKEY: abc"` — can repeat |
| `--seeds` | `21 23 33 42 2` | Seeds for EvoMaster and Schemathesis (RESTler uses `--restler-runs` instead) |

### EvoMaster

| Argument | Default | Description |
|---|---|---|
| `--evomaster-hours` | `1` | Time budget per seed in hours |

### RESTler

> **Note:** RESTler has no `--seed` flag. It is a stateful BFS fuzzer, not a random fuzzer.
> Use `--restler-runs` to control how many independent fuzz campaigns to run (each restarts the API via checkout).
> Use `--restler-search-strategy` to change exploration behavior.

| Argument | Default | Description |
|---|---|---|
| `--restler-runs` | `5` | Number of independent fuzz campaigns |
| `--restler-hours` | `1` | Time budget per fuzz run in hours |
| `--restler-search-strategy` | `bfs-fast` | Search strategy: `bfs-fast`, `bfs`, `bfs-cheap`, `random-walk` |
| `--restler-test-port` | `8030` | Port for the RESTler smoke-test phase |
| `--restler-fuzz-port` | `809` | Port for the RESTler fuzz phase |

### AutoRestTest

| Argument | Default | Description |
|---|---|---|
| `--autorest-workdir` | — | **Required.** Root of the AutoRestTest repo (contains `pyproject.toml` and `configurations.toml`) |
| `--autorest-runs` | `1` | Number of AutoRestTest runs |
| `--autorest-time` | `1200` | MARL time budget per run in **seconds** (does not include Q-table init time) |
| `--autorest-output-dir` | `autorest` | Directory where run outputs (`data/`) are collected |

---

## AutoRestTest setup

AutoRestTest is an LLM-powered tool that requires a one-time setup before the script can call it.

### 1. Clone and install

```bash
git clone https://github.com/selab-gatech/AutoRestTest.git
cd AutoRestTest
poetry install          # requires Python 3.10.x
```

### 2. Add your LLM API key

Create a `.env` file in the AutoRestTest root:

```
API_KEY=your_openai_or_openrouter_key
```

AutoRestTest supports any OpenAI-API-compatible provider (OpenAI, OpenRouter, Azure, Ollama, LM Studio, etc.).

### 3. Configure `configurations.toml`

Edit `configurations.toml` in the AutoRestTest root. The key settings for Defects4REST runs:

```toml
[llm]
engine = "gpt-4o-mini"                  # model to use
api_base = "https://api.openai.com/v1"  # change for other providers

[api]
override_url = true    # use the host/port below instead of the spec's server URL
host = "localhost"     # hostname of the running API
port = 8080            # port of the running API

[request_generation]
time_duration = 1200   # seconds — overridden at runtime by --autorest-time

[cache]
use_cached_graph = true   # cache LLM graph between runs to save cost
use_cached_table = true   # cache Q-tables between runs to save cost
```

For APIs that need a static auth header add:

```toml
[custom_headers]
Authorization = "Bearer your_token"
# or
X-API-Key = "your_key"
```

> The `[api]` URL override in `configurations.toml` sets the host and port AutoRestTest connects to. The script passes the schema path via `-s` at runtime; the URL must be configured in `configurations.toml`.

### 4. Verify the setup works standalone

```bash
cd /path/to/AutoRestTest
poetry run autoresttest --quick
```

Once it runs interactively, the script can drive it headlessly with `--skip-wizard`.

---

## Output structure

```
evomaster/
  em_seed_21/          # EvoMaster generated tests
  em_seed_23/
  ...
  em_seed_21.log       # Full stdout/stderr log per seed
  em_seed_23.log
  ...

schemathesis/
  logs_har_seed21/     # HAR traffic logs
  st_seed21.xml        # JUnit XML report
  st_run_seed21.log    # Full Schemathesis log
  ...

restler/
  compiler_config.json
  restler_custom_dict.json
  restler_out/
    Compile/           # Grammar and dictionary from compile step
    fuzz_run_1/        # Fuzz results per run (RESTler has no seed concept)
    fuzz_run_2/
    ...

autorest/
  run1/                # Contents of AutoRestTest's data/ folder after run 1
    report.json
    operation_status_codes.json
    server_errors.json
    successful_parameters.json
    successful_responses.json
    successful_bodies.json
    successful_primitives.json
    q_tables.json
  run2/
  ...
```

> AutoRestTest output files can grow to several GB for long runs. Clear the `autorest/` directory when no longer needed.

---

## How checkout works

Before each tool run (per seed), the script calls:

```
defects4rest checkout -p <project> -b <bug> <buggy|patched> --start
```

This checks out and starts the correct version of the API server. The tool then runs against the live server on the configured port.
