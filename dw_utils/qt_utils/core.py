def make_validator(pattern: str):
    try:
        from PySide6.QtGui import QRegularExpressionValidator
        from PySide6.QtCore import QRegularExpression
        return QRegularExpressionValidator(QRegularExpression(pattern))
    except ImportError:
        from PySide2.QtGui import QRegExpValidator
        from PySide2.QtCore import QRegExp
        return QRegExpValidator(QRegExp(pattern))