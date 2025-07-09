import queue
import threading
import time
from queue import PriorityQueue


class TaskExecutor:
    def __init__(self, max_workers=3):
        self.task_queue = PriorityQueue()
        self.workers = []
        self.max_workers = max_workers
        self.running = False
        self.pause_flag = threading.Event()
        self.lock = threading.Lock()  # 添加线程锁

    def add_task(self, task_func, *args, priority=5, callback=None, timeout=30, **kwargs):
        """
        添加任务到队列
        :param priority: 优先级 (1-10, 1为最高)
        :param callback: 任务完成回调函数
        :param timeout: 任务超时时间(秒)
        """
        with self.lock:
            self.task_queue.put(
                (priority, task_func, args, kwargs, callback, timeout))

    def start(self):
        """启动任务执行器"""
        with self.lock:
            if self.running:
                return

            self.running = True
            self.pause_flag.clear()

            # 创建工作线程
            for i in range(self.max_workers):
                worker = threading.Thread(
                    target=self._worker_loop,
                    name=f"Worker-{i}",
                    daemon=True
                )
                worker.start()
                self.workers.append(worker)

    def stop(self):
        """停止任务执行器"""
        with self.lock:
            if not self.running:
                return

            self.running = False
            for worker in self.workers:
                if worker.is_alive():
                    worker.join(timeout=2.0)
            self.workers.clear()

    def pause(self):
        """暂停任务执行"""
        self.pause_flag.set()

    def resume(self):
        """恢复任务执行"""
        self.pause_flag.clear()

    def _worker_loop(self):
        """工作线程循环 - 支持优先级"""
        while self.running:
            if self.pause_flag.is_set():
                time.sleep(0.5)
                continue

            try:
                priority, task_func, args, kwargs, callback, timeout = self.task_queue.get(
                    timeout=1)

                # 使用线程池执行任务并设置超时
                result = None
                start_time = time.time()
                try:
                    if timeout > 0:
                        # 创建子线程执行任务并设置超时
                        def task_wrapper():
                            return task_func(*args, **kwargs)

                        task_thread = threading.Thread(target=task_wrapper)
                        task_thread.start()
                        task_thread.join(timeout=timeout)

                        if task_thread.is_alive():
                            raise TimeoutError(f"任务执行超时 ({timeout}秒)")
                    else:
                        result = task_func(*args, **kwargs)

                except Exception as e:
                    print(f"任务执行失败: {str(e)}")
                    if callback:
                        callback(None, e)
                else:
                    if callback:
                        callback(result, None)
                finally:
                    self.task_queue.task_done()
                    print(f"任务完成, 耗时: {time.time()-start_time:.2f}秒")

            except queue.Empty:
                pass
            except Exception as e:
                print(f"工作线程发生异常: {str(e)}")
                time.sleep(1)

    def wait_all_tasks(self, timeout=None):
        """等待所有任务完成"""
        self.task_queue.join(timeout=timeout)

    def get_queue_size(self):
        """获取队列中待处理任务数量"""
        return self.task_queue.qsize()


class Task:
    def __init__(self, func, priority=0, *args, **kwargs):
        self.func = func
        self.priority = priority
        self.args = args
        self.kwargs = kwargs

    def __lt__(self, other):
        return self.priority < other.priority

    def run(self):
        return self.func(*self.args, **self.kwargs)
