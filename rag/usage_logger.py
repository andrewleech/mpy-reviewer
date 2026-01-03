"""Usage logging for performance analysis."""

import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from contextlib import contextmanager

from .config import get_config


class UsageLogger:
    """Log CLI usage for performance analysis."""

    def __init__(self):
        config = get_config()
        self.log_dir = config.project_root / "logs"
        self.log_dir.mkdir(exist_ok=True)
        self.log_file = self.log_dir / "usage.jsonl"

    def log_operation(
        self,
        operation: str,
        params: Dict[str, Any],
        duration_ms: float,
        result_count: int,
        error: Optional[str] = None,
    ):
        """Log a single operation.

        Args:
            operation: Operation type (review, search, index, etc.)
            params: Operation parameters (query, filters, options)
            duration_ms: Operation duration in milliseconds
            result_count: Number of results returned
            error: Error message if operation failed
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "params": params,
            "duration_ms": round(duration_ms, 2),
            "result_count": result_count,
            "error": error,
        }

        # Append to JSONL file
        with open(self.log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

    @contextmanager
    def track_operation(self, operation: str, **params):
        """Context manager to track an operation's performance.

        Usage:
            logger = UsageLogger()
            with logger.track_operation("search", query="memory", domain="memory") as ctx:
                results = perform_search(...)
                ctx.set_result_count(len(results))
        """
        start = time.time()
        context = OperationContext()

        try:
            yield context
        except Exception as e:
            context.error = str(e)
            raise
        finally:
            duration_ms = (time.time() - start) * 1000
            self.log_operation(
                operation=operation,
                params=params,
                duration_ms=duration_ms,
                result_count=context.result_count,
                error=context.error,
            )


class OperationContext:
    """Context object for tracking operation results."""

    def __init__(self):
        self.result_count = 0
        self.error = None

    def set_result_count(self, count: int):
        """Set the number of results returned."""
        self.result_count = count

    def set_error(self, error: str):
        """Set an error message."""
        self.error = error


def get_logger() -> UsageLogger:
    """Get singleton usage logger."""
    if not hasattr(get_logger, "_instance"):
        get_logger._instance = UsageLogger()
    return get_logger._instance
