from typing import Any, Optional, TypeVar, Generic

T = TypeVar('T')


class Result(Generic[T]):
    """
    统一返回结果类，类似 Java 中的 Result 或 R
    用法：
        Result.success(data)
        Result.error("参数错误")
    """

    def __init__(self, code: int, message: str, data: Optional[T] = None):
        self.code = code
        self.message = message
        self.data = data

    @classmethod
    def success(cls, data: Optional[T] = None, message: str = "操作成功") -> "Result[T]":
        """成功响应"""
        return cls(200, message, data)

    @classmethod
    def error(cls, message: str = "操作失败", code: int = 400) -> "Result[T]":
        """失败响应"""
        return cls(code, message, None)

    @classmethod
    def unauthorized(cls, message: str = "未登录或登录已过期") -> "Result[T]":
        """401 未认证"""
        return cls(401, message, None)

    @classmethod
    def forbidden(cls, message: str = "无权限访问") -> "Result[T]":
        """403 无权限"""
        return cls(403, message, None)

    @classmethod
    def not_found(cls, message: str = "资源不存在") -> "Result[T]":
        """404 资源不存在"""
        return cls(404, message, None)

    def is_success(self) -> bool:
        """是否成功"""
        return 200 <= self.code < 300

    def to_dict(self) -> dict:
        """转为字典，用于 JSON 序列化"""
        return {
            "code": self.code,
            "message": self.message,
            "data": self.data
        }

    def __repr__(self) -> str:
        return f"Result(code={self.code}, message={self.message}, data={self.data})"