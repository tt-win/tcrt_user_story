"""
HTML Report Generation Service
- Generates a static HTML report for a specific Test Run
- Stores the file under generated_report/{report_id}.html
- Provides a stable report_id per test run: team-{team_id}-config-{config_id}

Notes:
- Pure static HTML (no app navigation or tool UI), minimal inline CSS
- Escapes user-provided content to avoid XSS
- Atomic write via temp file then rename
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import os
import json
from pathlib import Path

from sqlalchemy.orm import Session, joinedload


class HTMLReportService:
    def __init__(self, db_session: Session, base_dir: Optional[str] = None):
        self.db_session = db_session
        # Resolve base dir
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.report_root = self.base_dir / "generated_report"
        self.tmp_root = self.report_root / ".tmp"
        os.makedirs(self.tmp_root, exist_ok=True)

    # ---------------- Public API ----------------
    def generate_test_run_report(self, team_id: int, config_id: int) -> Dict[str, Any]:
        data = self._collect_report_data(team_id, config_id)
        report_id = f"team-{team_id}-config-{config_id}"
        html = self._render_html(data)

        # Atomic write
        final_path = self.report_root / f"{report_id}.html"
        tmp_path = self.tmp_root / f"{report_id}-{datetime.utcnow().timestamp()}.html"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(html)
        os.replace(tmp_path, final_path)

        return {
            "report_id": report_id,
            "report_url": f"/reports/{report_id}.html",
            "generated_at": datetime.utcnow().isoformat(),
            "overwritten": True,
        }

    # ---------------- Data Collection ----------------
    def _collect_report_data(self, team_id: int, config_id: int) -> Dict[str, Any]:
        from ..models.database_models import TestRunConfig as TestRunConfigDB, TestRunItem as TestRunItemDB
        from ..models.lark_types import Priority, TestResultStatus

        # Config
        config = self.db_session.query(TestRunConfigDB).filter(
            TestRunConfigDB.id == config_id,
            TestRunConfigDB.team_id == team_id,
        ).first()
        if not config:
            raise ValueError(f"找不到 Test Run 配置 (team_id={team_id}, config_id={config_id})")

        # Items
        items = self.db_session.query(TestRunItemDB).options(joinedload(TestRunItemDB.test_case)).filter(
            TestRunItemDB.team_id == team_id,
            TestRunItemDB.config_id == config_id,
        ).all()

        # Stats
        total_count = len(items)
        executed_count = len([i for i in items if i.test_result is not None])
        passed_count = len([i for i in items if i.test_result == TestResultStatus.PASSED])
        failed_count = len([i for i in items if i.test_result == TestResultStatus.FAILED])
        retest_count = len([i for i in items if i.test_result == TestResultStatus.RETEST])
        na_count = len([i for i in items if i.test_result == TestResultStatus.NOT_AVAILABLE])
        not_executed_count = total_count - executed_count

        execution_rate = (executed_count / total_count * 100) if total_count > 0 else 0.0
        pass_rate = (passed_count / executed_count * 100) if executed_count > 0 else 0.0

        # Priority
        def _item_priority(itm):
            case = getattr(itm, 'test_case', None)
            pri = getattr(case, 'priority', None)
            if pri is None:
                return None
            return pri.value if hasattr(pri, 'value') else pri

        priority_map = [_item_priority(i) for i in items]
        high_priority = len([pri for pri in priority_map if pri == Priority.HIGH.value])
        medium_priority = len([pri for pri in priority_map if pri == Priority.MEDIUM.value])
        low_priority = len([pri for pri in priority_map if pri == Priority.LOW.value])

        # Results list (all, 不限 100 筆)
        test_results: List[Dict[str, Any]] = []
        for i in items:
            case = getattr(i, 'test_case', None)
            case_title = getattr(case, 'title', None)
            case_priority = getattr(case, 'priority', None)
            priority_str = None
            if case_priority is not None:
                priority_str = case_priority.value if hasattr(case_priority, 'value') else case_priority

            # 獲取最新的 comment（從歷史記錄中取得）
            comment = None
            if getattr(i, 'histories', None):
                # 找到 change_source 為 'comment' 的最新記錄
                comment_histories = [h for h in i.histories if getattr(h, 'change_source', None) == 'comment']
                if comment_histories:
                    latest_comment = max(comment_histories, key=lambda h: getattr(h, 'changed_at', datetime.min))
                    comment = getattr(latest_comment, 'change_reason', None)
            
            test_results.append({
                "test_case_number": i.test_case_number or "",
                "title": case_title or "",
                "priority": priority_str or "",
                "status": i.test_result.value if getattr(i.test_result, 'value', None) else (i.test_result or "未執行"),
                "executor": i.assignee_name or "",
                "execution_time": i.executed_at.strftime('%Y-%m-%d %H:%M') if i.executed_at else "",
                "comment": comment or ""
            })

        # Bug tickets summary（不請 JIRA，直接顯示票號與關聯測試案例）
        bug_map: Dict[str, Dict[str, Any]] = {}
        for i in items:
            if getattr(i, 'bug_tickets_json', None):
                try:
                    tickets_data = json.loads(i.bug_tickets_json)
                    if isinstance(tickets_data, list):
                        for t in tickets_data:
                            if isinstance(t, dict) and 'ticket_number' in t:
                                ticket_no = str(t['ticket_number']).upper()
                                if ticket_no not in bug_map:
                                    bug_map[ticket_no] = { 'ticket_number': ticket_no, 'test_cases': [] }
                                case = getattr(i, 'test_case', None)
                                case_title = getattr(case, 'title', None)
                                bug_map[ticket_no]['test_cases'].append({
                                    'test_case_number': i.test_case_number or '',
                                    'title': case_title or '',
                                    'test_result': i.test_result.value if getattr(i.test_result, 'value', None) else (i.test_result or '未執行')
                                })
                except Exception:
                    pass
        bug_tickets = list(bug_map.values())

        return {
            "team_id": team_id,
            "config_id": config_id,
            "generated_at": datetime.utcnow(),
            "test_run_name": config.name,
            "test_run_description": getattr(config, 'description', None),
            "test_version": getattr(config, 'test_version', None),
            "test_environment": getattr(config, 'test_environment', None),
            "build_number": getattr(config, 'build_number', None),
            "status": config.status.value if getattr(config.status, 'value', None) else getattr(config, 'status', ''),
            "start_date": getattr(config, 'start_date', None),
            "end_date": getattr(config, 'end_date', None),
            "statistics": {
                "total_count": total_count,
                "executed_count": executed_count,
                "passed_count": passed_count,
                "failed_count": failed_count,
                "retest_count": retest_count,
                "not_available_count": na_count,
                "not_executed_count": not_executed_count,
                "execution_rate": execution_rate,
                "pass_rate": pass_rate,
            },
            "priority_distribution": {
                "高": high_priority,
                "中": medium_priority,
                "低": low_priority,
            },
            "status_distribution": {
                "Passed": passed_count,
                "Failed": failed_count,
                "Retest": retest_count,
                "Not Available": na_count,
                "Not Executed": not_executed_count,
            },
            "test_results": test_results,
            "bug_tickets": bug_tickets,
        }

    # ---------------- Rendering ----------------
    def _status_class(self, status_text: str) -> str:
        st = (status_text or '').strip().lower()
        if st == 'passed':
            return 'passed'
        if st == 'failed':
            return 'failed'
        if st == 'retest':
            return 'retest'
        if st in ('not available', 'n/a'):
            return 'na'
        if st in ('not executed', '未執行'):
            return 'pending'
        return 'pending'

    def _html_escape(self, text: Any) -> str:
        if text is None:
            return ""
        s = str(text)
        return (
            s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;")
             .replace("'", "&#39;")
        )

    def _render_html(self, data: Dict[str, Any]) -> str:
        # Minimal inline CSS, print friendly + align with Tool style colors
        css = """
        :root {
          --tr-primary: #0d6efd;
          --tr-success: #198754;
          --tr-danger: #dc3545;
          --tr-warning: #ffc107;
          --tr-secondary: #6c757d;
          --tr-surface: #ffffff;
          --tr-border: #e5e7eb;
          --tr-muted: #666;
          --tr-text: #222;
          --tr-table-head: #f8fafc;
        }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans TC', 'Helvetica Neue', Arial, 'PingFang TC', 'Microsoft JhengHei', sans-serif; color: var(--tr-text); margin: 24px; background: var(--tr-surface); }
        h1, h2, h3 { margin: 0.2em 0; }
        h1 { color: var(--tr-primary); }
        .muted { color: var(--tr-muted); }
        .section { margin-top: 24px; }
        .card { border: 1px solid var(--tr-border); border-radius: 8px; padding: 16px; background: #fff; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid var(--tr-border); padding: 8px; text-align: left; vertical-align: top; }
        th { background: var(--tr-table-head); color: #374151; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px,1fr)); gap: 12px; }
        .stat { font-size: 20px; font-weight: 600; }
        .small { font-size: 12px; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #eef2ff; color: #3730a3; font-size: 12px; }
        .pill { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
        .pill.passed { background: rgba(25,135,84,.12); color: var(--tr-success); border: 1px solid rgba(25,135,84,.3); }
        .pill.failed { background: rgba(220,53,69,.12); color: var(--tr-danger); border: 1px solid rgba(220,53,69,.3); }
        .pill.retest { background: rgba(13,110,253,.12); color: var(--tr-primary); border: 1px solid rgba(13,110,253,.3); }
        .pill.na { background: rgba(108,117,125,.12); color: var(--tr-secondary); border: 1px solid rgba(108,117,125,.3); }
        .pill.pending { background: rgba(255,193,7,.12); color: var(--tr-warning); border: 1px solid rgba(255,193,7,.3); }
        .footer { margin-top: 32px; border-top: 1px solid var(--tr-border); padding-top: 12px; font-size: 12px; color: #6b7280; }
        @media print { .no-print { display: none; } body { margin: 0; } }
        """

        esc = self._html_escape
        s = data.get("statistics", {})
        p = data.get("priority_distribution", {})
        sd = data.get("status_distribution", {})

        header_html = f"""
        <div>
          <h1>Test Run 報告</h1>
          <div class="muted">生成時間：{esc(data.get('generated_at').strftime('%Y-%m-%d %H:%M'))}</div>
          <div class="section card">
            <div class="grid">
              <div>
                <div class="small muted">名稱</div>
                <div class="stat">{esc(data.get('test_run_name'))}</div>
              </div>
              <div>
                <div class="small muted">測試環境</div>
                <div>{esc(data.get('test_environment'))}</div>
              </div>
              <div>
                <div class="small muted">建置版本</div>
                <div>{esc(data.get('build_number'))}</div>
              </div>
              <div>
                <div class="small muted">測試版本</div>
                <div>{esc(data.get('test_version'))}</div>
              </div>
            </div>
            <div class="section">
              <div class="small muted">描述</div>
              <div>{esc(data.get('test_run_description'))}</div>
            </div>
          </div>
        </div>
        """

        stats_html = f"""
        <div class="section card">
          <h2>執行摘要</h2>
          <div class="grid">
            <div><div class="small muted">總項目</div><div class="stat">{s.get('total_count', 0)}</div></div>
            <div><div class="small muted">已執行</div><div class="stat">{s.get('executed_count', 0)}</div></div>
            <div><div class="small muted">執行率</div><div class="stat">{int(s.get('execution_rate', 0))}%</div></div>
            <div><div class="small muted">Pass Rate</div><div class="stat">{int(s.get('pass_rate', 0))}%</div></div>
          </div>
        </div>
        <div class="section card">
          <h2>分布摘要</h2>
          <div class="grid">
            <div>
              <div class="small muted">狀態分布</div>
              <table>
                <tr><th>Passed</th><td>{sd.get('Passed', 0)}</td></tr>
                <tr><th>Failed</th><td>{sd.get('Failed', 0)}</td></tr>
                <tr><th>Retest</th><td>{sd.get('Retest', 0)}</td></tr>
                <tr><th>Not Available</th><td>{sd.get('Not Available', 0)}</td></tr>
                <tr><th>Not Executed</th><td>{sd.get('Not Executed', 0)}</td></tr>
              </table>
            </div>
            <div>
              <div class="small muted">優先級分布</div>
              <table>
                <tr><th>高</th><td>{p.get('高', 0)}</td></tr>
                <tr><th>中</th><td>{p.get('中', 0)}</td></tr>
                <tr><th>低</th><td>{p.get('低', 0)}</td></tr>
              </table>
            </div>
          </div>
        </div>
        """

        # Bug tickets section
        bt = data.get('bug_tickets', [])
        if bt:
            bug_rows = []
            for t in bt:
                cases_html = "".join([
                    f"<tr><td><code>{esc(c.get('test_case_number'))}</code></td><td>{esc(c.get('title'))}</td><td><span class='pill {self._status_class(c.get('test_result'))}'>{esc(c.get('test_result'))}</span></td></tr>"
                    for c in t.get('test_cases', [])
                ])
                bug_rows.append(
                    f"""
                    <div class=\"card\" style=\"margin-bottom:12px;\">
                      <div><strong>Ticket</strong>: <span class=\"badge\">{esc(t.get('ticket_number'))}</span></div>
                      <div class=\"section\" style=\"margin-top:8px;\">
                        <table>
                          <tr><th style=\"width:180px;\">Test Case Number</th><th>Title</th><th style=\"width:140px;\">Result</th></tr>
                          {cases_html}
                        </table>
                      </div>
                    </div>
                    """
                )
            bugs_html = f"""
            <div class=\"section card\">
              <h2>Bug Tickets</h2>
              {''.join(bug_rows)}
            </div>
            """
        else:
            bugs_html = f"""
            <div class=\"section card\">
              <h2>Bug Tickets</h2>
              <div class=\"muted\">無關聯的 Bug Tickets</div>
            </div>
            """

        rows = []
        rows.append("<tr><th style=\"width:160px;\">Test Case Number</th><th>Title</th><th style=\"width:100px;\">Priority</th><th style=\"width:140px;\">Result</th><th style=\"width:160px;\">Executor</th><th style=\"width:160px;\">Executed At</th><th style=\"width:200px;\">Comment</th></tr>")
        for r in data.get("test_results", []):
            status_text = r.get('status') or ''
            status_class = self._status_class(status_text)
            comment = r.get('comment') or ''
            rows.append(
                "<tr>"
                f"<td>{esc(r.get('test_case_number'))}</td>"
                f"<td>{esc(r.get('title'))}</td>"
                f"<td>{esc(r.get('priority'))}</td>"
                f"<td><span class=\"pill {status_class}\">{esc(status_text)}</span></td>"
                f"<td>{esc(r.get('executor'))}</td>"
                f"<td>{esc(r.get('execution_time'))}</td>"
                f"<td style=\"white-space: pre-wrap;\">{esc(comment)}</td>"
                "</tr>"
            )
        details_html = f"""
        <div class="section card">
          <h2>詳細測試結果</h2>
          <table>
            {''.join(rows)}
          </table>
        </div>
        """

        footer = """
        <div class="footer">
          <div>本頁為靜態報告，僅呈現測試執行結果，不提供任何操作介面。</div>
        </div>
        """

        html = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <meta name="robots" content="noindex,nofollow" />
  <title>Test Run 報告 - {esc(data.get('test_run_name'))}</title>
  <style>{css}</style>
</head>
<body>
  {header_html}
  {stats_html}
  {bugs_html}
  {details_html}
  {footer}
</body>
</html>
"""
        return html
