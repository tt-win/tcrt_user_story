## 1. Config Contract

- [x] 1.1 Add `ReportsConfig` and load `reports.root_dir` / `REPORTS_ROOT_DIR` from the settings pipeline
- [x] 1.2 Update `config.yaml.example` and default config output to document the new report root setting

## 2. Report Path Integration

- [x] 2.1 Update `app/main.py` to resolve `/reports` from the configured report root and create directories before mounting
- [x] 2.2 Update `HTMLReportService` and report existence checks to use the same resolved report root

## 3. Verification

- [x] 3.1 Add focused tests for report root resolution and HTML report service path selection
- [x] 3.2 Run focused pytest coverage for the new report path behavior
