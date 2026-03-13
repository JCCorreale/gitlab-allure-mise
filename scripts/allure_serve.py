#!/usr/bin/env python3
import os
import sys
import tempfile
import zipfile
import subprocess
import requests
import datetime
import shutil
from urllib.parse import quote
from pathlib import Path


print("Python version:", sys.version)
print("Version info:", sys.version_info)

# --- Load allure_config.toml if present ---
config_file = Path("allure_config.toml")
config = {}
try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # for Python <3.11
if config_file.exists():
    with open(config_file, "rb") as f:
        toml_data = tomllib.load(f)
        config = toml_data.get("gitlab", {})

# --- Configuration ---
TOKEN = os.getenv("GITLAB_TOKEN") or config.get("token")
GITLAB_URL = os.getenv("GITLAB_URL") or config.get("url")
PROJECT_PATH = os.getenv("GITLAB_PROJECT") or config.get("project")
JOB_NAME = os.getenv("GITLAB_JOB_NAME") or config.get("job_name", "test-report")

# Legacy schedule IDs support (converted to pipeline entries)
schedule_ids_env = os.getenv("GITLAB_PIPELINE_SCHEDULE_IDS")
legacy_schedule_ids = []
if schedule_ids_env:
    legacy_schedule_ids = [s.strip() for s in schedule_ids_env.split(",") if s.strip()]
elif isinstance(config.get("schedule_ids"), list):
    legacy_schedule_ids = [str(s) for s in config.get("schedule_ids", []) if str(s).strip()]

# New pipelines configuration
pipelines_cfg = config.get("pipelines")
if not pipelines_cfg and legacy_schedule_ids:
    pipelines_cfg = [{"label": f"schedule-{sid}", "schedule_id": sid} for sid in legacy_schedule_ids]

# --- Validate configuration ---
if not TOKEN:
    print("❌ Missing GitLab token. Set GITLAB_TOKEN or provide in allure_config.toml/.env")
    sys.exit(1)
if not GITLAB_URL:
    print("❌ Missing GitLab URL. Set GITLAB_URL or provide in allure_config.toml/.env")
    sys.exit(1)
if not PROJECT_PATH:
    print("❌ Missing GitLab project path. Set GITLAB_PROJECT or provide in allure_config.toml/.env")
    sys.exit(1)
if not pipelines_cfg:
    print("❌ No pipelines configured. Add [[gitlab.pipelines]] entries with label and pipeline_id or schedule_id")
    sys.exit(1)

# --- Prepare API URLs ---
api_root = f"{GITLAB_URL.rstrip('/')}/api/v4/projects/{quote(PROJECT_PATH, safe='')}"
HEADERS = {"PRIVATE-TOKEN": TOKEN}

def fetch_job_id(pipeline_id: str):
    jobs_url = f"{api_root}/pipelines/{pipeline_id}/jobs"
    resp = requests.get(jobs_url, headers=HEADERS)
    if not resp.ok:
        print(f"❌ Failed to fetch jobs for pipeline {pipeline_id}: {resp.status_code} {resp.text}")
        return None
    jobs = resp.json()
    return next((j["id"] for j in jobs if j.get("name") == JOB_NAME), None)

def pipeline_info(pipeline_id: str):
    url = f"{api_root}/pipelines/{pipeline_id}"
    resp = requests.get(url, headers=HEADERS)
    if not resp.ok:
        print(f"❌ Failed to fetch pipeline {pipeline_id}: {resp.status_code} {resp.text}")
        return None
    return resp.json()

