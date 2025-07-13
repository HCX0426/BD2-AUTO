import io
import sys
import time
import random
from auto import Auto

# 设置UTF-8编码输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def run():
    """游戏自动化主函数"""
    sys.stdout.flush()
    
    # 创建Auto实例
    auto = Auto()
    
    # 添加设备
    auto.add_device("Windows:///?title_re=BrownDust II")
    
    # 启动系统
    auto.start()
    print("="*50)
    print("游戏自动化系统已启动")
    print("="*50)
    
    try:
        # ==================== 示例1: 基本任务操作 ====================
        print("\n[示例1] 基本任务操作")
        
        # 添加点击任务（相对坐标）
        click_task = auto.add_click_task((0.5, 0.5), is_relative=True)
        task_id = auto.get_task_id(click_task)
        print(f"已创建点击任务 (ID: {task_id}) - 点击屏幕中心")
        
        # 添加按键任务
        key_task = auto.add_key_task('a', duration=0.2)
        key_task_id = auto.get_task_id(key_task)
        print(f"已创建按键任务 (ID: {key_task_id}) - 按下A键")
        
        # 添加等待任务
        wait_task = auto.add_wait_task(1.0)
        wait_task_id = auto.get_task_id(wait_task)
        print(f"已创建等待任务 (ID: {wait_task_id}) - 等待1秒")
        
        # 等待所有任务完成
        auto.wait(timeout=5)
        print("所有基本任务已完成")
        
        # ==================== 示例2: 链式调用 ====================
        print("\n[示例2] 链式调用")
        
        # 创建一个链式任务序列
        (auto.add_click_task((0.3, 0.4), is_relative=True)
         .then(lambda res: print("点击了游戏界面左上角区域"))
         .add_key_task('enter', duration=0.1)
         .then(lambda _: print("按下了Enter键"))
         .add_wait_task(0.5)
         .add_click_task((0.7, 0.8), is_relative=True)
         .then(lambda _: print("点击了游戏界面右下角区域"))
         .catch(lambda e: print(f"链式任务出错: {e}"))
         .wait(timeout=10)
        )
        print("链式任务序列执行完成")
        
        # ==================== 示例3: 严格顺序任务链 ====================
        print("\n[示例3] 严格顺序任务链")
        
        # 创建任务函数
        def custom_action():
            """自定义游戏操作"""
            print("执行自定义游戏操作...")
            # 模拟一个可能失败的操作
            return random.choice([True, False])  # 50%成功几率
            
        # 创建任务链
        task1 = auto.create_click_task((0.2, 0.3), is_relative=True)
        task2 = auto.create_wait_task(0.2)
        task3 = auto.create_key_task('space')
        task4 = auto.create_custom_task(custom_action)
        
        # 执行严格顺序的任务链
        if auto.strict_sequence(task1, task2, task3, task4, timeout=15):
            print("任务链执行成功: 完成了一系列游戏操作")
        else:
            print(f"任务链失败: {auto.last_error}")
        
        # ==================== 示例4: 任务管理与取消 ====================
        print("\n[示例4] 任务管理与取消")
        
        # 添加一个长时间等待任务
        long_wait = auto.add_wait_task(20.0)
        long_wait_id = auto.get_task_id(long_wait)
        print(f"已创建长时间等待任务 (ID: {long_wait_id})")
        
        # 添加一个需要取消的任务
        cancel_task = auto.add_key_task('esc', delay=3.0)
        cancel_task_id = auto.get_task_id(cancel_task)
        print(f"已创建需要取消的任务 (ID: {cancel_task_id})")
        
        # 在另一个线程中等待2秒后取消任务
        def cancel_delayed():
            time.sleep(2)
            if auto.cancel_task(long_wait_id):
                print(f"成功取消了长时间等待任务 (ID: {long_wait_id})")
            if auto.cancel_task(cancel_task_id):
                print(f"成功取消了按键任务 (ID: {cancel_task_id})")
                
        import threading
        threading.Thread(target=cancel_delayed, daemon=True).start()
        
        # 等待所有任务完成（包括取消）
        auto.wait(timeout=5)
        print("任务管理示例完成")
        
        # ==================== 示例5: 复杂任务链组合 ====================
        print("\n[示例5] 复杂任务链组合")
        
        # 创建子任务链
        def create_battle_sequence():
            """创建战斗序列任务链"""
            return (
                auto.add_key_task('1')
                .add_wait_task(0.3)
                .add_key_task('2')
                .add_wait_task(0.3)
                .add_key_task('3')
            )
        
        # 主任务链
        (auto.add_click_task((0.5, 0.9), is_relative=True)  # 点击开始战斗按钮
         .then(lambda _: print("进入战斗场景"))
         .add_wait_task(1.0)  # 等待加载
         .then(create_battle_sequence)  # 执行战斗序列
         .add_wait_task(2.0)  # 等待战斗结束
         .add_click_task((0.1, 0.1), is_relative=True)  # 点击返回按钮
         .then(lambda _: print("战斗结束，返回主界面"))
         .catch(lambda e: print(f"战斗流程出错: {e}"))
         .wait(timeout=30)
        )
        print("复杂任务链组合执行完成")
        
        # ==================== 示例6: 错误处理与重试 ====================
        print("\n[示例6] 错误处理与重试")
        
        # 创建可能失败的任务
        def unreliable_action():
            """可能失败的游戏操作"""
            print("执行不可靠操作...")
            if random.random() < 0.7:  # 70%失败率
                raise Exception("操作失败: 游戏未响应")
            return True
        
        # 带重试机制的任务链
        max_retries = 3
        for attempt in range(max_retries):
            print(f"\n尝试 {attempt+1}/{max_retries}")
            try:
                (auto.add_custom_task(unreliable_action)
                 .wait(timeout=2)
                )
                print("操作成功!")
                break
            except Exception as e:
                print(f"尝试失败: {e}")
                if attempt < max_retries - 1:
                    print("等待2秒后重试...")
                    auto.add_wait_task(2.0).wait()
        else:
            print("操作失败，达到最大重试次数")
        
    except Exception as e:
        print(f"自动化执行发生严重错误: {e}")
    finally:
        # 停止自动化系统
        auto.stop()
        print("="*50)
        print("游戏自动化系统已停止")
        print("="*50)
        
        # 保持主线程运行
        try:
            while True:
                time.sleep(1)
                sys.stdout.flush()
        except KeyboardInterrupt:
            print("程序已退出")

if __name__ == "__main__":
    print("="*50)
    print("BrownDust II 任务链控制案例")
    print("="*50)
    print("本案例展示了以下任务链功能：")
    print("1. 基本任务操作（点击、按键、等待）")
    print("2. 链式调用（then/catch/wait）")
    print("3. 严格顺序任务链")
    print("4. 任务管理与取消")
    print("5. 复杂任务链组合")
    print("6. 错误处理与重试机制")
    print("="*50)
    run()