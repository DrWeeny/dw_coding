from Qt import QtWidgets

def copy_clipboard(text:str):
    clipboard = QtWidgets.QApplication.clipboard()
    clipboard.setText(text)
    print('#- SENDED TO CLIPBOARD ====')
    print(text)
    print('#- END OF CLIPBOARD =======')