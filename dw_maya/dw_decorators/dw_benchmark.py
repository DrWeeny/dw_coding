import time
from functools import wraps
import datetime
from pathlib import Path
from typing import Any, Callable, TypeVar, Optional
from statistics import mean, median
from dw_logger import get_logger


# Type variable for generic function type
F = TypeVar('F', bound=Callable[..., Any])


class TimingStats:
    """Class to store and analyze function execution timing statistics."""

    def __init__(self, func_name: str):
        self.func_name = func_name
        self.executions: list[float] = []
        self.start_time: Optional[float] = None

    def start(self) -> None:
        """Start timing an execution."""
        self.start_time = time.perf_counter()

    def stop(self) -> float:
        """Stop timing and record the execution time."""
        if self.start_time is None:
            raise RuntimeError("Timer was not started")

        duration = (time.perf_counter() - self.start_time) * 1000  # ms
        self.executions.append(duration)
        self.start_time = None
        return duration

    @property
    def stats(self) -> dict[str, float]:
        """Calculate timing statistics."""
        if not self.executions:
            return {}

        return {
            'last': self.executions[-1],
            'min': min(self.executions),
            'max': max(self.executions),
            'mean': mean(self.executions),
            'median': median(self.executions),
            'count': len(self.executions)
        }

    def __enter__(self) -> 'TimingStats':
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.stop()

    def clear(self) -> None:
        """Clear all timing statistics."""
        self.executions.clear()
        self.start_time = None

    def __str__(self) -> str:
        stats = self.stats
        if not stats:
            return f"No timing data for {self.func_name}"

        return (f"Function: {self.func_name}\n"
                f"Last execution: {stats['last']:.2f}ms\n"
                f"Min: {stats['min']:.2f}ms\n"
                f"Max: {stats['max']:.2f}ms\n"
                f"Mean: {stats['mean']:.2f}ms\n"
                f"Median: {stats['median']:.2f}ms\n"
                f"Total executions: {stats['count']}")


# Global dictionary to store timing statistics
_timing_stats: dict[str, TimingStats] = {}


def timeIt(track_stats: bool = False) -> Callable:
    """
    Decorator to measure and log function execution time.

    Args:
        track_stats: Whether to track timing statistics across calls
    """

    def decorator(func: Callable) -> Callable:
        if track_stats:
            stats = TimingStats(func.__name__)
            _timing_stats[func.__name__] = stats

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            logger = get_logger()

            if track_stats:
                stats.start()

            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000

                if track_stats:
                    stats.stop()

                logger.info(f'{func.__name__} took {elapsed:.4f} ms to execute.')
                return result
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                logger.error(
                    f'Error in {func.__name__} after {elapsed:.4f} ms: {str(e)}'
                )
                raise

        return wrapper

    # Handle case where decorator is used without parameters
    if callable(track_stats):
        f = track_stats
        track_stats = False
        return decorator(f)

    return decorator


def printDate(func):
    """
    Decorator to print the current date and time after a function has finished executing.

    Args:
        func (function): The function to wrap.

    Returns:
        function: The wrapped function with a date and time printout after execution.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        logger = get_logger()
        # Execute the wrapped function
        result = func(*args, **kwargs)

        # Get the current date and time
        t = datetime.datetime.now()

        # Print the function name and the current date and time
        logger.info(f'# Function "{func.__name__}" finished on: {t:%d, %b %Y} at {t:%H:%M:%S}')

        return result

    return wrapper



def get_timing_stats(func_name: str) -> Optional[TimingStats]:
    """Get timing statistics for a specific function."""
    return _timing_stats.get(func_name)
