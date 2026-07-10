def make_validator(pattern: str):
    """Build a regex line-edit validator for the active Qt binding.

    Args:
        pattern: Regex pattern string. A QRegularExpression / QRegExp
            instance is also accepted; its pattern string is extracted so
            the right regex class can be rebuilt per binding (PySide2's
            QRegExpValidator cannot take a QRegularExpression).

    Returns:
        QRegularExpressionValidator (PySide6) or QRegExpValidator (PySide2).
    """
    if not isinstance(pattern, str):
        # QRegularExpression and QRegExp both expose .pattern()
        pattern = pattern.pattern()

    try:
        from PySide6.QtGui import QRegularExpressionValidator
        from PySide6.QtCore import QRegularExpression
        return QRegularExpressionValidator(QRegularExpression(pattern))
    except ImportError:
        from PySide2.QtGui import QRegExpValidator
        from PySide2.QtCore import QRegExp
        return QRegExpValidator(QRegExp(pattern))