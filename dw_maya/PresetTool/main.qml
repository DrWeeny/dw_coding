import QtQuick 2.4

Rectangle {
    id: presetWindow
    width: 800
    height: 600
    color:"steelblue"

    Text {
        text: "Hello World"
        anchors.centerIn: parent
        x: presetWindow.width/2
        y: presetWindow.height/2

    }
}