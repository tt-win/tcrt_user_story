## 1. Config & TLS Support
- [x] 1.1 Add `jira.ca_cert_path` to config models (`app/config.py`) and defaults, and document it in `config.yaml.example`.
- [x] 1.2 Add TLS utility to build a CA bundle (ported from `jira_sync_v3`), with fallback to the custom CA path when bundle creation fails.
- [x] 1.3 Update Jira client requests to use the computed `verify` value and log which CA mode is in use.

## 2. Validation
- [x] 2.1 Manual: With `jira.ca_cert_path` set to a valid custom CA, Jira API calls succeed and logs indicate the CA mode.
- [x] 2.2 Manual: Without `jira.ca_cert_path`, Jira API calls behave the same as before.
