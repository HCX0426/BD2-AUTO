"""自动任务模块

包含所有自动任务的实现，包括登录、邮件领取、每日任务等
"""
# 显式导入模块中的函数
from .daily_missions import daily_missions
from .get_email import get_email
from .get_guild import get_guild
from .get_pvp import get_pvp
from .get_restaurant import get_restaurant
from .intensive_decomposition import intensive_decomposition
from .login import login
from .lucky_draw import lucky_draw
from .map_collection import map_collection
from .pass_activity import pass_activity
from .pass_rewards import pass_rewards
from .sweep_daily import sweep_daily

# 明确导出列表
__all__ = ['login', 'get_email', 'get_restaurant', 'get_guild', 'sweep_daily', 'pass_rewards',
           'pass_activity', 'daily_missions', 'intensive_decomposition', 'lucky_draw', 'get_pvp', 'map_collection']
