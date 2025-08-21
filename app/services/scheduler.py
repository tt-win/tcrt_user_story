"""
定時任務管理器

負責管理各種定時任務，包括 TCG 資料同步
"""

import time
import threading
import logging
from typing import Dict, Any
from datetime import datetime, timedelta
from app.services.tcg_converter import tcg_converter


class TaskScheduler:
    """定時任務調度器"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.tasks = {}
        self.running = False
        self.scheduler_thread = None
    
    def start(self):
        """啟動調度器"""
        if self.running:
            return
            
        self.running = True
        
        # 註冊 TCG 同步任務（每 2 小時執行一次）
        self.register_task(
            name="tcg_sync",
            func=self._sync_tcg_task,
            interval_hours=2,
            run_immediately=True  # 啟動時立即執行一次
        )
        
        # 啟動調度線程
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.scheduler_thread.start()
        
        self.logger.info("定時任務調度器已啟動")
    
    def stop(self):
        """停止調度器"""
        self.running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        self.logger.info("定時任務調度器已停止")
    
    def register_task(self, name: str, func, interval_hours: float, run_immediately: bool = False):
        """
        註冊定時任務
        
        Args:
            name: 任務名稱
            func: 要執行的函數
            interval_hours: 執行間隔（小時）
            run_immediately: 是否立即執行一次
        """
        next_run = datetime.now()
        if not run_immediately:
            next_run += timedelta(hours=interval_hours)
            
        self.tasks[name] = {
            'func': func,
            'interval_hours': interval_hours,
            'next_run': next_run,
            'last_run': None,
            'run_count': 0,
            'error_count': 0,
            'last_error': None
        }
        
        self.logger.info(f"已註冊定時任務: {name}, 間隔: {interval_hours}小時, 下次執行: {next_run}")
    
    def _scheduler_loop(self):
        """調度主循環"""
        while self.running:
            try:
                current_time = datetime.now()
                
                for task_name, task_info in self.tasks.items():
                    if current_time >= task_info['next_run']:
                        self._execute_task(task_name, task_info)
                
                # 每分鐘檢查一次
                time.sleep(60)
                
            except Exception as e:
                self.logger.error(f"調度器循環異常: {e}")
                time.sleep(60)
    
    def _execute_task(self, task_name: str, task_info: Dict[str, Any]):
        """執行單個任務"""
        try:
            self.logger.info(f"開始執行定時任務: {task_name}")
            start_time = time.time()
            
            # 執行任務
            result = task_info['func']()
            
            # 更新任務狀態
            task_info['last_run'] = datetime.now()
            task_info['run_count'] += 1
            task_info['next_run'] = datetime.now() + timedelta(hours=task_info['interval_hours'])
            task_info['last_error'] = None
            
            execution_time = time.time() - start_time
            self.logger.info(
                f"定時任務 {task_name} 執行完成, 耗時: {execution_time:.2f}秒, "
                f"結果: {result}, 下次執行: {task_info['next_run']}"
            )
            
        except Exception as e:
            # 記錄錯誤
            task_info['error_count'] += 1
            task_info['last_error'] = str(e)
            task_info['next_run'] = datetime.now() + timedelta(hours=task_info['interval_hours'])
            
            self.logger.error(f"定時任務 {task_name} 執行失敗: {e}")
    
    def _sync_tcg_task(self) -> Dict[str, Any]:
        """TCG 同步任務"""
        try:
            sync_count = tcg_converter.sync_tcg_from_lark()
            return {
                'success': True,
                'sync_count': sync_count,
                'message': f'成功同步 {sync_count} 筆 TCG 資料'
            }
        except Exception as e:
            self.logger.error(f"TCG 同步任務失敗: {e}")
            return {
                'success': False,
                'sync_count': 0,
                'message': f'同步失敗: {str(e)}'
            }
    
    def get_task_status(self) -> Dict[str, Any]:
        """取得所有任務的狀態"""
        status = {
            'scheduler_running': self.running,
            'tasks': {}
        }
        
        for task_name, task_info in self.tasks.items():
            status['tasks'][task_name] = {
                'interval_hours': task_info['interval_hours'],
                'next_run': task_info['next_run'].isoformat() if task_info['next_run'] else None,
                'last_run': task_info['last_run'].isoformat() if task_info['last_run'] else None,
                'run_count': task_info['run_count'],
                'error_count': task_info['error_count'],
                'last_error': task_info['last_error']
            }
        
        return status
    
    def trigger_task(self, task_name: str) -> bool:
        """手動觸發任務執行"""
        if task_name not in self.tasks:
            return False
            
        task_info = self.tasks[task_name]
        self._execute_task(task_name, task_info)
        return True


# 全域調度器實例
task_scheduler = TaskScheduler()