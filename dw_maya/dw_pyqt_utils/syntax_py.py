#!/usr/bin/env python
#----------------------------------------------------------------------------#
#------------------------------------------------------------------ HEADER --#

"""
@author:
    abtidona

@description:
    this is a description

@applications:
    - groom
    - cfx
    - fur
"""

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- IMPORTS --#

# built-in
import sys, os, re

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

# built-in
import re

# Maya and PySide6 imports
from maya import cmds, mel
from PySide6 import QtWidgets, QtCore, QtGui


#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#
def format_qt(color, style=''):
    """Return a QTextCharFormat with the given attributes."""
    _color = QtGui.QColor(color) if isinstance(color, (str, QtGui.QColor)) else QtGui.QColor(*color)
    _format = QtGui.QTextCharFormat()
    _format.setForeground(_color)
    if 'bold' in style:
        _format.setFontWeight(QtGui.QFont.Weight.Bold)
    if 'italic' in style:
        _format.setFontItalic(True)
    return _format

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- GLOBALS --#
# Syntax styles that can be shared by all languages
STYLES = {
    'keyword': format_qt(QtGui.QColor(255, 25, 30)),
    'operator': format_qt('red'),
    'brace': format_qt('darkGray'),
    'defclass': format_qt('black', 'bold'),
    'string': format_qt('magenta'),
    'string2': format_qt('darkMagenta'),
    'comment': format_qt('darkGreen', 'italic'),
    'self': format_qt('black', 'italic'),
    'numbers': format_qt('brown'),
}

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

class PythonHighlighter(QtGui.QSyntaxHighlighter):
    """Syntax highlighter for the Python language.
    """
    # Python keywords
    keywords = [
        'and', 'assert', 'break', 'class', 'continue', 'def', 'del', 'elif',
        'else', 'except', 'exec', 'finally', 'for', 'from', 'global', 'if',
        'import', 'in', 'is', 'lambda', 'not', 'or', 'pass', 'print', 'raise',
        'return', 'try', 'while', 'yield', 'None', 'True', 'False'
    ]

    operators = [
        '=', '==', '!=', '<', '<=', '>', '>=', r'\+', '-', r'\*', '/', '//',
        '%', r'\*\*', r'\+=', '-=', r'\*=', '/=', '%=', r'\^', r'\|', r'\&', '~',
        '>>', '<<'
    ]

    braces = [r'\{', r'\}', r'\(', r'\)', r'\[', r'\]']

    def __init__(self, document):
        super().__init__(document)

        # syntax highlighting from this point onward
        self.tri_single = (QtCore.QRegularExpression(r"'''"), 1, STYLES['string2'])
        self.tri_double = (QtCore.QRegularExpression(r'"""'), 2, STYLES['string2'])

        # Define syntax highlighting rules
        self.rules = [
            (QtCore.QRegularExpression(r'\b' + keyword + r'\b'), 0, STYLES['keyword']) for keyword in self.keywords
        ] + [
            (QtCore.QRegularExpression(op), 0, STYLES['operator']) for op in self.operators
        ] + [
            (QtCore.QRegularExpression(brace), 0, STYLES['brace']) for brace in self.braces
        ] + [
            (QtCore.QRegularExpression(r'\bself\b'), 0, STYLES['self']),
            (QtCore.QRegularExpression(r'"[^"\\]*(\\.[^"\\]*)*"'), 0, STYLES['string']),
            (QtCore.QRegularExpression(r"'[^'\\]*(\\.[^'\\]*)*'"), 0, STYLES['string']),
            (QtCore.QRegularExpression(r'\bdef\b\s*(\w+)'), 1, STYLES['defclass']),
            (QtCore.QRegularExpression(r'\bclass\b\s*(\w+)'), 1, STYLES['defclass']),
            (QtCore.QRegularExpression(r'#[^\n]*'), 0, STYLES['comment']),
            (QtCore.QRegularExpression(r'\b[+-]?[0-9]+[lL]?\b'), 0, STYLES['numbers']),
            (QtCore.QRegularExpression(r'\b[+-]?0[xX][0-9A-Fa-f]+[lL]?\b'), 0, STYLES['numbers']),
            (QtCore.QRegularExpression(r'\b[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\b'), 0, STYLES['numbers']),
        ]

    def highlightBlock(self, text):
        """Apply syntax highlighting to the given block of text."""
        for pattern, group, style in self.rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                self.setFormat(match.capturedStart(group), match.capturedLength(group), style)

        self.setCurrentBlockState(0)
        if not self._match_multiline(text, *self.tri_single):
            self._match_multiline(text, *self.tri_double)


    def _match_multiline(self, text, delimiter, in_state, style):
        """Apply multi-line string formatting."""
        if self.previousBlockState() == in_state:
            start = 0
        else:
            start = delimiter.match(text).capturedStart() if delimiter.match(text).hasMatch() else -1

        while start >= 0:
            end_match = delimiter.match(text, start + 1)
            end = end_match.capturedStart() if end_match.hasMatch() else -1
            if end >= 0:
                length = end - start + end_match.capturedLength()
                self.setCurrentBlockState(0)
            else:
                self.setCurrentBlockState(in_state)
                length = len(text) - start
            self.setFormat(start, length, style)
            start = delimiter.match(text, start + length).capturedStart() if delimiter.match(text, start + length).hasMatch() else -1

        return self.currentBlockState() == in_state
