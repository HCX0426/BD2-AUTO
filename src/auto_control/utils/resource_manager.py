import os
import shutil
import time
from typing import List, Optional

from src.auto_control.utils.logger import Logger


class ResourceManager:
    """
    统一资源管理器
    负责管理和清理自动化系统中的各种资源，包括：
    1. 调试图片
    2. 日志文件
    3. 缓存数据
    4. 临时文件
    
    支持调试模式下的自动清理，提供统一的资源清理接口
    """
    
    def __init__(self, logger: Logger, test_mode: bool = False, path_manager=None):
        """
        初始化资源管理器
        
        Args:
            logger: 日志器实例
            test_mode: 是否为测试模式
            path_manager: 路径管理器实例
        """
        self.logger = logger
        self.test_mode = test_mode
        self.path_manager = path_manager
        
        # 定义需要清理的资源目录
        self.resource_dirs = {
            "template_debug": path_manager.get("match_temple_debug") if path_manager else "",
            "ocr_debug": path_manager.get("match_ocr_debug") if path_manager else "",
            "log": path_manager.get("log") if path_manager else "",
            "cache": path_manager.get("cache") if path_manager else "",
        }
        
        # 记录资源清理时间
        self.last_cleanup_time = 0
        self.CLEANUP_INTERVAL = 3600  # 自动清理间隔（秒）
    
    def cleanup(self, resource_type: Optional[str] = None, force: bool = False) -> bool:
        """
        清理指定类型的资源
        
        Args:
            resource_type: 资源类型，可选值：template_debug, ocr_debug, log, cache, all
            force: 是否强制清理，忽略清理间隔
        
        Returns:
            bool: 清理是否成功
        """
        current_time = time.time()
        
        # 检查清理间隔
        if not force and current_time - self.last_cleanup_time < self.CLEANUP_INTERVAL:
            self.logger.debug(f"资源清理间隔未到，跳过清理")
            return True
        
        try:
            if resource_type == "all" or not resource_type:
                # 清理所有资源
                for rt in self.resource_dirs.keys():
                    self._cleanup_dir(self.resource_dirs[rt], rt)
            else:
                # 清理指定类型资源
                if resource_type in self.resource_dirs:
                    self._cleanup_dir(self.resource_dirs[resource_type], resource_type)
                else:
                    self.logger.warning(f"未知的资源类型: {resource_type}")
                    return False
            
            self.last_cleanup_time = current_time
            return True
        except Exception as e:
            self.logger.error(f"资源清理失败: {str(e)}", exc_info=True)
            return False
    
    def _cleanup_dir(self, dir_path: str, dir_type: str) -> None:
        """
        清理指定目录
        
        Args:
            dir_path: 目录路径
            dir_type: 目录类型
        """
        if not dir_path or not os.path.exists(dir_path):
            return
        
        try:
            self.logger.debug(f"开始清理{dir_type}目录: {dir_path}")
            
            if dir_type == "template_debug" or dir_type == "ocr_debug":
                # 清理调试图片（仅PNG文件）
                self._cleanup_debug_images(dir_path, dir_type)
            elif dir_type == "cache":
                # 清理缓存文件
                self._cleanup_cache(dir_path)
            elif dir_type == "log":
                # 清理旧日志（由Logger类自行处理）
                self.logger.debug(f"日志清理由Logger类自行处理，跳过")
            
        except Exception as e:
            self.logger.error(f"清理{dir_type}目录失败: {str(e)}", exc_info=True)
    
    def _cleanup_debug_images(self, dir_path: str, dir_type: str) -> None:
        """
        清理调试图片
        
        Args:
            dir_path: 调试目录路径
            dir_type: 目录类型
        """
        try:
            total_count = 0
            deleted_count = 0
            failed_files = []
            
            for filename in os.listdir(dir_path):
                file_path = os.path.join(dir_path, filename)
                if not os.path.isfile(file_path):
                    continue
                
                # 只清理PNG文件
                if filename.lower().endswith(".png"):
                    total_count += 1
                    try:
                        os.remove(file_path)
                        deleted_count += 1
                    except PermissionError:
                        failed_files.append(f"{filename}（权限不足）")
                    except Exception as e:
                        failed_files.append(f"{filename}（错误：{str(e)}）")
            
            log_msg = (
                f"清理{dir_type}目录完成 | "
                f"目录: {dir_path} | "
                f"总文件数: {total_count} | "
                f"成功删除: {deleted_count} | "
                f"删除失败: {len(failed_files)}"
            )
            if failed_files:
                log_msg += f" | 失败文件: {failed_files}"
            self.logger.info(log_msg)
            
        except Exception as e:
            self.logger.error(f"清理{dir_type}目录异常: {str(e)}", exc_info=True)
    
    def _cleanup_cache(self, dir_path: str) -> None:
        """
        清理缓存文件
        
        Args:
            dir_path: 缓存目录路径
        """
        try:
            total_count = 0
            deleted_count = 0
            failed_files = []
            
            for filename in os.listdir(dir_path):
                file_path = os.path.join(dir_path, filename)
                if os.path.isfile(file_path):
                    total_count += 1
                    try:
                        # 检查文件修改时间，清理超过7天的缓存
                        if time.time() - os.path.getmtime(file_path) > 7 * 24 * 3600:
                            os.remove(file_path)
                            deleted_count += 1
                    except PermissionError:
                        failed_files.append(f"{filename}（权限不足）")
                    except Exception as e:
                        failed_files.append(f"{filename}（错误：{str(e)}）")
                elif os.path.isdir(file_path):
                    # 递归清理子目录
                    self._cleanup_cache(file_path)
            
            log_msg = (
                f"清理缓存目录完成 | "
                f"目录: {dir_path} | "
                f"总文件数: {total_count} | "
                f"成功删除: {deleted_count} | "
                f"删除失败: {len(failed_files)}"
            )
            if failed_files:
                log_msg += f" | 失败文件: {failed_files}"
            self.logger.info(log_msg)
            
        except Exception as e:
            self.logger.error(f"清理缓存目录异常: {str(e)}", exc_info=True)
    
    def cleanup_on_start(self) -> None:
        """
        系统启动时的资源清理
        """
        self.logger.info("系统启动，开始清理资源...")
        
        # 测试模式下清理所有调试资源
        if self.test_mode:
            self.logger.info("测试模式：清理所有调试资源")
            self.cleanup("template_debug", force=True)
            self.cleanup("ocr_debug", force=True)
        
        # 定期清理缓存
        self.cleanup("cache", force=True)
    
    def cleanup_on_stop(self) -> None:
        """
        系统停止时的资源清理
        """
        self.logger.info("系统停止，开始清理资源...")
        
        # 测试模式下清理所有调试资源
        if self.test_mode:
            self.cleanup("template_debug", force=True)
            self.cleanup("ocr_debug", force=True)
        
        # 清理缓存
        self.cleanup("cache", force=True)
    
    def register_resource_dir(self, name: str, path: str) -> None:
        """
        注册资源目录
        
        Args:
            name: 目录名称
            path: 目录路径
        """
        self.resource_dirs[name] = path
    
    def get_resource_stats(self) -> dict:
        """
        获取资源统计信息
        
        Returns:
            dict: 资源统计信息
        """
        stats = {}
        for name, path in self.resource_dirs.items():
            if path and os.path.exists(path):
                stats[name] = {
                    "path": path,
                    "files": len([f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]),
                    "size": self._get_dir_size(path),
                }
        return stats
    
    def _get_dir_size(self, dir_path: str) -> int:
        """
        获取目录大小
        
        Args:
            dir_path: 目录路径
        
        Returns:
            int: 目录大小（字节）
        """
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(dir_path):
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(file_path)
                except (OSError, PermissionError):
                    continue
        return total_size
