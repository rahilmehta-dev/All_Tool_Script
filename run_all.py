import subprocess
import argparse
import os
import sys
import json
import shutil

# ============================
# Global default configuration
# ============================

DEFAULT_SEEDS = [21, 23, 33, 42, 2]

# EvoMaster default settings
DEFAULT_EVOMASTER_HOURS = 1          # default 1 hour per seed
EVOMASTER_RATE_PER_MIN = 60

# Schemathesis default settings
SCHEMA_MAX_EXAMPLES = 1000
SCHEMA_WORKERS = 4
SCHEMA_RATE_LIMIT = "20/s"

# RESTler default settings (in HOURS)
RESTLER_TIME_BUDGET_DEFAULT = 1      # default 1 hour per seed

# AutoRestTest default settings
AUTOREST_DEFAULT_RUNS = 1
AUTOREST_DEFAULT_OUTPUT_DIR = "autorest"
AUTOREST_DEFAULT_TIME_SECONDS = 1200   # 20 min per run (MARL phase only)

# Set to True to re-enable AutoRestTest
AUTOREST_ENABLED = False


def run_logged(cmd, log_path, check=True):
    """Run cmd, streaming output to both the terminal and log_path."""
    with open(log_path, "w") as log_f:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log_f.write(line)
        proc.wait()
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)
    return proc.returncode


def parse_headers(header_args):
    """Parse --header "Name: value" arguments into list of (name, value)."""
    headers = []
    for h in header_args:
        if ":" not in h:
            raise ValueError(f"Invalid header format (expected 'Name: value'): {h}")
        name, value = h.split(":", 1)
        headers.append((name.strip(), value.strip()))
    return headers


def dockerize_url(url):
    """Rewrite localhost/127.0.0.1 to host.docker.internal for URLs used inside containers.

    On macOS/Windows Docker Desktop, --network host does not expose the host's
    loopback; host.docker.internal is the correct hostname to reach the Mac host
    from inside a container. --add-host=host.docker.internal:host-gateway makes
    the same name work on Linux Docker Engine.
    """
    return url.replace("://localhost", "://host.docker.internal") \
              .replace("://127.0.0.1", "://host.docker.internal")


# ============================
# Defects4REST checkout
# ============================

def checkout(project, bug, version, seed, tool):
    print(f"\n[checkout] project={project}, bug={bug}, version={version}, tool={tool}, seed={seed}")

    cmd = [
        "defects4rest",
        "checkout",
        "-p", project,
        "-i", str(bug),
        f"--{version}",
    ]

    print("  Running:", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"  Checkout failed (exit {e.returncode}): {e}")
    except Exception as e:
        print(f"  Checkout error: {e}")


# ============================
# EvoMaster
# ============================

def run_evomaster(project, bug, version, schema_path, base_url, api_headers, seeds, evomaster_max_time):
    print("\n==============================")
    print(" Running EvoMaster")
    print("==============================\n")

    out_root = os.path.join(os.getcwd(), f"{project}_{bug}", "EvoMaster")
    os.makedirs(out_root, exist_ok=True)

    # file:// URIs treat '#' as a fragment separator, so copy the schema to a safe name
    safe_schema_name = "schema_evomaster.yaml"
    safe_schema_host = os.path.join(out_root, safe_schema_name)
    shutil.copy2(schema_path, safe_schema_host)
    evomaster_schema_url = f"file:///work/{project}_{bug}/EvoMaster/{safe_schema_name}"

    for seed in seeds:
        print(f">>> EvoMaster seed {seed}")
        checkout(project, bug, version, seed, "EvoMaster")

        seed_dir_host = os.path.join(out_root, f"Seed_{seed}")
        os.makedirs(seed_dir_host, exist_ok=True)
        seed_dir_container = f"/work/{project}_{bug}/EvoMaster/Seed_{seed}"

        cmd = [
            "docker", "run", "--rm",
            "--add-host=host.docker.internal:host-gateway",
            "-v", f"{os.getcwd()}:/work",
            "webfuzzing/evomaster",
            "--blackBox", "true",
            "--problemType", "REST",
            "--bbSwaggerUrl", evomaster_schema_url,
            "--bbTargetUrl", dockerize_url(base_url),
            "--maxTime", evomaster_max_time,
            "--ratePerMinute", str(EVOMASTER_RATE_PER_MIN),
            "--seed", str(seed),
            "--outputFolder", seed_dir_container,
            "--outputFormat", "PYTHON_UNITTEST",
        ]

        for i, (name, value) in enumerate(api_headers):
            cmd.extend([f"--header{i}", f"{name}: {value}"])

        log_file = os.path.join(out_root, f"Seed_{seed}.log")
        print(f"    Log: {log_file}")
        try:
            run_logged(cmd, log_file)
        except subprocess.CalledProcessError as e:
            print(f"  EvoMaster seed {seed} failed (exit {e.returncode}), continuing...")

        print(f"    Output: {seed_dir_host}\n")


