"""
OCR语言配置文件
- 统一管理所有语言代码映射
- 定义各引擎的默认语言配置
- 处理语言代码转换逻辑
"""
from typing import Any, Dict, List

# 标准化的语言代码映射（主键为标准化代码）
LANGUAGE_CODE_MAP = {
    'chi_sim': {'name': '简体中文', 'easyocr': 'ch_sim', 'tesseract': 'chi_sim'},
    'chi_tra': {'name': '繁体中文', 'easyocr': 'ch_tra', 'tesseract': 'chi_tra'},
    'eng': {'name': '英文', 'easyocr': 'en', 'tesseract': 'eng'},
    'jpn': {'name': '日文', 'easyocr': 'ja', 'tesseract': 'jpn'}
}

# 各引擎的默认语言组合（使用标准化代码）
ENGINE_DEFAULT_LANGUAGES = {
    'tesseract': ['chi_sim', 'eng'],
    'easyocr': ['ch_sim', 'en']
}

# 语言强制组合规则（针对特定引擎）
LANGUAGE_COMBINATION_RULES = {
    'easyocr': {
        'ch_tra': ['ch_tra', 'en']  # 使用繁体时必须包含英文
    }
}

# 引擎基础配置
ENGINE_CONFIGS = {
    'tesseract': {
        'gpu': False,
        'timeout': 30,
        'preprocess': True
    },
    'easyocr': {
        'gpu': True,
        'timeout': 60,
        'model_storage': None
    }
}

# 图像预处理配置
PREPROCESS_CONFIG = {
    'denoise': {'h': 10},
    'clahe': {'clip_limit': 2.0, 'tile_size': (8, 8)},
    'threshold': {'block_size': 11, 'c': 2}
}

def get_default_languages(engine: str) -> str:
    """获取指定引擎的默认语言组合"""
    if engine not in ENGINE_DEFAULT_LANGUAGES:
        raise ValueError(f"Unsupported OCR engine: {engine}")
    return '+'.join(ENGINE_DEFAULT_LANGUAGES[engine])

def convert_lang_code(lang: str, engine: str) -> str:
    """将标准化语言代码转换为指定引擎的代码"""
    if lang not in LANGUAGE_CODE_MAP:
        return lang
    return LANGUAGE_CODE_MAP[lang].get(engine, lang)

def validate_lang_combination(langs: List[str], engine: str) -> List[str]:
    """验证并修正语言组合"""
    if engine not in LANGUAGE_COMBINATION_RULES:
        return langs
        
    required = []
    for lang in langs:
        if lang in LANGUAGE_COMBINATION_RULES[engine]:
            required.extend(LANGUAGE_COMBINATION_RULES[engine][lang])
    
    return list(dict.fromkeys(langs + required))  # 保持顺序并去重

def get_engine_config(engine: str) -> Dict[str, Any]:
    """获取引擎配置"""
    return ENGINE_CONFIGS.get(engine, {})