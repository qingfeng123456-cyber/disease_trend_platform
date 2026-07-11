from __future__ import annotations


class PlatformError(Exception):
    """平台业务异常基类。"""


class ConfigError(PlatformError):
    """配置缺失或格式错误。"""


class DataNotReadyError(PlatformError):
    """serving 层结果尚未生成。"""


class ValidationError(PlatformError):
    """用户输入参数不合法。"""
