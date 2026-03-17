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
job_name = "test-report"  # the job whose status/artifacts are used
```

## Usage

Run the Mise task to download artifacts and serve them:

`mise run allure:serve`

**Output directory options (precedence):**
- `--dir <path>`: serve an existing allure-results directory (skips download); overrides everything.
- `--outdir <name>`: saves under `out/<name>/...`.
- `--use-tmp-dir`: uses a temp dir; ignored if `--outdir` is set.
- Default (no flags): saves under `out/<yyyy_MM_dd-hh_mm>/combined_allure_results` and serves from there.

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
schedule_id = "123"  # picks latest pipeline from this schedule

[[gitlab.pipelines]]
label = "hotfix"
pipeline_id = "999999"  # uses this pipeline directly
```

- Ogni entry deve avere `label` e uno tra `pipeline_id` oppure `schedule_id`.
- Se è presente `pipeline_id`, viene usato direttamente.
- Se è presente `schedule_id`, viene presa la pipeline più recente (ordine desc per id) dal relativo schedule.
- Viene considerato solo lo stato del job `job_name` (deve essere `success`); se il job manca o non è `success`, viene registrato un errore.
- Gli `allure-results` di tutte le pipeline con job riuscito vengono aggregati e serviti in un'unica istanza di Allure.

**Errori e log:**
- Ogni errore viene registrato subito in `failures.txt` all'interno della cartella di output, in formato JSON per riga (contiene label e id di schedule/pipeline).
- Se non ci sono pipeline con job riuscito, il comando termina con errore.

## Dependencies

Handled automatically by Mise: Python 3.12+ and Allure CLI.