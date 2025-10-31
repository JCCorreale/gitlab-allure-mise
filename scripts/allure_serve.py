#!/usr/bin/env python3
import os
import sys
import tempfile
import zipfile
import subprocess
import requests
import datetime
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
if len(sys.argv) < 2:
    print("Usage: allure_serve.py <pipeline_id_env_var>")
    sys.exit(1)

# --- Get pipeline ID variable from program arguments ---
pipeline_id_env_var = sys.argv[1].strip()

# --- Prepare API URLs ---
pipeline_id = os.getenv(pipeline_id_env_var)
api_root = f"{GITLAB_URL.rstrip('/')}/api/v4/projects/{quote(PROJECT_PATH, safe='')}"
jobs_url = f"{api_root}/pipelines/{pipeline_id}/jobs"

# --- Retrieve jobs ---
print(f"🔍 Retrieving jobs for pipeline {pipeline_id} in project '{PROJECT_PATH}' ...")
resp = requests.get(jobs_url, headers={"PRIVATE-TOKEN": TOKEN})
if not resp.ok:
    print(f"❌ Failed to fetch jobs: {resp.status_code} {resp.text}")
    sys.exit(1)

jobs = resp.json()
job_id = next((j["id"] for j in jobs if j["name"] == JOB_NAME), None)
if not job_id:
    print(f"❌ Job '{JOB_NAME}' not found in pipeline {pipeline_id}.")
    sys.exit(1)

artifact_url = f"{api_root}/jobs/{job_id}/artifacts"

# --- Download and extract artifact ---
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
with requests.get(artifact_url, headers={"PRIVATE-TOKEN": TOKEN}, stream=True) as r:
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