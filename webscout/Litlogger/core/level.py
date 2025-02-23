from enum import Enum

class LogLevel(Enum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50

    @staticmethod
    def get_level(level_str: str) -> 'LogLevel':
        try:
            return LogLevel[level_str.upper()]
        except KeyError:
            raise ValueError(f"Invalid log level: {level_str}")

    def __lt__(self, other):
        if isinstance(other, LogLevel):
            return self.value < other.value
        return NotImplemented
