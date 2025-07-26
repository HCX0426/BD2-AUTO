import asyncio
import queue
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from queue import PriorityQueue
from typing import Any, Callable, Coroutine, Optional, Tuple, TypeVar, Union

from .config.control__config import *
T = TypeVar("T")
TaskFunc = Union[Callable[..., T], Callable[..., Coroutine[Any, Any, T]]]
CallbackFunc = Callable[[Optional[T], Optional[Exception]], None]


class Task:
    """任务类，封装任务信息和执行逻辑"""

    def __init__(
        self,
        func: TaskFunc[T],
        priority: int = 5,
        args: Optional[Tuple] = None,
        kwargs: Optional[dict] = None,
        callback: Optional[CallbackFunc] = None,
        timeout: Optional[float] = DEFAULT_TASK_TIMEOUT,
        future: Optional[Future] = None,
    ):
        # 使用 dataclass 来简化初始化
        self.id = str(uuid.uuid4())
        self.func = func
        self.priority = max(0, min(10, priority))  # 限制优先级范围 0-10
        self.args = tuple(args or ())  # 确保是元组类型
        self.kwargs = dict(kwargs or {})  # 确保是字典类型
        self.callback = callback
        self.timeout = timeout or DEFAULT_TASK_TIMEOUT # 确保timeout非负
        self.future = future or Future()
        self._created_at = time.monotonic()  # 使用 monotonic 更准确

    def __lt__(self, other: "Task") -> bool:
        if not isinstance(other, Task):
            return NotImplemented
        return (self.priority, self._created_at) < (other.priority, other._created_at)

    def adjust_priority(self, new_priority: int) -> None:
        """动态调整任务优先级"""
        self.priority = new_priority

    def get_id(self) -> str:
        """获取任务ID"""
        return self.id


