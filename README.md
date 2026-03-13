# GitLab Allure Automation with Mise

Automate downloading Allure artifacts from any GitLab pipeline and serving them locally with `allure serve`. Works with private GitLab instances and is cross-platform.

## Setup

**1. Clone the repository:**
```
git clone <repo_url>
cd gitlab-allure-mise
```

**2. Configure GitLab access** using `allure_config.toml`:

```
[gitlab]
url = "https://gitlab.mycompany.com"
project = "group/subgroup/my-project"
token = "glpat-xxxxxxxxxxxx"
job_name = "test-report"
```

## Usage

Run the Mise task to download artifacts and serve them:

`mise run allure:serve <pipeline_id>`

**Example:**

`mise run allure:serve 123456`

**Override the job name temporarily:**

`GITLAB_JOB_NAME="e2e-results" mise run allure:serve 123456`

**Schedule mode (multiple pipelines):**

- Add `schedule_ids = ["123", "456"]` under `[gitlab]` in `allure_config.toml`, or set `GITLAB_PIPELINE_SCHEDULE_IDS="123,456"`.
- Run the same command: `mise run allure:serve anything` (the positional arg is ignored when schedule IDs are configured).
- The script fetches the latest pipeline per schedule, warns on non-success statuses, downloads Allure artifacts from successful ones, merges results, and serves them once.

## Dependencies

Handled automatically by Mise: Python 3.12+ and Allure CLI.