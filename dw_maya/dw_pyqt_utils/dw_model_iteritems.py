
def iterItems(root):
    """
    used in PyQt to iterate all items under the root item
    :param root:
    :return:
    """
    def recurse(parent):
        for row in range(parent.rowCount()):
            for column in range(parent.columnCount()):
                child = parent.child(row, column)
                yield child
                if child.hasChildren():
                    yield from recurse(child)
    if root is not None:
        yield from recurse(root)