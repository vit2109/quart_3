import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from .config import settings

def setup_logging():
    """Настройка логирования для приложения"""
    
    # Создаем директорию для логов если её нет
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Настройка форматирования
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    # Корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    
    # Очищаем существующие хендлеры
    root_logger.handlers.clear()
    
    # Консольный хендлер
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    console_formatter = logging.Formatter(log_format, date_format)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # В EXE журнал обязателен: консоль может быть закрыта, а диагностическое
    # сообщение индексации иначе будет потеряно.
    log_file = settings.LOG_FILE
    if getattr(sys, "frozen", False) and not log_file:
        log_file = str(log_dir / "app.log")
    if log_file:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10_485_760,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter(log_format, date_format)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    
    # Настройка логгеров для сторонних библиотек
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.orm").setLevel(logging.WARNING)
    
    # Создаем логгер для приложения
    logger = logging.getLogger("app")
    logger.info(f"Logging configured with level: {settings.LOG_LEVEL}")
    
    return logger

# Создаем экземпляр логгера для использования в других модулях
logger = logging.getLogger("app")
