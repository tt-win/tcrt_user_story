"""
PDF Report Generation Service using ReportLab
"""
import io
from datetime import datetime
from typing import Dict, Any, List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, 
    KeepTogether, PageBreak, Image
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import Color, black, white, red, green, orange, blue, grey
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

import os

# Ensure matplotlib can write its cache in restricted environments
try:
    os.environ.setdefault('MPLCONFIGDIR', '/tmp/mplconfig')
    os.makedirs(os.environ['MPLCONFIGDIR'], exist_ok=True)
except Exception:
    # If /tmp isn't writable for some reason, ignore; matplotlib will attempt defaults
    pass

import matplotlib
# Use non-GUI backend to avoid server-side rendering issues
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
import os
from app.database import run_sync


class PDFReportService:
    """ReportLab-based PDF report generation service"""
    
    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _setup_custom_styles(self):
        """Setup custom paragraph styles for the report"""
        # 註冊中文字型
        chinese_font = self._register_chinese_font()
        
        # 標題樣式
        self.styles.add(ParagraphStyle(
            name='ChineseTitle',
            parent=self.styles['Title'],
            fontSize=20,
            spaceAfter=30,
            alignment=TA_CENTER,
            textColor=colors.black,
            fontName=chinese_font
        ))
        
        # 副標題樣式
        self.styles.add(ParagraphStyle(
            name='ChineseSubtitle',
            parent=self.styles['Heading1'],
            fontSize=14,
            spaceAfter=15,
            alignment=TA_LEFT,
            textColor=colors.black,
            fontName=chinese_font
        ))
        
        # 一般內容樣式
        self.styles.add(ParagraphStyle(
            name='ChineseNormal',
            parent=self.styles['Normal'],
            fontSize=11,
            spaceAfter=12,
            alignment=TA_LEFT,
            textColor=colors.black,
            fontName=chinese_font
        ))
    
    def _register_chinese_font(self) -> str:
        """註冊中文字型並回傳字型名稱"""
        # 嘗試的字型路徑（按優先順序）
        font_paths = [
            '/Library/Fonts/Arial Unicode.ttf',  # macOS
            '/System/Library/Fonts/Arial.ttc',   # macOS fallback
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',  # Linux
            '/Windows/Fonts/simhei.ttf',  # Windows
            '/Windows/Fonts/msyh.ttc'     # Windows
        ]
        
        font_name = 'ChineseFont'
        
        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    if font_path.endswith('.ttc'):
                        # TrueType Collection 需要指定子字型
                        pdfmetrics.registerFont(TTFont(font_name, font_path, subfontIndex=0))
                    else:
                        pdfmetrics.registerFont(TTFont(font_name, font_path))
                    
                    # 儲存字型名稱供其他方法使用
                    self.chinese_font = font_name
                    return font_name
                except Exception as e:
                    print(f"Failed to register font {font_path}: {e}")
                    continue
        
        # 如果找不到合適字型，嘗試使用 ReportLab 內建 CID 字型（支援 CJK）
        try:
            # STSong-Light 主要為簡體中文；MSung-Light 支援繁體
            # 優先嘗試 MSung-Light，若不可用則退回 STSong-Light
            try:
                cid_font_name = 'MSung-Light'
                pdfmetrics.registerFont(UnicodeCIDFont(cid_font_name))
            except Exception:
                cid_font_name = 'STSong-Light'
                pdfmetrics.registerFont(UnicodeCIDFont(cid_font_name))
            self.chinese_font = cid_font_name
            print(f"Info: Using CID font as fallback: {cid_font_name}")
            return cid_font_name
        except Exception as e:
            # 最後退回 Helvetica（可能無法顯示 CJK，僅保證不崩潰）
            print(f"Warning: No suitable Chinese font found, falling back to Helvetica. Reason: {e}")
            self.chinese_font = 'Helvetica'
            return 'Helvetica'
    
    async def generate_test_run_report(self, team_id: int, config_id: int) -> bytes:
        """
        Generate PDF report for a specific test run
        
        Args:
            team_id: Team ID
            config_id: Test run configuration ID
            
        Returns:
            bytes: Generated PDF content
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72
        )
        
        # 收集報告數據
        report_data = await self._collect_report_data(team_id, config_id)
        
        # 建立報告內容
        story = []
        
        # 第一頁：報告標題和執行統計概覽
        story.extend(self._build_header(report_data))
        story.extend(self._build_statistics_section(report_data))
        
        # 強制分頁 - 第二頁開始：狀態和優先級分佈圖表
        story.append(PageBreak())
        story.extend(self._build_status_chart(report_data))
        story.extend(self._build_priority_chart(report_data))
        
        # 強制分頁 - 第三頁開始：詳細測試結果表格
        story.append(PageBreak())
        story.extend(self._build_results_table(report_data))
        
        # 頁腳資訊
        story.extend(self._build_footer())
        
        # 生成 PDF
        doc.build(story)
        
        buffer.seek(0)
        return buffer.read()
    
    async def _collect_report_data(self, team_id: int, config_id: int) -> Dict[str, Any]:
        return await run_sync(self.db_session, self._collect_report_data_sync, team_id, config_id)

    def _collect_report_data_sync(self, sync_db: Session, team_id: int, config_id: int) -> Dict[str, Any]:
        """Collect all necessary data for the report"""
        from ..models.database_models import TestRunConfig as TestRunConfigDB, TestRunItem as TestRunItemDB
        from ..models.lark_types import Priority, TestResultStatus
        import json
        
        # 獲取 Test Run 配置資訊
        config = sync_db.query(TestRunConfigDB).filter(
            TestRunConfigDB.id == config_id,
            TestRunConfigDB.team_id == team_id
        ).first()
        
        if not config:
            raise ValueError(f"找不到 Test Run 配置 (team_id={team_id}, config_id={config_id})")
        
        # 獲取所有測試項目
        items_query = sync_db.query(TestRunItemDB).options(joinedload(TestRunItemDB.test_case)).filter(
            TestRunItemDB.team_id == team_id,
            TestRunItemDB.config_id == config_id
        )
        items = items_query.all()
        
        # 計算基本統計
        total_count = len(items)
        # executed_count: 排除 Pending 的所有非空狀態 (包含 Not Required)
        executed_count = len([item for item in items if item.test_result is not None and item.test_result != TestResultStatus.PENDING])
        
        passed_count = len([item for item in items if item.test_result == TestResultStatus.PASSED])
        failed_count = len([item for item in items if item.test_result == TestResultStatus.FAILED])
        retest_count = len([item for item in items if item.test_result == TestResultStatus.RETEST])
        na_count = len([item for item in items if item.test_result == TestResultStatus.NOT_AVAILABLE])
        pending_count = len([item for item in items if item.test_result == TestResultStatus.PENDING])
        not_required_count = len([item for item in items if item.test_result == TestResultStatus.NOT_REQUIRED])
        skip_count = len([item for item in items if item.test_result == TestResultStatus.SKIP])
        
        # 未執行 = 總數 - 已執行 - Pending (如果 Pending 算未執行的一種)
        # 實際上 Pending 就是 explicit "Not Executed". 
        # implicit "Not Executed" 是 test_result is None.
        implicit_not_executed_count = len([item for item in items if item.test_result is None])
        
        # 總未執行 = Implicit None + Explicit Pending
        not_executed_total = implicit_not_executed_count + pending_count
        
        execution_rate = (executed_count / total_count * 100) if total_count > 0 else 0.0
        pass_rate = (passed_count / executed_count * 100) if executed_count > 0 else 0.0
        
        # 計算優先級分佈
        def _item_priority(itm):
            case = getattr(itm, 'test_case', None)
            pri = getattr(case, 'priority', None)
            if pri is None:
                return None
            return pri.value if hasattr(pri, 'value') else pri

        priority_values = [_item_priority(item) for item in items]
        high_priority = len([pri for pri in priority_values if pri == Priority.HIGH.value])
        medium_priority = len([pri for pri in priority_values if pri == Priority.MEDIUM.value])
        low_priority = len([pri for pri in priority_values if pri == Priority.LOW.value])
        
        # 計算 Bug Tickets 統計
        unique_bug_tickets = set()
        for item in items:
            if item.bug_tickets_json:
                try:
                    tickets_data = json.loads(item.bug_tickets_json)
                    if isinstance(tickets_data, list):
                        for ticket in tickets_data:
                            if isinstance(ticket, dict) and 'ticket_number' in ticket:
                                unique_bug_tickets.add(ticket['ticket_number'].upper())
                except Exception:
                    pass
        
        # 準備詳細測試結果數據（限制前 100 筆）
        test_results = []
        for item in items[:100]:
            case = getattr(item, 'test_case', None)
            case_title = getattr(case, 'title', None)
            case_priority = getattr(case, 'priority', None)
            priority_str = None
            if case_priority is not None:
                priority_str = case_priority.value if hasattr(case_priority, 'value') else case_priority
            
            status_str = '未執行'
            if item.test_result:
                status_str = item.test_result.value if hasattr(item.test_result, 'value') else item.test_result
                
            test_results.append({
                'test_case_number': item.test_case_number or '',
                'title': case_title or '',
                'priority': priority_str or '',
                'status': status_str,
                'executor': item.assignee_name or '',
                'execution_time': item.executed_at.strftime('%Y-%m-%d %H:%M') if item.executed_at else ''
            })
        
        return {
            'team_id': team_id,
            'config_id': config_id,
            'generated_at': datetime.now(),
            'test_run_name': config.name,
            'test_run_description': config.description,
            'test_version': config.test_version,
            'test_environment': config.test_environment,
            'build_number': config.build_number,
            'status': config.status.value if config.status else '',
            'start_date': config.start_date,
            'end_date': config.end_date,
            'statistics': {
                'total_count': total_count,
                'executed_count': executed_count,
                'passed_count': passed_count,
                'failed_count': failed_count,
                'retest_count': retest_count,
                'not_available_count': na_count,
                'pending_count': pending_count,
                'not_required_count': not_required_count,
                'skip_count': skip_count,
                'not_executed_count': not_executed_total,
                'execution_rate': execution_rate,
                'pass_rate': pass_rate,
                'bug_tickets_count': len(unique_bug_tickets)
            },
            'status_distribution': {
                'Passed': passed_count,
                'Failed': failed_count,
                'Retest': retest_count,
                'Not Available': na_count,
                'Pending': pending_count,
                'Not Required': not_required_count,
                'Skip': skip_count,
                'Not Executed': implicit_not_executed_count
            },
            'priority_distribution': {
                '高': high_priority,
                '中': medium_priority,
                '低': low_priority
            },
            'test_results': test_results,
            'bug_tickets': list(unique_bug_tickets)
        }
    
    def _build_header(self, data: Dict[str, Any]) -> List:
        """Build report header section"""
        story = []
        
        # 主標題
        title = Paragraph(
            f"Test Run 執行分析報告", 
            self.styles['ChineseTitle']
        )
        story.append(title)
        
        # Test Run 名稱
        test_run_title = Paragraph(
            f"<b>{data['test_run_name']}</b>",
            self.styles['ChineseSubtitle']
        )
        story.append(test_run_title)
        
        # 基本資訊表格
        info_data = [
            ['項目', '詳細資訊'],
            ['Test Run 狀態', data['status']],
            ['測試版本', data['test_version'] or 'N/A'],
            ['測試環境', data['test_environment'] or 'N/A'],
            ['Build 編號', data['build_number'] or 'N/A'],
        ]
        
        # 添加日期資訊（如果有的話）
        if data['start_date']:
            info_data.append(['開始日期', data['start_date'].strftime('%Y-%m-%d')])
        if data['end_date']:
            info_data.append(['結束日期', data['end_date'].strftime('%Y-%m-%d')])
            
        info_data.append(['報告生成時間', data['generated_at'].strftime('%Y-%m-%d %H:%M:%S')])
        
        info_table = Table(info_data, colWidths=[2*inch, 4*inch])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), self.chinese_font),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        story.append(info_table)
        story.append(Spacer(1, 25))
        
        # 描述（如果有的話）
        if data.get('test_run_description'):
            story.append(Paragraph("描述", self.styles['ChineseSubtitle']))
            story.append(Paragraph(data['test_run_description'], self.styles['ChineseNormal']))
            story.append(Spacer(1, 15))
        
        return story
    
    def _build_statistics_section(self, data: Dict[str, Any]) -> List:
        """Build statistics overview section"""
        story = []
        stats = data['statistics']
        
        # 統計概覽標題
        story.append(Paragraph("執行統計概覽", self.styles['ChineseSubtitle']))
        
        # 統計表格
        stats_data = [
            ['項目', '數值', '百分比'],
            ['總測試案例數', str(stats['total_count']), '100.0%'],
            ['已執行案例數', str(stats['executed_count']), f"{stats['execution_rate']:.1f}%"],
            ['通過案例數', str(stats['passed_count']), f"{(stats['passed_count']/stats['total_count']*100) if stats['total_count'] > 0 else 0:.1f}%"],
            ['失敗案例數', str(stats['failed_count']), f"{(stats['failed_count']/stats['total_count']*100) if stats['total_count'] > 0 else 0:.1f}%"],
            ['需重測案例數', str(stats['retest_count']), f"{(stats['retest_count']/stats['total_count']*100) if stats['total_count'] > 0 else 0:.1f}%"],
            ['不適用案例數', str(stats['not_available_count']), f"{(stats['not_available_count']/stats['total_count']*100) if stats['total_count'] > 0 else 0:.1f}%"],
            ['不需要案例數', str(stats['not_required_count']), f"{(stats['not_required_count']/stats['total_count']*100) if stats['total_count'] > 0 else 0:.1f}%"],
            ['未執行案例數', str(stats['not_executed_count']), f"{(stats['not_executed_count']/stats['total_count']*100) if stats['total_count'] > 0 else 0:.1f}%"],
            ['待處理案例數', str(stats['pending_count']), f"{(stats['pending_count']/stats['total_count']*100) if stats['total_count'] > 0 else 0:.1f}%"],
            ['', '', ''],  # 分隔行
            ['執行通過率', f"{stats['pass_rate']:.1f}%", '(已執行中的通過比例)'],
            ['Bug Tickets 數量', str(stats['bug_tickets_count']), '']
        ]
        
        table = Table(stats_data, colWidths=[2.5*inch, 1.5*inch, 2*inch])
        table.setStyle(TableStyle([
            # 標題行樣式
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, -1), self.chinese_font),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            
            # 數據行樣式
            ('BACKGROUND', (0, 1), (-1, -3), colors.beige),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),    # 第一列左對齊
            ('ALIGN', (1, 1), (1, -1), 'CENTER'),  # 第二列置中
            ('ALIGN', (2, 1), (2, -1), 'CENTER'),  # 第三列置中
            
            # 分隔行樣式 (index 10)
            ('BACKGROUND', (0, 10), (-1, 10), colors.lightgrey),
            ('LINEBELOW', (0, 10), (-1, 10), 1, colors.grey),
            
            # 總結行樣式 (index 11+)
            ('BACKGROUND', (0, 11), (-1, -1), colors.lightyellow),
            
            # 整體格線
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
        ]))
        
        story.append(table)
        story.append(Spacer(1, 25))
        
        return story
    
    def _build_status_chart(self, data: Dict[str, Any]) -> List:
        """Build status distribution pie chart"""
        story = []
        
        story.append(Paragraph("測試狀態分佈", self.styles['ChineseSubtitle']))
        
        # 使用 matplotlib 生成圓餅圖
        chart_image = self._create_pie_chart(
            data['status_distribution'],
            "測試狀態分佈",
            colors=['#28a745', '#dc3545', '#ffc107', '#6c757d', '#17a2b8']
        )
        
        if chart_image:
            story.append(chart_image)
        
        story.append(Spacer(1, 20))
        return story
    
    def _build_priority_chart(self, data: Dict[str, Any]) -> List:
        """Build priority distribution bar chart"""
        story = []
        
        story.append(Paragraph("優先級分佈", self.styles['ChineseSubtitle']))
        
        # 使用 matplotlib 生成長條圖
        chart_image = self._create_bar_chart(
            data['priority_distribution'],
            "優先級分佈",
            colors=['#dc3545', '#ffc107', '#28a745']  # 高、中、低
        )
        
        if chart_image:
            story.append(chart_image)
        
        story.append(Spacer(1, 20))
        return story
    
    def _build_results_table(self, data: Dict[str, Any]) -> List:
        """Build detailed test results table"""
        story = []
        
        if data['test_results']:
            story.append(Paragraph("詳細測試結果", self.styles['ChineseSubtitle']))
            
            # 建立表格標題
            table_data = [
                ['測試案例編號', '標題', '優先級', '狀態', '執行者', '執行時間']
            ]
            
            # 添加測試結果數據
            for result in data['test_results'][:50]:  # 限制最多50筆避免過長
                table_data.append([
                    result.get('test_case_number', ''),
                    result.get('title', '')[:40] + '...' if len(result.get('title', '')) > 40 else result.get('title', ''),
                    result.get('priority', ''),
                    result.get('status', ''),
                    result.get('executor', ''),
                    result.get('execution_time', '')
                ])
            
            table = Table(table_data, colWidths=[1.2*inch, 2.5*inch, 0.8*inch, 1*inch, 1*inch, 1.5*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, -1), self.chinese_font),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            
            story.append(table)
        
        return story
    
    def _build_footer(self) -> List:
        """Build report footer"""
        story = []
        story.append(Spacer(1, 30))
        
        footer_text = f"報告生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        story.append(Paragraph(footer_text, self.styles['ChineseNormal']))
        
        return story
    
    def _create_pie_chart(self, data: Dict[str, int], title: str, colors: List[str]) -> Optional[Image]:
        """Create pie chart using matplotlib and convert to ReportLab Image"""
        try:
            # 設定中文字型（如果可用）
            plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False
            
            # 準備數據
            labels = list(data.keys())
            sizes = list(data.values())
            
            # 過濾掉為 0 的數據
            filtered_data = [(label, size, color) for label, size, color in zip(labels, sizes, colors) if size > 0]
            if not filtered_data:
                return None
                
            labels, sizes, chart_colors = zip(*filtered_data)
            
            # 創建圖表
            fig, ax = plt.subplots(figsize=(6, 6))
            wedges, texts, autotexts = ax.pie(
                sizes, 
                labels=labels, 
                autopct='%1.1f%%',
                colors=chart_colors,
                startangle=90
            )
            
            ax.set_title(title, fontsize=14, fontweight='bold')
            plt.tight_layout()
            
            # 轉換為 ReportLab Image
            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='png', dpi=150, bbox_inches='tight')
            plt.close()
            
            img_buffer.seek(0)
            return Image(img_buffer, width=4*inch, height=4*inch)
            
        except Exception as e:
            print(f"Error creating pie chart: {e}")
            return None
    
    def _create_bar_chart(self, data: Dict[str, int], title: str, colors: List[str]) -> Optional[Image]:
        """Create bar chart using matplotlib and convert to ReportLab Image"""
        try:
            plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False
            
            labels = list(data.keys())
            values = list(data.values())
            
            if not values or all(v == 0 for v in values):
                return None
            
            fig, ax = plt.subplots(figsize=(6, 4))
            bars = ax.bar(labels, values, color=colors[:len(labels)])
            
            # 添加數值標籤
            for bar, value in zip(bars, values):
                height = bar.get_height()
                ax.annotate(f'{value}',
                           xy=(bar.get_x() + bar.get_width() / 2, height),
                           xytext=(0, 3),  # 3 points vertical offset
                           textcoords="offset points",
                           ha='center', va='bottom')
            
            ax.set_title(title, fontsize=14, fontweight='bold')
            ax.set_ylabel('數量')
            plt.tight_layout()
            
            # 轉換為 ReportLab Image
            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='png', dpi=150, bbox_inches='tight')
            plt.close()
            
            img_buffer.seek(0)
            return Image(img_buffer, width=5*inch, height=3*inch)
            
        except Exception as e:
            print(f"Error creating bar chart: {e}")
            return None
