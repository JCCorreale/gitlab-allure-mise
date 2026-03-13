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

`mise run allure:serve`

**Output directory options:**
- Default: saves under `out/<yyyy_MM_dd-hh_mm>/combined_allure_results` and serves from there.
- `--outdir <name>`: saves under `out/<name>/...`.
- `--use-tmp-dir`: uses a temp dir like before.
- `--serve-only <path>`: skip downloads, just `allure serve <path>`.

**Configuration (pipelines with label):**

In `allure_config.toml`:
```
[gitlab]
url = "https://gitlab.mycompany.com"
project = "group/subgroup/my-project"
token = "glpat-xxxxxxxxxxxx"
job_name = "test-report"

[[gitlab.pipelines]]
label = "nightly"
schedule_id = "123"  # picks latest successful pipeline from this schedule

[[gitlab.pipelines]]
label = "hotfix"
pipeline_id = "999999"  # uses this pipeline directly
```

- Ogni entry deve avere `label` e uno tra `pipeline_id` oppure `schedule_id`.
- Se è presente `pipeline_id`, viene usato direttamente.
- Se è presente `schedule_id`, viene presa la pipeline più recente (ordine desc per id). Se lo stato non è `success`, viene stampato un errore.
- Gli `allure-results` di tutte le pipeline successful vengono aggregati e serviti in un'unica istanza di Allure.

**Note:** eventuali variabili legacy `GITLAB_PIPELINE_SCHEDULE_IDS` o `schedule_ids` nel config vengono ancora accettate e convertite in `pipelines` con label auto-generata, ma il formato sopra è preferito.

## Dependencies

Handled automatically by Mise: Python 3.12+ and Allure CLI.