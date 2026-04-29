import subprocess
import argparse
import os
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
SCHEMA_MAX_EXAMPLES = 1
SCHEMA_WORKERS = 4
SCHEMA_RATE_LIMIT = "60/s"

# RESTler default settings (in HOURS)
RESTLER_TIME_BUDGET_DEFAULT = 1      # default 1 hour per seed

# AutoRestTest default settings
AUTOREST_DEFAULT_RUNS = 1
AUTOREST_DEFAULT_OUTPUT_DIR = "autorest"
AUTOREST_DEFAULT_TIME_SECONDS = 1200   # 20 min per run (MARL phase only)


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
        "-b", str(bug),
        version,
        "--start"
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

    evomaster_root = os.path.join(os.getcwd(), "evomaster")
    os.makedirs(evomaster_root, exist_ok=True)

    schema_basename = os.path.basename(schema_path)
    evomaster_schema_url = f"file:///work/{schema_basename}"

    for seed in seeds:
        print(f">>> EvoMaster seed {seed}")
        checkout(project, bug, version, seed, "EvoMaster")

        output_folder_host = os.path.join(evomaster_root, f"em_seed_{seed}")
        os.makedirs(output_folder_host, exist_ok=True)
        output_folder_container = f"/work/evomaster/em_seed_{seed}"

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
            "--outputFolder", output_folder_container,
            "--outputFormat", "PYTHON_UNITTEST",
        ]

        for i, (name, value) in enumerate(api_headers):
            cmd.extend([f"--header{i}", f"{name}: {value}"])

        log_file = os.path.join(evomaster_root, f"em_seed_{seed}.log")
        with open(log_file, "w") as f:
            try:
                subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=True)
            except subprocess.CalledProcessError as e:
                print(f"  EvoMaster seed {seed} failed (exit {e.returncode}), continuing...")

        print(f"    Log: {log_file}")
        print(f"    Output: {output_folder_host}\n")


# ============================
# Schemathesis
# ============================

def run_schemathesis(project, bug, version, schema_path, base_url, api_headers, seeds):
    print("\n==============================")
    print(" Running Schemathesis")
    print("==============================\n")

    schema_root = os.path.join(os.getcwd(), "schemathesis")
    os.makedirs(schema_root, exist_ok=True)

    for seed in seeds:
        print(f">>> Schemathesis seed {seed}")
        checkout(project, bug, version, seed, "schemathesis")

        har_dir = os.path.join(schema_root, f"logs_har_seed{seed}")
        os.makedirs(har_dir, exist_ok=True)
        junit_path = os.path.join(schema_root, f"st_seed{seed}.xml")

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

        log_file = os.path.join(schema_root, f"st_run_seed{seed}.log")
        with open(log_file, "w") as f:
            try:
                subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=True)
            except subprocess.CalledProcessError as e:
                print(f"  Schemathesis seed {seed} failed (exit {e.returncode}), continuing...")

        print(f"    Log: {log_file}")
        print(f"    HAR: {har_dir}")
        print(f"    JUnit: {junit_path}\n")


# ============================
# RESTler
# ============================

