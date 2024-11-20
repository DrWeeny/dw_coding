import re

SHAPE_PATTERN = re.compile(r'[Ss]hape(\d+)?$')
COMPOUND_PATTERN = re.compile(r'\[(\d+)?:(\d+)?\]')