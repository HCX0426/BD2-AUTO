import threading
import time
from queue import Queue, Empty
import traceback

class TaskExecutor:
    def __init__(self, max_workers=3):
        self.task_queue = Queue()
        self.workers = []
        self.max_workers = max_workers
        self.running = False
        self.pause_flag = threading.Event()
        
    def add_task(self, task_func, *args, **kwargs):
        """添加任务到队列"""
        self.task_queue.put((task_func, args, kwargs))
        
    def start(self):
        """启动任务执行器"""
        if self.running:
            return
            
        self.running = True
        self.pause_flag.clear()
        
        # 创建工作线程
        for i in range(self.max_workers):
            worker = threading.Thread(target=self._worker_loop, daemon=True)
            worker.start()
            self.workers.append(worker)
            
    def stop(self):
        """停止任务执行器"""
        self.running = False
        for worker in self.workers:
            if worker.is_alive():
                worker.join(timeout=2.0)
                
    def pause(self):
        """暂停任务执行"""
        self.pause_flag.set()
        
    def resume(self):
        """恢复任务执行"""
        self.pause_flag.clear()
        
    def _worker_loop(self):
        """工作线程循环"""
        while self.running:
            # 检查暂停状态
            if self.pause_flag.is_set():
                time.sleep(0.5)
                continue
                
            try:
                # 从队列获取任务
                task_func, args, kwargs = self.task_queue.get(timeout=1)
                
                # 执行任务
                try:
                    task_func(*args, **kwargs)
                except Exception as e:
                    print(f"任务执行失败: {str(e)}")
                    traceback.print_exc()
                    
                # 标记任务完成
                self.task_queue.task_done()
                
            except Empty:
                continue
                
    def wait_all_tasks(self, timeout=None):
        """等待所有任务完成"""
        self.task_queue.join(timeout=timeout)
        
    def get_queue_size(self):
        """获取队列中待处理任务数量"""
        return self.task_queue.qsize()