def download_artifacts(pipeline_id: str, workdir: str, label: str):
    job_id = fetch_job_id(pipeline_id)
    if not job_id:
        print(f"❌ [{label}] Job '{JOB_NAME}' not found in pipeline {pipeline_id}.")
        return None
    artifact_url = f"{api_root}/jobs/{job_id}/artifacts"
    pipeline_dir = os.path.join(workdir, f"{label}_pipeline_{pipeline_id}")
    os.makedirs(pipeline_dir, exist_ok=True)
    zip_path = os.path.join(pipeline_dir, "artifacts.zip")
    artifacts_dir = os.path.join(pipeline_dir, "artifacts")
    allure_dir = os.path.join(artifacts_dir, "allure-results")
    print(f"📦 [{label}] Downloading artifacts for pipeline {pipeline_id} ...")
    with requests.get(artifact_url, headers=HEADERS, stream=True) as r:
        if not r.ok:
            print(f"❌ [{label}] Failed to download artifacts for pipeline {pipeline_id}: {r.status_code} {r.text}")
            return None
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    print(f"📂 [{label}] Extracting artifacts ...")
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        for member in zip_ref.infolist():
            try:
                target_path = Path(artifacts_dir) / Path(member.filename)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                if not member.is_dir():
                    with open(target_path, "wb") as f:
                        f.write(zip_ref.read(member))
            except Exception as e:
                print(f"⚠️ [{label}] Skipping {member.filename}: {e}")
    return allure_dir if os.path.isdir(allure_dir) else None

def copy_allure_results(source_dir: str, dest_dir: str, label: str):
    if not os.path.isdir(source_dir):
        print(f"⚠️ [{label}] No allure-results at {source_dir}")
        return
    for root, dirs, files in os.walk(source_dir):
        rel_root = os.path.relpath(root, source_dir)
        target_root = os.path.join(dest_dir, rel_root)
        os.makedirs(target_root, exist_ok=True)
        for file in files:
            shutil.copy2(os.path.join(root, file), os.path.join(target_root, file))

def latest_pipeline_for_schedule(schedule_id: str):
    url = f"{api_root}/pipeline_schedules/{schedule_id}/pipelines?per_page=50&order_by=id&sort=desc"
    resp = requests.get(url, headers=HEADERS)
    if not resp.ok:
        print(f"❌ Failed to fetch pipelines for schedule {schedule_id}: {resp.status_code} {resp.text}")
        return None
    data = resp.json()
    if not data:
        print(f"⚠️ No pipelines found for schedule {schedule_id}")
        return None
    return max(data, key=lambda p: p.get("id", 0))

# --- Main logic ---
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
tmpdir_obj = tempfile.TemporaryDirectory(prefix=f"allure-report_{timestamp}_", delete=False)
tmp = tmpdir_obj.name
combined_dir = os.path.join(tmp, "combined_allure_results")
os.makedirs(combined_dir, exist_ok=True)
print(f"📂 Created temporary directory {tmp}")

any_success = False
seen = set()
for entry in pipelines_cfg:
    if not isinstance(entry, dict):
        print(f"⚠️ Invalid pipeline entry {entry}, skipping")
        continue
    label = entry.get("label") or entry.get("name") or "pipeline"
    pipeline_id = entry.get("pipeline_id")
    schedule_id = entry.get("schedule_id")
    if pipeline_id:
        key = ("pipeline", str(pipeline_id))
    else:
        key = ("schedule", str(schedule_id))
    if key in seen:
        print(f"ℹ️ [{label}] Skipping duplicate {key}")
        continue
    seen.add(key)

    info = None
    if pipeline_id:
        info = pipeline_info(str(pipeline_id))
    elif schedule_id:
        info = latest_pipeline_for_schedule(str(schedule_id))
    else:
        print(f"❌ [{label}] Missing pipeline_id or schedule_id, skipping")
        continue

    if not info:
        continue
    resolved_id = info.get("id")
    status = info.get("status")
    print(f"🔍 [{label}] Using pipeline {resolved_id} (status={status})")
    if status != "success":
        print(f"❌ [{label}] Pipeline {resolved_id} is not successful (status={status})")
        continue

    allure_src = download_artifacts(str(resolved_id), tmp, label)
    if allure_src:
        copy_allure_results(allure_src, combined_dir, label)
        any_success = True

if not any_success:
    print("❌ No successful pipelines to serve.")
    sys.exit(1)

print(f"🚀 Launching Allure to serve aggregated results from {combined_dir} ...")
subprocess.run(["allure", "serve", combined_dir], shell=True)
#tmpdir_obj.cleanup()