def run_restler(project, bug, version, schema_path, api_headers, seeds, test_port, fuzz_port, time_budget_hours):
    print("\n==============================")
    print(" Running RESTler")
    print("==============================\n")

    restler_root = os.path.join(os.getcwd(), "restler")
    os.makedirs(restler_root, exist_ok=True)

    schema_filename = os.path.basename(schema_path)
    schema_copy_path = os.path.join(restler_root, schema_filename)
    shutil.copy2(schema_path, schema_copy_path)
    print(f"[Config] Copied schema to: {schema_copy_path}")

    restler_header_dict = {name: [value] for (name, value) in api_headers}
    custom_dict = {}
    if restler_header_dict:
        custom_dict["restler_custom_payload_header"] = restler_header_dict

    custom_dict_path = os.path.join(restler_root, "restler_custom_dict.json")
    with open(custom_dict_path, "w") as f:
        json.dump(custom_dict, f, indent=2)

    compiler_config = {
        "SwaggerSpecFilePath": [f"/work/restler/{schema_filename}"],
        "CustomDictionaryFilePath": "/work/restler/restler_custom_dict.json"
    }
    compiler_config_path = os.path.join(restler_root, "compiler_config.json")
    with open(compiler_config_path, "w") as f:
        json.dump(compiler_config, f, indent=2)

    restler_out = os.path.join(restler_root, "restler_out")
    os.makedirs(restler_out, exist_ok=True)
    restler_out_container = "/work/restler/restler_out"

    # --add-host ensures host.docker.internal resolves on Linux; Docker Desktop (macOS/Windows) defines it automatically.
    DOCKER_HOST_EXTRA = ["--add-host=host.docker.internal:host-gateway"]

    print(">>> RESTler compile")
    compile_cmd = [
        "docker", "run", "--platform", "linux/amd64", "--rm",
        "-v", f"{os.getcwd()}:/work",
        "mcr.microsoft.com/restlerfuzzer/restler:v8.5.0",
        "dotnet", "/RESTler/restler/Restler.dll",
        "--workingDirPath", restler_out_container,
        "compile", "/work/restler/compiler_config.json",
    ]
    try:
        subprocess.run(compile_cmd, check=True)
        print("    Compile done\n")
    except subprocess.CalledProcessError as e:
        print(f"    Compile failed (exit {e.returncode}), skipping RESTler entirely\n")
        return

    print(">>> RESTler test")
    test_cmd = [
        "docker", "run", "--platform", "linux/amd64", "--rm",
        "-v", f"{os.getcwd()}:/work",
        *DOCKER_HOST_EXTRA,
        "mcr.microsoft.com/restlerfuzzer/restler:v8.5.0",
        "dotnet", "/RESTler/restler/Restler.dll",
        "--workingDirPath", restler_out_container,
        "test",
        "--grammar_file", f"{restler_out_container}/Compile/grammar.py",
        "--dictionary_file", f"{restler_out_container}/Compile/dict.json",
        "--no_ssl",
        "--target_ip", "host.docker.internal",
        "--target_port", str(test_port),
    ]
    try:
        subprocess.run(test_cmd, check=True)
        print("    Test done\n")
    except subprocess.CalledProcessError as e:
        print(f"    Test failed (exit {e.returncode}), continuing to fuzz...\n")

    for s in seeds:
        print(f">>> RESTler fuzz seed {s}")
        checkout(project, bug, version, s, "RESTler")

        seed_dir = os.path.join(restler_out, f"fuzz_seed_{s}")
        os.makedirs(seed_dir, exist_ok=True)
        seed_dir_container = f"{restler_out_container}/fuzz_seed_{s}"

        fuzz_cmd = [
            "docker", "run", "--platform", "linux/amd64", "--rm",
            "-v", f"{os.getcwd()}:/work",
            *DOCKER_HOST_EXTRA,
            "mcr.microsoft.com/restlerfuzzer/restler:v8.5.0",
            "dotnet", "/RESTler/restler/Restler.dll",
            "--workingDirPath", seed_dir_container,
            "fuzz",
            "--grammar_file", f"{restler_out_container}/Compile/grammar.py",
            "--dictionary_file", f"{restler_out_container}/Compile/dict.json",
            "--no_ssl",
            "--target_ip", "host.docker.internal",
            "--target_port", str(fuzz_port),
            "--time_budget", str(time_budget_hours),
        ]

        try:
            subprocess.run(fuzz_cmd, check=True)
            print(f"    Finished seed {s}, output: {seed_dir}\n")
        except subprocess.CalledProcessError as e:
            print(f"    Fuzz seed {s} failed (exit {e.returncode}), continuing...\n")


# ============================
# AutoRestTest
# ============================

def run_autorest(project, bug, version, schema_path, autorest_runs, autorest_output_dir, autorest_workdir, autorest_time_seconds):
    print("\n==============================")
    print(" Running AutoRestTest")
    print("==============================\n")

    if not autorest_workdir:
        print("  ERROR: --autorest-workdir is required for AutoRestTest. Skipping.\n")
        return

    os.makedirs(autorest_output_dir, exist_ok=True)

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

        try:
            subprocess.run(cmd, check=True, cwd=autorest_workdir)
        except subprocess.CalledProcessError as e:
            print(f"    AutoRestTest run {i} failed (exit {e.returncode}), continuing...")
            continue

        dest = os.path.join(autorest_output_dir, f"run{i}")
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
        "--autorest-output-dir",
        default=AUTOREST_DEFAULT_OUTPUT_DIR,
        help=f"Directory where run outputs are collected (default: {AUTOREST_DEFAULT_OUTPUT_DIR})",
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

    args = parser.parse_args()

    run_evo = args.run in ("evomaster", "all")
    run_sch = args.run in ("schemathesis", "all")
    run_res = args.run in ("restler", "all")
    run_auto = args.run in ("autorest", "all")

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

    evomaster_max_time = f"{args.evomaster_hours}h" if args.evomaster_hours is not None else f"{DEFAULT_EVOMASTER_HOURS}h"
    print(f"[Config] EvoMaster maxTime: {evomaster_max_time}")

    restler_time_budget = args.restler_hours if args.restler_hours is not None else RESTLER_TIME_BUDGET_DEFAULT
    print(f"[Config] RESTler time_budget (hours): {restler_time_budget}")

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
            seeds=seeds,
            test_port=args.restler_test_port,
            fuzz_port=args.restler_fuzz_port,
            time_budget_hours=restler_time_budget,
        )

    if run_auto:
        run_autorest(
            project=args.project,
            bug=args.bug,
            version=args.version,
            schema_path=args.schema,
            autorest_runs=args.autorest_runs,
            autorest_output_dir=args.autorest_output_dir,
            autorest_workdir=args.autorest_workdir,
            autorest_time_seconds=args.autorest_time,
        )

    print("=== Done ===")
