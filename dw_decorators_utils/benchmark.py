import time
import cProfile
import pstats
import io
from functools import wraps
import datetime
from typing import Any, Callable, TypeVar, Optional, List, Dict
from statistics import mean, median
from TechArtsSandbox.abi.abi_logger import get_logger

logger = get_logger()


# Type variable for generic function type
F = TypeVar('F', bound=Callable[..., Any])


class TimingStats:
    """Class to store and analyze function execution timing statistics."""

    def __init__(self, func_name: str):
        self.func_name = func_name
        self.executions: List[float] = []
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
    def stats(self) -> Dict[str, float]:
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
_timing_stats: Dict[str, TimingStats] = {}


def timeIt(track_stats: bool = False, log_level: str = 'debug') -> Callable:
    """
    Decorator to measure and log function execution time.

    Timing is skipped entirely if the logger level is above the requested
    ``log_level``, so there is zero overhead in production.

    Args:
        track_stats: Whether to track timing statistics across calls.
        log_level:   Logger level used to report the result.
                     ``'debug'`` (default) or ``'info'``.

    Examples:
        Basic usage without parameters::

            @timeIt
            def my_function():
                pass

        Usage with parameters (tracking disabled)::

            @timeIt()
            def my_function():
                pass

        Usage with stats tracking enabled::

            @timeIt(track_stats=True)
            def my_function():
                pass

            my_function()

            # Retrieve timing statistics after calls
            stats = get_timing_stats('my_function')
            print(stats)

        Always visible at INFO level::

            @timeIt(log_level='info')
            def my_function():
                pass
    """
    import logging
    _level_value = logging.DEBUG if log_level == 'debug' else logging.INFO
    _log_fn_name = log_level if log_level in ('debug', 'info') else 'debug'

    def decorator(func: Callable) -> Callable:
        if track_stats:
            stats = TimingStats(func.__name__)
            _timing_stats[func.__name__] = stats

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Skip all measurement if the logger won't emit at the requested level
            if not logger.isEnabledFor(_level_value):
                return func(*args, **kwargs)

            if track_stats:
                stats.start()

            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000

                if track_stats:
                    stats.stop()

                getattr(logger, _log_fn_name)(f'{func.__name__} took {elapsed:.4f} ms to execute.')
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


def profileIt(top_n: int = 20, sort_by: str = 'cumulative', log_level: str = 'debug') -> Callable:
    """
    Decorator that profiles a function using cProfile, logging a breakdown
    of time spent in each sub-function call.

    Profiling is skipped entirely if the logger level is above ``log_level``,
    so there is zero overhead in production.

    Args:
        top_n:      Number of top entries to display in the profiling report (default: 20).
        sort_by:    Column to sort results by. Options: ``'cumulative'``, ``'tottime'``,
                    ``'calls'``, ``'pcalls'``, ``'name'`` (default: ``'cumulative'``).
        log_level:  Logger level used to report the result.
                    ``'debug'`` (default) or ``'info'``.

    Examples:
        Basic usage — shows the top 20 sub-calls sorted by cumulative time::

            @profileIt
            def my_function():
                pass

        Show top 10 sub-calls sorted by total (self) time::

            @profileIt(top_n=10, sort_by='tottime')
            def my_function():
                pass

        Always visible at INFO level::

            @profileIt(log_level='info')
            def my_function():
                pass
    """
    import logging
    _level_value = logging.DEBUG if log_level == 'debug' else logging.INFO
    _log_fn_name = log_level if log_level in ('debug', 'info') else 'debug'

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Skip all profiling if the logger won't emit at the requested level
            if not logger.isEnabledFor(_level_value):
                return func(*args, **kwargs)

            profiler = cProfile.Profile()
            profiler.enable()
            try:
                result = func(*args, **kwargs)
            finally:
                profiler.disable()
                stream = io.StringIO()
                ps = pstats.Stats(profiler, stream=stream)
                ps.strip_dirs()
                ps.sort_stats(sort_by)
                ps.print_stats(top_n)
                report = stream.getvalue()
                getattr(logger, _log_fn_name)(
                    f'[profileIt] {func.__name__} sub-call breakdown '
                    f'(top {top_n}, sort={sort_by}):\n{report}'
                )
            return result

        return wrapper

    # Allow usage without parentheses: @profileIt
    if callable(top_n):
        f = top_n
        top_n = 20
        return decorator(f)

    return decorator

