from typing import Optional, Any

class AppException(Exception):
    """Базовое исключение для приложения"""
    def __init__(self, message: str, status_code: int = 400, details: Optional[Any] = None):
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)

class AuthenticationError(AppException):
    """Ошибка аутентификации"""
    def __init__(self, message: str = "Authentication failed", details: Optional[Any] = None):
        super().__init__(message, status_code=401, details=details)

class AuthorizationError(AppException):
    """Ошибка авторизации"""
    def __init__(self, message: str = "Permission denied", details: Optional[Any] = None):
        super().__init__(message, status_code=403, details=details)

class NotFoundError(AppException):
    """Объект не найден"""
    def __init__(self, message: str = "Resource not found", details: Optional[Any] = None):
        super().__init__(message, status_code=404, details=details)

class ValidationError(AppException):
    """Ошибка валидации"""
    def __init__(self, message: str = "Validation error", details: Optional[Any] = None):
        super().__init__(message, status_code=422, details=details)

class DataLoadingError(AppException):
    """Ошибка загрузки данных"""
    def __init__(self, message: str = "Data loading failed", details: Optional[Any] = None):
        super().__init__(message, status_code=400, details=details)


class DuplicateError(AppException):
    """Дубликат ресурса (например, уже загруженный файл)"""
    def __init__(self, message: str = "Duplicate resource", details: Optional[Any] = None):
        super().__init__(message, status_code=409, details=details)

class AIError(AppException):
    """Ошибка AI модуля"""
    def __init__(self, message: str = "AI processing failed", details: Optional[Any] = None):
        super().__init__(message, status_code=503, details=details)
