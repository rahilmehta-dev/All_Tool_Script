# Setup Guide

Follow these steps **once** before running `run_all.py` for the first time.

---

## 1. Clone this repo (with submodules)

```bash
git clone --recurse-submodules <this-repo-url>
cd All_Tool_Script
```

If you already cloned without `--recurse-submodules`, pull the submodule now:

```bash
git submodule update --init --recursive
```

---

## 2. Install system requirements

| Tool | How |
|---|---|
| Python **3.10.x** | `brew install python@3.10` (Mac) or `pyenv install 3.10` |
| Poetry | `pip install poetry` or [official installer](https://python-poetry.org/docs/#installation) |
| Docker Desktop | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) — must be **running** |
| `defects4rest` | Follow [Defects4REST install instructions](https://github.com/ANSWER-OSU/Defects4REST) |
| Schemathesis | `pip install schemathesis` |

---

## 3. Install AutoRestTest dependencies

```bash
cd AutoRestTest
poetry install
cd ..
```

> Poetry will use the pinned `poetry.lock` to install exact versions. This requires Python 3.10.x.
> If you have multiple Python versions, point Poetry to the right one first:
> ```bash
> poetry env use python3.10
> poetry install
> ```

---

## 4. Add your LLM API key

Create a file called `.env` inside the `AutoRestTest/` folder:

```bash
echo "API_KEY=your_key_here" > AutoRestTest/.env
```

AutoRestTest supports any OpenAI-API-compatible provider:

| Provider | `API_KEY` value |
|---|---|
| [OpenRouter](https://openrouter.ai) (recommended — access to many models) | OpenRouter API key |
| OpenAI | OpenAI API key |
| Local (Ollama, LM Studio) | Any string, e.g. `local` |

> **Cost estimate:** ~$0.10 per run using `gpt-4o-mini` on an API with ~15 operations.

---

## 5. Configure AutoRestTest for your project

Edit `AutoRestTest/configurations.toml`. The lines you need to change are:

### LLM model and provider

```toml
[llm]
engine = "gpt-4o-mini"                   # or "google/gemini-2.5-flash-lite-preview-09-2025", etc.
api_base = "https://api.openai.com/v1"   # or "https://openrouter.ai/api/v1" for OpenRouter
```

### API URL (point it to the running Defects4REST service)

```toml
[api]
override_url = true   # must be true to use host/port below
host = "localhost"
port = 8080           # change to whatever port your API runs on
```

### Auth headers (if the API requires a key or token)

```toml
[custom_headers]
Authorization = "Bearer your_token"
# or
X-API-Key = "your_key"
```

### Cache (keep enabled to save LLM cost across runs)

```toml
[cache]
use_cached_graph = true
use_cached_table = true
```

> **Port:** Check the Defects4REST docs for the port your specific project uses.
> For example, Dolibarr typically runs on `8030`, Podman on `8080`.

---

## 6. Verify AutoRestTest works

Test it manually once to make sure everything is configured correctly:

```bash
cd AutoRestTest
poetry run autoresttest --quick
cd ..
```

The interactive wizard should appear. If it runs and connects to the API you're fine.

---

## 7. Pull the RESTler and EvoMaster Docker images (optional, saves time later)

The script pulls these automatically, but you can pull them in advance:

```bash
docker pull webfuzzing/evomaster
docker pull mcr.microsoft.com/restlerfuzzer/restler:v8.5.0
```

---

## 8. Smoke test (run this first)

Before committing to a full multi-hour run, use `--smoke` to verify that every tool can connect to the API and write output correctly. Each tool runs for ~2 minutes with a single seed:

```bash
python3 run_all.py \
  --smoke \
  --run all \
  --project dolibarr \
  --bug 1 \
  --version buggy \
  --schema api.json \
  --url http://localhost:8030 \
  --header "DOLAPIKEY: your_key" \
  --autorest-workdir AutoRestTest
```

What `--smoke` overrides:
| Tool | Normal | Smoke |
|---|---|---|
| EvoMaster | 1h per seed × 5 seeds | 2m × 1 seed |
| Schemathesis | 1 example × 5 seeds | 5 examples × 1 seed |
| RESTler | 1h per run × 5 runs | 2m × 1 run |
| AutoRestTest | configured time × N runs | 120s × 1 run |

Check that:
- All four tools produced output in `evomaster/`, `schemathesis/`, `restler/`, `autorest/`
- No "Cannot connect" or "404" errors in the logs
- RESTler compile and test phases succeeded

---

## 9. Run the script (full run)

```bash
python3 run_all.py \
  --run all \
  --project <project> \
  --bug <bug_number> \
  --version buggy \
  --schema /path/to/api.json \
  --url http://localhost:<port> \
  --autorest-workdir AutoRestTest \
  --autorest-time 3600
```

**Example for Dolibarr bug 1:**

```bash
python3 run_all.py \
  --run all \
  --project dolibarr \
  --bug 1 \
  --version buggy \
  --schema api.json \
  --url http://localhost:8030 \
  --header "DOLAPIKEY: your_key" \
  --autorest-workdir AutoRestTest \
  --autorest-time 3600
```

**Run only AutoRestTest:**

```bash
python3 run_all.py \
  --run autorest \
  --project dolibarr \
  --bug 1 \
  --version buggy \
  --schema api.json \
  --autorest-workdir AutoRestTest \
  --autorest-time 3600
```

---

## Output locations

| Tool | Output folder |
|---|---|
| EvoMaster | `evomaster/em_seed_<N>/` + `evomaster/em_seed_<N>.log` |
| Schemathesis | `schemathesis/` |
| RESTler | `restler/restler_out/fuzz_run_<N>/` (RESTler has no seed — runs are numbered) |
| AutoRestTest | `autorest/run<N>/` (contains `report.json`, `server_errors.json`, etc.) |

---

## Troubleshooting

**`poetry install` fails with Python version error**
```bash
poetry env use python3.10
poetry install
```

**AutoRestTest can't reach the API**
Make sure `override_url = true` and the port in `configurations.toml` matches the running service.

**RESTler compile fails**
Check that Docker is running and the schema file path is correct.

**EvoMaster can't reach the API**
The script rewrites `localhost` → `host.docker.internal` automatically. If it still fails on Linux, check that Docker Engine supports `host-gateway`.

**LLM API errors**
Verify `API_KEY` in `AutoRestTest/.env` and that `api_base` in `configurations.toml` matches your provider.