# ============================
# Schemathesis
# ============================

def run_schemathesis(project, bug, version, schema_path, base_url, api_headers, seeds):
    print("\n==============================")
    print(" Running Schemathesis")
    print("==============================\n")

    out_root = os.path.join(os.getcwd(), f"{project}_{bug}", "Schemathesis")
    os.makedirs(out_root, exist_ok=True)

    for seed in seeds:
        print(f">>> Schemathesis seed {seed}")
        checkout(project, bug, version, seed, "schemathesis")

        har_dir = os.path.join(out_root, f"Seed_{seed}")
        os.makedirs(har_dir, exist_ok=True)
        junit_path = os.path.join(out_root, f"Seed_{seed}.xml")

        cmd = [
            "schemathesis", "run",
            schema_path,
            "--url", base_url,
            "--checks", "all",
            "--exclude-checks", "status_code_conformance",
            "--max-examples", str(SCHEMA_MAX_EXAMPLES),
            "--workers", str(SCHEMA_WORKERS),
            "--rate-limit", SCHEMA_RATE_LIMIT,
            "--seed", str(seed),
            "--report", "junit",
            "--report-junit-path", junit_path,
            "--report", "har",
            "--report-dir", har_dir,
        ]

        for name, value in api_headers:
            cmd.extend(["--header", f"{name}: {value}"])

        log_file = os.path.join(out_root, f"Seed_{seed}.log")
        print(f"    Log: {log_file}")
        try:
            run_logged(cmd, log_file)
        except subprocess.CalledProcessError as e:
            print(f"  Schemathesis seed {seed} failed (exit {e.returncode}), continuing...")

        print(f"    HAR: {har_dir}")
        print(f"    JUnit: {junit_path}\n")


# ============================
# RESTler
# ============================