class TaskExecutor:
    """任务执行器，支持同步/异步任务、优先级队列和动态优先级调整"""

    def __init__(self, max_workers: int = 3):
        self.input_queue = PriorityQueue()  # 输入队列（优先级队列）
        self.output_queue = queue.Queue()  # 输出队列（处理回调）
        self.workers = []  # 工作线程列表
        self.max_workers = max_workers
        self.running = False
        self.pause_flag = threading.Event()
        self.lock = threading.Lock()
        self.io_executor = ThreadPoolExecutor(max_workers=2)
        self.loop = asyncio.new_event_loop()
        self.task_registry = {}  # 任务注册表

    async def _async_task_wrapper(
        self,
        task_func: TaskFunc[T],
        *args: Any,
        timeout: Optional[float] = None,
        **kwargs: Any
    ) -> T:
        """协程任务包装器"""
        try:
            if asyncio.iscoroutinefunction(task_func):
                return await asyncio.wait_for(task_func(*args, **kwargs), timeout=timeout)
            return await self.loop.run_in_executor(
                None,
                lambda: task_func(*args, **kwargs),
            )
        except Exception as e:
            raise e

    def _output_worker(self) -> None:
        """输出线程处理回调"""
        while self.running:
            try:
                result, error, callback = self.output_queue.get(timeout=1)
                if callback:
                    try:
                        callback(result, error)
                    except Exception as e:
                        print(f"[ERROR] 回调执行失败: {str(e)}")
                self.output_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[ERROR] 输出线程异常: {str(e)}")

    def _execute_task(self, task: Task) -> Any:
        """优化任务执行逻辑"""
        # 使用 contextmanager 处理超时
        from contextlib import contextmanager
        
        @contextmanager
        def timeout_handler(seconds: Optional[float]):
            if not seconds:
                yield
                return
                
            def timeout_callback():
                raise TimeoutError(f"任务执行超时 ({seconds}秒)")
                
            timer = threading.Timer(seconds, timeout_callback)
            timer.start()
            try:
                yield
            finally:
                timer.cancel()

        try:
            with timeout_handler(task.timeout):
                # 协程任务处理
                if asyncio.iscoroutinefunction(task.func):
                    return asyncio.run_coroutine_threadsafe(
                        self._async_task_wrapper(
                            task.func, *task.args, **task.kwargs
                        ),
                        self.loop
                    ).result(timeout=task.timeout)
                    
                # 普通任务处理
                return task.func(*task.args, **task.kwargs)
                
        except Exception as e:
            print(f"[ERROR] 任务执行失败: {str(e)}")
            raise

    def _set_task_result(self, task: Task, result: Any) -> None:
        """设置任务结果"""
        if not task.future.done():
            task.future.set_result(result)
        if task.callback:
            self.output_queue.put((result, None, task.callback))

    def _set_task_exception(self, task: Task, e: Exception) -> None:
        """设置任务异常"""
        if not task.future.done():
            task.future.set_exception(e)
        print(f"[ERROR] 任务执行失败: {str(e)}")
        if task.callback:
            self.output_queue.put((None, e, task.callback))

    def _cleanup_task(self, task: Task, start_time: float) -> None:
        """清理任务资源"""
        self.input_queue.task_done()
        with self.lock:
            if task.id in self.task_registry:
                del self.task_registry[task.id]
        duration = time.monotonic() - start_time
        print(f"[INFO] 任务完成, 耗时: {duration:.2f}秒")

    def _worker_loop(self) -> None:
        """优化工作线程循环"""
        while self.running:
            if self.pause_flag.is_set():
                time.sleep(0.1)  # 减少睡眠时间提高响应性
                continue

            try:
                # 使用带超时的获取,避免阻塞
                try:
                    task = self.input_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                    
                start_time = time.monotonic()
                task_name = task.func.__name__
                
                print(f"[DEBUG] 开始执行任务: {task_name} (ID: {task.id})")
                
                try:
                    result = self._execute_task(task)
                    self._set_task_result(task, result)
                    print(f"[DEBUG] 任务完成: {task_name}")
                except Exception as e:
                    self._set_task_exception(task, e)
                    print(f"[ERROR] 任务失败: {task_name} - {str(e)}")
                finally:
                    self._cleanup_task(task, start_time)
                    
            except Exception as e:
                print(f"[ERROR] 工作线程异常: {str(e)}")
                time.sleep(0.1)  # 避免异常情况下的快速循环

    def add_task(
        self,
        task_func: TaskFunc[T],
        *args: Any,
        priority: int = 5,
        callback: Optional[CallbackFunc] = None,
        timeout: Optional[float] = 30,
        **kwargs: Any,
    ) -> Task:
        """添加任务到队列并返回Task对象"""
        with self.lock:
            future = Future()
            task = Task(
                task_func,
                priority,
                args,
                kwargs,
                callback,
                timeout,
                future
            )
            self.input_queue.put(task)
            self.task_registry[task.id] = task
            print(
                f"[INFO] 已添加任务: {task_func.__name__}, 优先级: {priority}, 任务ID: {task.id}")
            return task  # 返回Task对象

    def adjust_task_priority(self, task_id: str, new_priority: int) -> bool:
        """调整指定任务的优先级"""
        with self.lock:
            if task_id not in self.task_registry:
                return False

            task = self.task_registry[task_id]
            task.adjust_priority(new_priority)

            # 重新排序队列
            temp_tasks = []
            while not self.input_queue.empty():
                temp_task = self.input_queue.get()
                if temp_task.id == task_id:
                    temp_tasks.append(task)  # 使用更新后的任务
                else:
                    temp_tasks.append(temp_task)

            for temp_task in temp_tasks:
                self.input_queue.put(temp_task)

            print(f"[INFO] 已调整任务优先级: {task_id} -> {new_priority}")
            return True

    def cancel_task(self, task_id: str) -> bool:
        """取消指定任务"""
        with self.lock:
            if task_id not in self.task_registry:
                return False

            task = self.task_registry[task_id]
            if not task.future.done():
                task.future.cancel()

            # 从队列中移除任务
            temp_tasks = []
            while not self.input_queue.empty():
                temp_task = self.input_queue.get()
                if temp_task.id != task_id:
                    temp_tasks.append(temp_task)

            for temp_task in temp_tasks:
                self.input_queue.put(temp_task)

            del self.task_registry[task_id]
            print(f"[INFO] 已取消任务: {task_id}")
            return True

    def start(self) -> None:
        """启动执行器"""
        with self.lock:
            if self.running:
                print("[WARNING] 执行器已经在运行中")
                return

            self.running = True
            self.pause_flag.clear()

            # 启动协程事件循环线程
            def run_loop() -> None:
                asyncio.set_event_loop(self.loop)
                self.loop.run_forever()

            loop_thread = threading.Thread(target=run_loop, daemon=True)
            loop_thread.start()

            # 启动输出线程
            output_thread = threading.Thread(
                target=self._output_worker,
                name="OutputWorker",
                daemon=True,
            )
            output_thread.start()

            # 创建工作线程
            for i in range(self.max_workers):
                worker = threading.Thread(
                    target=self._worker_loop,
                    name=f"Worker-{i}",
                    daemon=True,
                )
                worker.start()
                self.workers.append(worker)
            print(f"[INFO] 已启动执行器, 工作线程数: {self.max_workers}")

    def stop(self) -> None:
        """停止任务执行器"""
        with self.lock:
            if not self.running:
                print("[WARNING] 执行器未运行")
                return

            print("[INFO] 正在停止执行器...")
            self.running = False

            # 停止事件循环
            self.loop.call_soon_threadsafe(self.loop.stop)

            # 关闭线程池
            self.io_executor.shutdown(wait=False)

            # 取消所有未完成任务
            for task_id in list(self.task_registry.keys()):
                self.cancel_task(task_id)

            # 等待工作线程结束
            for worker in self.workers:
                if worker.is_alive():
                    worker.join(timeout=2.0)
            self.workers.clear()
            print("[INFO] 执行器已停止")

    def pause(self) -> None:
        """暂停任务执行"""
        self.pause_flag.set()
        print("[INFO] 执行器已暂停")

    def resume(self) -> None:
        """恢复任务执行"""
        self.pause_flag.clear()
        print("[INFO] 执行器已恢复")

    def wait_all_tasks(self, timeout: Optional[float] = None) -> bool:
        """等待所有任务完成"""
        start_time = time.time()
        while not self.input_queue.empty():
            if timeout and (time.time() - start_time) > timeout:
                print("[WARNING] 等待任务超时")
                return False
            time.sleep(0.1)
        return True

    def get_queue_size(self) -> int:
        """获取队列中待处理任务数量"""
        return self.input_queue.qsize()
