import re

SHAPE_PATTERN = re.compile(r'[Ss]hape(\d+)?$')
COMPONENT_PATTERN = re.compile("^([a-zA-Z0-9_:|]+)\.(f|e|vtx)\[(\d{1,}):?(\d{1,})?\]")
COMPOUND_PATTERN = re.compile(r'\[(\d+)?:(\d+)?\]')