def run_restler(project, bug, version, schema_path, api_headers, runs, test_port, fuzz_port,
                time_budget_hours, search_strategy):
    # RESTler has NO --seed flag. It supports --search_strategy instead.
    # Multiple fuzz runs are used to gather variance; each run gets a fresh API checkout.
    print("\n==============================")
    print(" Running RESTler")
    print("==============================\n")
    print(f"[Config] RESTler fuzz runs: {runs}, strategy: {search_strategy}, time per run: {time_budget_hours}h\n")

    out_root = os.path.join(os.getcwd(), f"{project}_{bug}", "RESTler")
    os.makedirs(out_root, exist_ok=True)
    out_root_container = f"/work/{project}_{bug}/RESTler"

    safe_schema_name = "schema_restler.yaml"
    schema_copy_path = os.path.join(out_root, safe_schema_name)
    shutil.copy2(schema_path, schema_copy_path)
    print(f"[Config] Copied schema to: {schema_copy_path}")

    restler_header_dict = {name: [value] for (name, value) in api_headers}
    custom_dict = {}
    if restler_header_dict:
        custom_dict["restler_custom_payload_header"] = restler_header_dict

    custom_dict_path = os.path.join(out_root, "restler_custom_dict.json")
    with open(custom_dict_path, "w") as f:
        json.dump(custom_dict, f, indent=2)

    compiler_config = {
        "SwaggerSpecFilePath": [f"{out_root_container}/{safe_schema_name}"],
        "CustomDictionaryFilePath": f"{out_root_container}/restler_custom_dict.json"
    }
    compiler_config_path = os.path.join(out_root, "compiler_config.json")
    with open(compiler_config_path, "w") as f:
        json.dump(compiler_config, f, indent=2)

    # --add-host ensures host.docker.internal resolves on Linux; Docker Desktop (macOS/Windows) defines it automatically.
    DOCKER_HOST_EXTRA = ["--add-host=host.docker.internal:host-gateway"]

    print(">>> RESTler compile")
    compile_cmd = [
        "docker", "run", "--platform", "linux/amd64", "--rm",
        "-v", f"{os.getcwd()}:/work",
        "mcr.microsoft.com/restlerfuzzer/restler:v8.5.0",
        "dotnet", "/RESTler/restler/Restler.dll",
        "--workingDirPath", out_root_container,
        "compile", f"{out_root_container}/compiler_config.json",
    ]
    compile_log = os.path.join(out_root, "compile.log")
    print(f"    Log: {compile_log}")
    try:
        run_logged(compile_cmd, compile_log)
        print("    Compile done\n")
    except subprocess.CalledProcessError as e:
        print(f"    Compile failed (exit {e.returncode}), skipping RESTler entirely\n")
        return

    print(">>> RESTler test (smoke test)")
    test_cmd = [
        "docker", "run", "--platform", "linux/amd64", "--rm",
        "-v", f"{os.getcwd()}:/work",
        *DOCKER_HOST_EXTRA,
        "mcr.microsoft.com/restlerfuzzer/restler:v8.5.0",
        "dotnet", "/RESTler/restler/Restler.dll",
        "--workingDirPath", out_root_container,
        "test",
        "--grammar_file", f"{out_root_container}/Compile/grammar.py",
        "--dictionary_file", f"{out_root_container}/Compile/dict.json",
        "--no_ssl",
        "--target_ip", "host.docker.internal",
        "--target_port", str(test_port),
    ]
    test_log = os.path.join(out_root, "test.log")
    print(f"    Log: {test_log}")
    try:
        run_logged(test_cmd, test_log)
        print("    Test done\n")
    except subprocess.CalledProcessError as e:
        print(f"    Test failed (exit {e.returncode}), continuing to fuzz...\n")

    for run_num in range(1, runs + 1):
        print(f">>> RESTler fuzz run {run_num}/{runs}")
        checkout(project, bug, version, run_num, "RESTler")

        run_dir_host = os.path.join(out_root, f"Run_{run_num}")
        os.makedirs(run_dir_host, exist_ok=True)
        run_dir_container = f"{out_root_container}/Run_{run_num}"

        fuzz_cmd = [
            "docker", "run", "--platform", "linux/amd64", "--rm",
            "-v", f"{os.getcwd()}:/work",
            *DOCKER_HOST_EXTRA,
            "mcr.microsoft.com/restlerfuzzer/restler:v8.5.0",
            "dotnet", "/RESTler/restler/Restler.dll",
            "--workingDirPath", run_dir_container,
            "fuzz",
            "--grammar_file", f"{out_root_container}/Compile/grammar.py",
            "--dictionary_file", f"{out_root_container}/Compile/dict.json",
            "--no_ssl",
            "--target_ip", "host.docker.internal",
            "--target_port", str(fuzz_port),
            "--time_budget", str(time_budget_hours),
            "--search_strategy", search_strategy,
        ]

        fuzz_log = os.path.join(out_root, f"Run_{run_num}.log")
        print(f"    Log: {fuzz_log}")
        try:
            run_logged(fuzz_cmd, fuzz_log)
            print(f"    Finished run {run_num}, output: {run_dir_host}\n")
        except subprocess.CalledProcessError as e:
            print(f"    Fuzz run {run_num} failed (exit {e.returncode}), continuing...\n")


# ============================
# AutoRestTest
# ============================

def run_autorest(project, bug, version, schema_path, autorest_runs, autorest_workdir, autorest_time_seconds):
    print("\n==============================")
    print(" Running AutoRestTest")
    print("==============================\n")

    if not autorest_workdir:
        print("  ERROR: --autorest-workdir is required for AutoRestTest. Skipping.\n")
        return

    out_root = os.path.join(os.getcwd(), f"{project}_{bug}", "AutoRestTest")
    os.makedirs(out_root, exist_ok=True)

    # AutoRestTest needs an absolute spec path so it can be found from the workdir.
    schema_abs = os.path.abspath(schema_path)

    # data/ is where AutoRestTest writes its output files (report.json, etc.)
    data_dir = os.path.join(autorest_workdir, "data")

    for i in range(1, autorest_runs + 1):
        print(f">>> AutoRestTest run {i}")
        checkout(project, bug, version, i, "AutoRestTest")

        cmd = [
            "poetry", "run", "autoresttest",
            "--skip-wizard",
            "-s", schema_abs,
            "-t", str(autorest_time_seconds),
        ]

        run_log = os.path.join(out_root, f"Run_{i}.log")
        print(f"    Log: {run_log}")
        try:
            run_logged(cmd, run_log)
        except subprocess.CalledProcessError as e:
            print(f"    AutoRestTest run {i} failed (exit {e.returncode}), continuing...")
            continue

        dest = os.path.join(out_root, f"Run_{i}")
        if os.path.exists(data_dir):
            shutil.move(data_dir, dest)
            print(f"    Moved output to: {dest}")
        else:
            print(f"    WARNING: data/ folder not found at {data_dir}, nothing to move.")

    print("\n    AutoRestTest finished.\n")


