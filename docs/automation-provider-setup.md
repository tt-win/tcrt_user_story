# Automation Hub — Provider Setup

Step-by-step config for every built-in provider, including Allure deployment
patterns (§6.5) and air-gapped LocalGit + self-hosted CI (§10.4).

All provider settings live under team scope at `/automation-provider-settings`
or via `POST /api/teams/{team_id}/automation-providers`. Credentials are
AES-256-GCM encrypted with `AUTOMATION_PROVIDER_ENCRYPTION_KEY`; only fingerprints
are returned by list endpoints.

---

## Storage providers

### `storage:github` — GitHub via REST API

| Config | Example | Notes |
|---|---|---|
| `owner` | `tc-gaming` | Org or user. |
| `repo` | `tcrt-automation` | Single repo per provider. |
| `default_branch` | `main` | Used when triggers omit `branch`. |
| `auth_method` | `pat` or `github_app` | See below. |
| `api_base_url` | `https://api.github.com` | Switch for GHE. |
| `default_runner_label` | `ubuntu-latest` | Injected into workflow inputs. |
| `scan_path` | `tests/` | Where auto-discovery starts. |

**Credentials**
- `auth_method=pat`: a Fine-grained Personal Access Token with `Contents: read`,
  `Pull requests: write` (for §10.3 PR creation), `Actions: read/write` on the
  target repo.
- `auth_method=github_app`: `app_id`, `installation_id`, `private_key_pem`
  (PEM string). Use this for org-wide deployments — the installation token
  is minted per request and refreshed automatically.

### `storage:local_git` — Working copy + `git` CLI (air-gapped)

For deployments that can't reach github.com. Mount a pre-cloned working copy
into the TCRT host (or a sidecar), point `working_dir` at it.

| Config | Example |
|---|---|
| `working_dir` | `/var/lib/tcrt/automation-repo` |
| `remote_name` | `origin` |
| `default_branch` | `main` |
| `ssh_key_path` | `/var/lib/tcrt/.ssh/automation_deploy_key` |

Behaviour:
- `list_scripts` / `read_script` operate against the working tree.
- `write_script` does `git add` + `git commit` + `git push` to `remote_name`.
- `create_pull_request` returns `None` — local git provider has no PR primitive
  (use upstream Gitea/GitLab UI manually). This is a documented
  non-goal (§10.3).
- `health_check` does a `git rev-parse HEAD` to confirm the working copy is
  valid.

Recommended deployment patterns:

| Pattern | Why |
|---|---|
| **GitLab self-hosted + LocalGit + Jenkins** | Air-gapped enterprise; SSO via GitLab, runners on internal infra. |
| **Gitea + LocalGit + Jenkins** | Lightweight, no external dependencies. |

---

## CI providers

### `ci:jenkins`

| Config | Example | Notes |
|---|---|---|
| `base_url` | `https://jenkins.example/` | Trailing slash optional. |
| `auth_method` | `api_token` or `trigger_token` | API token preferred. |
| `username` | `qa-bot` | Required for `api_token`. |
| `default_job_token` | `secret` | For `trigger_token` mode. |
| `default_runner_label` | `any` | Injected as `NODE_LABEL`. |
| `csrf_protection_enabled` | `true` | Auto-fetches `/crumbIssuer/api/json`. |
| `view_name_template` | `TCRT_{team_name}` | Team view name (always managed). Supports `{team_name}`, `{team_slug}`, and `{team_id}`. |
| `job_name_template` | `tcrt_{team_slug}_{suite_slug}` | Suite job naming (suite names are unique per team). |

**Credentials**: `username` + `api_token` (recommended) or just `job_token`
for trigger-only workflows.

TCRT auto-creates each suite as a Pipeline `Item` via `createItem`, writes the
config.xml from [jenkins-suite-config-example.xml](./automation-workflow-templates/jenkins-suite-config-example.xml), and adds it to the team
view (creating the view if missing). Because the Jenkins CI provider is org-level,
the view template is expanded at suite job creation / refresh time using the
suite's team context.

---

## Result providers

### `result:allure`

| Config | Example | Notes |
|---|---|---|
| `base_url` | `https://allure.example.com` | Front door of the Allure server. |
| `run_url_template` | `{base_url}/runs/{ci_external_run_id}` | Variables: `base_url`, `ci_external_run_id`, `project`. |
| `embed_mode` | `link` or `iframe` | UI mode for the Report button. |
| `project` | `tcrt-default` | Optional, for multi-project Allure. |
| `dashboard_url` | `https://allure.example.com/dashboards/team-qa` | Team-level entry; surfaces as the "Team Dashboard" button. |

**Credentials**: optional `api_token` for authenticated Allure servers.

When running `frankescobar/allure-docker-service` for the TCRT proxy flow,
persist projects at `/app/allure-docker-api/static/projects`, for example:

```bash
docker run -d --name allure -p 5050:5050 \
  -e KEEP_HISTORY=1 \
  -v "$PWD/allure-projects:/app/allure-docker-api/static/projects" \
  frankescobar/allure-docker-service
```

Mounting the same host directory at `/app/projects` is not enough for current
images; project creation can fail and TCRT will not receive a `report_url`.

`embed_mode: iframe` renders Report links in a modal `<iframe>`. If the
upstream sends `X-Frame-Options: DENY` the iframe will be blank — the modal
always shows an "Open in CI" fallback button.

### Allure deployment patterns (§6.5)

| Pattern | Best for | Caveats |
|---|---|---|
| **GitHub Pages** | Public projects; cheap; trivial CI step. | History pruning needs deliberate retention rules. |
| **S3 + CloudFront** | Private / corporate; signed URLs; CDN cache. | Requires AWS auth in workflow; CloudFront invalidation cost on writes. |
| **In-house nginx + retained `history/` dir** | Self-hosted; full history control. | DIY backup, TLS, auth. Mount the history directory across runs to avoid losing trends. |

Example workflow snippet (GitHub Pages):

```yaml
- name: Generate Allure report
  run: |
    pip install allure-pytest
    allure generate allure-results --clean -o site
- name: Deploy to Pages
  uses: peaceiris/actions-gh-pages@v3
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    publish_dir: ./site
```

Wire `run_url_template` to point at the per-run subdirectory you publish.

---

## Verifying a provider

The Settings UI exposes a *Test connection* button per provider. It calls
`POST /api/teams/{id}/automation-providers/{provider_id}/test-connection`,
which runs the provider's `health_check()`:

- GitHub → `GET /user` (whoami).
- Jenkins → `GET /me/api/json`.
- Allure → `GET /` with the configured `base_url`.

Result is stored on the provider row as `last_health_status` and surfaced as
a coloured badge.
