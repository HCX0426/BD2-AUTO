import asyncio
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from queue import PriorityQueue
from typing import (
    Any,
    Callable,
    Coroutine,
    Optional,
    Tuple,
    TypeVar,
    Union,
)

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
        timeout: Optional[float] = 30,
    ):
        self.func = func
        self.priority = priority
        self.args = args or ()
        self.kwargs = kwargs or {}
        self.callback = callback
        self.timeout = timeout
        self._created_at = time.time()

    def __lt__(self, other: "Task") -> bool:
        """优先级比较，数值越小优先级越高"""
        if self.priority == other.priority:
            return self._created_at < other._created_at  # 相同优先级时，先创建的优先
        return self.priority < other.priority

    def adjust_priority(self, new_priority: int) -> None:
        """动态调整任务优先级"""
        self.priority = new_priority


class TaskExecutor:
    """任务执行器，支持同步/异步任务、优先级队列和动态优先级调整"""

    def __init__(self, max_workers: int = 3):
        self.input_queue: PriorityQueue[Task] = PriorityQueue()  # 输入队列
        self.output_queue: queue.Queue[Tuple[Optional[T], Optional[Exception], Optional[CallbackFunc]]] = queue.Queue()  # 输出队列
        self.workers: list[threading.Thread] = []
        self.max_workers = max_workers
        self.running = False
        self.pause_flag = threading.Event()
        self.lock = threading.Lock()
        self.io_executor = ThreadPoolExecutor(max_workers=2)  # IO线程池
        self.loop = asyncio.new_event_loop()  # 协程事件循环

    async def _async_task_wrapper(
        self, task_func: TaskFunc[T], *args: Any, timeout: Optional[float] = None, **kwargs: Any
    ) -> T:
        """协程任务包装器"""
        try:
            if asyncio.iscoroutinefunction(task_func):
                return await asyncio.wait_for(task_func(*args, **kwargs), timeout=timeout)
            else:
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
                        print(f"[ERROR] 回调函数执行失败: {str(e)}")
                self.output_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[ERROR] 输出线程异常: {str(e)}")

    def _worker_loop(self) -> None:
        """工作线程循环"""
        while self.running:
            if self.pause_flag.is_set():
                time.sleep(0.5)
                continue

            try:
                task = self.input_queue.get(timeout=1)
                start_time = time.time()

                try:
                    # 协程任务处理
                    if asyncio.iscoroutinefunction(task.func) or any(
                        asyncio.iscoroutine(arg) for arg in task.args
                    ):
                        future = asyncio.run_coroutine_threadsafe(
                            self._async_task_wrapper(
                                task.func, *task.args, timeout=task.timeout, **task.kwargs
                            ),
                            self.loop,
                        )
                        result = future.result(timeout=task.timeout if task.timeout else None)
                    else:
                        # 普通线程任务处理
                        if task.timeout and task.timeout > 0:
                            exc_queue: queue.Queue[Exception] = queue.Queue()

                            def task_wrapper() -> Any:
                                try:
                                    return task.func(*task.args, **task.kwargs)
                                except Exception as e:
                                    exc_queue.put(e)
                                    raise

                            task_thread = threading.Thread(target=task_wrapper)
                            task_thread.start()
                            task_thread.join(timeout=task.timeout)

                            if task_thread.is_alive():
                                raise TimeoutError(f"任务执行超时 ({task.timeout}秒)")
                            if not exc_queue.empty():
                                raise exc_queue.get()
                            result = None
                        else:
                            result = task.func(*task.args, **task.kwargs)

                    # 将结果放入输出队列
                    if task.callback:
                        self.output_queue.put((result, None, task.callback))

                except Exception as e:
                    print(f"[ERROR] 任务执行失败: {str(e)}")
                    if task.callback:
                        self.output_queue.put((None, e, task.callback))

                finally:
                    self.input_queue.task_done()
                    print(f"[INFO] 任务完成, 耗时: {time.time()-start_time:.2f}秒")

            except queue.Empty:
                continue
            except Exception as e:
                print(f"[ERROR] 工作线程异常: {str(e)}")
                time.sleep(1)

    def add_task(
        self,
        task_func: TaskFunc[T],
        *args: Any,
        priority: int = 5,
        callback: Optional[CallbackFunc] = None,
        timeout: Optional[float] = 30,
        **kwargs: Any,
    ) -> None:
        """添加任务到队列"""
        with self.lock:
            task = Task(task_func, priority, args, kwargs, callback, timeout)
            self.input_queue.put(task)
            print(f"[INFO] 已添加任务: {task_func.__name__}, 优先级: {priority}")

    def adjust_task_priority(self, condition: Callable[[Task], bool], new_priority: int) -> None:
        """调整满足条件的任务的优先级"""
        with self.lock:
            # 临时存储队列中的任务
            temp_tasks = []
            while not self.input_queue.empty():
                task = self.input_queue.get()
                if condition(task):
                    task.adjust_priority(new_priority)
                    print(f"[INFO] 已调整任务优先级: {task.func.__name__} -> {new_priority}")
                temp_tasks.append(task)

            # 重新放回队列
            for task in temp_tasks:
                self.input_queue.put(task)

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

    def wait_all_tasks(self, timeout: Optional[float] = None) -> None:
        """等待所有任务完成"""
        self.input_queue.join(timeout=timeout)
        if timeout and not self.input_queue.empty():
            print("[WARNING] 等待任务超时")

    def get_queue_size(self) -> int:
        """获取队列中待处理任务数量"""
        return self.input_queue.qsize()
