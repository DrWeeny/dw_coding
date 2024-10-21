import time
from functools import wraps
import datetime


def timeIt(func):
    """
    Decorator to measure and print the execution time of a function in milliseconds.

    Args:
        func (function): The function to be wrapped.

    Returns:
        function: The wrapped function that prints its execution time after running.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()  # Start the timer
        result = func(*args, **kwargs)  # Execute the function
        end = time.time()  # End the timer

        elapsed = (end - start) * 1000  # Calculate elapsed time in milliseconds
        print(f'{func.__name__} took {elapsed:.4f} ms to execute.')
        return result

    return wrapper

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
        # Execute the wrapped function
        result = func(*args, **kwargs)

        # Get the current date and time
        t = datetime.datetime.now()

        # Print the function name and the current date and time
        print(f'# Function "{func.__name__}" finished on: {t:%d, %b %Y} at {t:%H:%M:%S}')
        return result

    return wrapper