# ============================
# Main
# ============================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run EvoMaster, Schemathesis, RESTler, and/or AutoRestTest on any project"
    )

    # What to run
    parser.add_argument(
        "--run",
        choices=["evomaster", "schemathesis", "restler", "autorest", "all"],
        default="all",
        help="Which tools to run (default: all)",
    )

    # Seeds
    parser.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        help=f"List of seeds to use (default: {DEFAULT_SEEDS})",
    )

    # Shared
    parser.add_argument(
        "--url",
        dest="base_url",
        help="Base API URL (e.g., http://localhost:8030/api/index.php)",
    )
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help='HTTP header, e.g. --header "DOLAPIKEY: 123" (can repeat)',
    )

    # Single schema for EvoMaster / Schemathesis / RESTler
    parser.add_argument(
        "--schema",
        required=True,
        help="Local OpenAPI/Swagger file used by EvoMaster, Schemathesis, and RESTler",
    )

    # EvoMaster
    parser.add_argument(
        "--evomaster-hours",
        type=float,
        help=f"EvoMaster maxTime in HOURS (default: {DEFAULT_EVOMASTER_HOURS})",
    )

    # RESTler
    parser.add_argument(
        "--restler-test-port",
        type=int,
        default=8030,
        help="RESTler test port (default: 8030)",
    )
    parser.add_argument(
        "--restler-fuzz-port",
        type=int,
        default=809,
        help="RESTler fuzz port (default: 809)",
    )
    parser.add_argument(
        "--restler-hours",
        type=float,
        help=f"RESTler fuzz time_budget in HOURS (default: {RESTLER_TIME_BUDGET_DEFAULT})",
    )
    parser.add_argument(
        "--restler-runs",
        type=int,
        default=len(DEFAULT_SEEDS),
        help=f"Number of RESTler fuzz runs (default: {len(DEFAULT_SEEDS)}). "
             "RESTler has no --seed flag; use this to control how many independent fuzz campaigns to run.",
    )
    parser.add_argument(
        "--restler-search-strategy",
        choices=["bfs-fast", "bfs", "bfs-cheap", "random-walk"],
        default="bfs-fast",
        help="RESTler search strategy (default: bfs-fast). "
             "Options: bfs-fast, bfs, bfs-cheap, random-walk",
    )

    # AutoRestTest
    parser.add_argument(
        "--autorest-runs",
        type=int,
        default=AUTOREST_DEFAULT_RUNS,
        help=f"Number of AutoRestTest runs (default: {AUTOREST_DEFAULT_RUNS})",
    )
    parser.add_argument(
        "--autorest-time",
        type=int,
        default=AUTOREST_DEFAULT_TIME_SECONDS,
        help=f"AutoRestTest MARL time budget per run in SECONDS (default: {AUTOREST_DEFAULT_TIME_SECONDS})",
    )
    parser.add_argument(
        "--autorest-workdir",
        default=None,
        help="Root directory of the AutoRestTest repo (must contain pyproject.toml and configurations.toml)",
    )

    # Defects4REST
    parser.add_argument(
        "--project",
        required=True,
        help="Project name (e.g., dolibarr, flowable, podman)"
    )
    parser.add_argument(
        "--bug",
        required=True,
        help="Bug number in defects4rest"
    )
    parser.add_argument(
        "--version",
        choices=["buggy", "patched"],
        required=True,
        help="Version to check out: buggy or patched for the bug"
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help=(
            "Smoke-test mode: runs every tool for ~2 minutes with 1 seed to verify "
            "API connectivity, Docker networking, and output paths before a full run. "
            "Overrides: EvoMaster maxTime=2m, RESTler time_budget=2m (1 run), "
            "Schemathesis max-examples=5, AutoRestTest time=120s (1 run)."
        ),
    )

    args = parser.parse_args()

    run_evo = args.run in ("evomaster", "all")
    run_sch = args.run in ("schemathesis", "all")
    run_res = args.run in ("restler", "all")
    run_auto = args.run in ("autorest", "all")

    # --smoke: 1 seed only, 2-min caps, 5 Schemathesis examples — verifies connectivity and output paths
    SMOKE_SEED = [DEFAULT_SEEDS[0]]
    SMOKE_EVOMASTER_TIME = "2m"
    SMOKE_RESTLER_HOURS = round(2 / 60, 4)   # 2 minutes in hours
    SMOKE_AUTOREST_TIME = 120                 # 2 minutes in seconds
    SMOKE_SCHEMA_EXAMPLES = 5

    if args.smoke:
        seeds = SMOKE_SEED
        print("\n*** SMOKE MODE: 1 seed, 2-minute time caps, 5 Schemathesis examples ***\n")
    else:
        seeds = args.seeds if args.seeds is not None else DEFAULT_SEEDS
    print(f"[Config] Using seeds: {seeds}")

    api_headers = parse_headers(args.header) if args.header else []
    if api_headers:
        print(f"[Config] Using headers: {api_headers}")
    else:
        print("[Config] No headers configured")

    # Basic validation
    if (run_evo or run_sch or run_res) and not args.base_url:
        print("ERROR: --url (base API URL) is required for EvoMaster/Schemathesis/RESTler.")
        raise SystemExit(1)

    if (run_evo or run_sch or run_res) and not os.path.exists(args.schema):
        print(f"ERROR: Schema file not found: {args.schema}")
        raise SystemExit(1)

    if args.smoke:
        evomaster_max_time = SMOKE_EVOMASTER_TIME
        restler_time_budget = SMOKE_RESTLER_HOURS
        restler_runs = 1
        autorest_time = SMOKE_AUTOREST_TIME
    else:
        evomaster_max_time = f"{args.evomaster_hours}h" if args.evomaster_hours is not None else f"{DEFAULT_EVOMASTER_HOURS}h"
        restler_time_budget = args.restler_hours if args.restler_hours is not None else RESTLER_TIME_BUDGET_DEFAULT
        restler_runs = args.restler_runs
        autorest_time = args.autorest_time

    print(f"[Config] EvoMaster maxTime: {evomaster_max_time}")
    print(f"[Config] RESTler time_budget (hours): {restler_time_budget}, runs: {restler_runs}")
    print(f"[Config] Project: {args.project}, Bug: {args.bug}, Version: {args.version}")
    print(f"[Config] Selected mode: {args.run}")

    if run_evo:
        run_evomaster(
            project=args.project,
            bug=args.bug,
            version=args.version,
            schema_path=args.schema,
            base_url=args.base_url,
            api_headers=api_headers,
            seeds=seeds,
            evomaster_max_time=evomaster_max_time,
        )

    if run_sch:
        # In smoke mode override max_examples globally for this run
        if args.smoke:
            SCHEMA_MAX_EXAMPLES = SMOKE_SCHEMA_EXAMPLES
        run_schemathesis(
            project=args.project,
            bug=args.bug,
            version=args.version,
            schema_path=args.schema,
            base_url=args.base_url,
            api_headers=api_headers,
            seeds=seeds,
        )

    if run_res:
        run_restler(
            project=args.project,
            bug=args.bug,
            version=args.version,
            schema_path=args.schema,
            api_headers=api_headers,
            runs=restler_runs,
            test_port=args.restler_test_port,
            fuzz_port=args.restler_fuzz_port,
            time_budget_hours=restler_time_budget,
            search_strategy=args.restler_search_strategy,
        )

    if run_auto and not AUTOREST_ENABLED:
        print("\n[AutoRestTest] Disabled (set AUTOREST_ENABLED = True in script to enable).\n")
    elif run_auto:
        run_autorest(
            project=args.project,
            bug=args.bug,
            version=args.version,
            schema_path=args.schema,
            autorest_runs=1 if args.smoke else args.autorest_runs,
            autorest_workdir=args.autorest_workdir,
            autorest_time_seconds=autorest_time,
        )

    print("=== Done ===")
