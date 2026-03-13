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

# schedule IDs from env (comma separated) or config list
schedule_ids_env = os.getenv("GITLAB_PIPELINE_SCHEDULE_IDS")
schedule_ids = []
if schedule_ids_env:
    schedule_ids = [s.strip() for s in schedule_ids_env.split(",") if s.strip()]
elif isinstance(config.get("schedule_ids"), list):
    schedule_ids = [str(s) for s in config.get("schedule_ids", []) if str(s).strip()]

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
if not schedule_ids and len(sys.argv) < 2:
    print("Usage: allure_serve.py <pipeline_id_env_var> or set GITLAB_PIPELINE_SCHEDULE_IDS / schedule_ids in config")
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

def download_artifacts(pipeline_id: str, workdir: str):
    job_id = fetch_job_id(pipeline_id)
    if not job_id:
        print(f"❌ Job '{JOB_NAME}' not found in pipeline {pipeline_id}.")
        return None
    artifact_url = f"{api_root}/jobs/{job_id}/artifacts"
    pipeline_dir = os.path.join(workdir, f"pipeline_{pipeline_id}")
    os.makedirs(pipeline_dir, exist_ok=True)
    zip_path = os.path.join(pipeline_dir, "artifacts.zip")
    artifacts_dir = os.path.join(pipeline_dir, "artifacts")
    allure_dir = os.path.join(artifacts_dir, "allure-results")
    print(f"📦 Downloading artifacts for pipeline {pipeline_id} ...")
    with requests.get(artifact_url, headers=HEADERS, stream=True) as r:
        if not r.ok:
            print(f"❌ Failed to download artifacts for pipeline {pipeline_id}: {r.status_code} {r.text}")
            return None
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    print("📂 Extracting artifacts ...")
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        for member in zip_ref.infolist():
            try:
                target_path = Path(artifacts_dir) / Path(member.filename)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                if not member.is_dir():
                    with open(target_path, "wb") as f:
                        f.write(zip_ref.read(member))
            except Exception as e:
                print(f"⚠️ Skipping {member.filename}: {e}")
    return allure_dir if os.path.isdir(allure_dir) else None

def copy_allure_results(source_dir: str, dest_dir: str):
    if not os.path.isdir(source_dir):
        print(f"⚠️ No allure-results at {source_dir}")
        return
    for root, dirs, files in os.walk(source_dir):
        rel_root = os.path.relpath(root, source_dir)
        target_root = os.path.join(dest_dir, rel_root)
        os.makedirs(target_root, exist_ok=True)
        for file in files:
            shutil.copy2(os.path.join(root, file), os.path.join(target_root, file))

def latest_pipeline_for_schedule(schedule_id: str):
    url = f"{api_root}/pipeline_schedules/{schedule_id}/pipelines?per_page=1"
    resp = requests.get(url, headers=HEADERS)
    if not resp.ok:
        print(f"❌ Failed to fetch pipelines for schedule {schedule_id}: {resp.status_code} {resp.text}")
        return None
    data = resp.json()
    if not data:
        print(f"⚠️ No pipelines found for schedule {schedule_id}")
        return None
    return data[0]

# --- Main logic ---
if schedule_ids:
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    tmpdir_obj = tempfile.TemporaryDirectory(prefix=f"allure-report_{timestamp}_", delete=False)
    tmp = tmpdir_obj.name
    combined_dir = os.path.join(tmp, "combined_allure_results")
    os.makedirs(combined_dir, exist_ok=True)
    print(f"📂 Created temporary directory {tmp}")
    any_success = False
    for sid in schedule_ids:
        info = latest_pipeline_for_schedule(sid)
        if not info:
            continue
        pipeline_id = info.get("id")
        status = info.get("status")
        print(f"🔍 Schedule {sid} latest pipeline {pipeline_id} status: {status}")
        if status != "success":
            print(f"❌ Pipeline {pipeline_id} for schedule {sid} is not successful (status={status})")
            continue
        allure_src = download_artifacts(str(pipeline_id), tmp)
        if allure_src:
            copy_allure_results(allure_src, combined_dir)
            any_success = True
    if not any_success:
        print("❌ No successful pipelines to serve.")
        sys.exit(1)
    print(f"🚀 Launching Allure to serve aggregated results from {combined_dir} ...")
    subprocess.run(["allure", "serve", combined_dir], shell=True)
else:
    pipeline_id_env_var = sys.argv[1].strip()
    pipeline_id = os.getenv(pipeline_id_env_var)
    if not pipeline_id:
        print(f"❌ Environment variable {pipeline_id_env_var} is empty")
        sys.exit(1)
    job_id = fetch_job_id(pipeline_id)
    if not job_id:
        print(f"❌ Job '{JOB_NAME}' not found in pipeline {pipeline_id}.")
        sys.exit(1)
    artifact_url = f"{api_root}/jobs/{job_id}/artifacts"
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = (f"allure-report_{timestamp}_")
    tmpdir_obj  = tempfile.TemporaryDirectory(prefix=prefix, delete=False)
    tmp = tmpdir_obj.name
    print(f"📂 Created temporary directory {tmp}")
    print(f"🆔 Found job '{JOB_NAME}' with ID {job_id}.")
    zip_path = os.path.join(tmp, "artifacts.zip")
    artifacts_dir = os.path.join(tmp, "artifacts")
    allure_dir = os.path.join(artifacts_dir, "allure-results")
    print(f"📦 Downloading artifacts for job {job_id} to temporary directory {tmp}...")
    with requests.get(artifact_url, headers=HEADERS, stream=True) as r:
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    print("📂 Extracting artifacts ...")
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        for member in zip_ref.infolist():
            try:
                # Build full path
                target_path = artifacts_dir / Path(member.filename)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                if not member.is_dir():
                    with open(target_path, "wb") as f:
                        f.write(zip_ref.read(member))
                        #f.flush()
                        #print(f"✅ Extracted {member.filename} to {target_path}")
            except Exception as e:
                print(f"⚠️ Skipping {member.filename}: {e}")
    print(f"🚀 Launching Allure to serve {allure_dir} ...")
    subprocess.run(["allure", "serve", allure_dir], shell=True)
    #subprocess.run(["allure", "--version"], shell=True)

    #tmpdir_obj.cleanup()

