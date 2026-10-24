import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI
import Lingmo.Assistant

// One block on the canvas: coloured icon tile, title, a one-line summary,
// an input port on the left and its output ports on the right. Drag to move;
// drag from an output port to another block to connect.
Item {
    id: node

    required property string nodeId
    required property string nodeType
    required property string label
    required property real posX
    required property real posY
    required property var params
    required property string status
    required property string output
    required property string error
    required property string issue
    required property string issueLevel

    property var editor          // FlowEditor
    readonly property var doc: assistant.flow
    readonly property var typeInfo: doc.nodeType(nodeType)
    readonly property string category: typeInfo.category || ""
    readonly property var portList: { node.params; return doc.ports(nodeId) }
    readonly property bool selected: editor && editor.selected === nodeId
    readonly property bool isTrigger: nodeType.indexOf("trigger.") === 0

    x: posX
    y: posY
    width: editor ? editor.nodeWidth : 220
    height: editor ? editor.nodeHeight(portList.length) : 76
    z: selected || dragHandler.active ? 2 : 1

    // Running: a soft accent halo that breathes
    Rectangle {
        anchors.fill: card
        anchors.margins: -5
        radius: card.radius + 5
        color: "transparent"
        border.width: 3
        border.color: Ui.statusColor(node.status)
        visible: node.status === "running" || node.status === "waiting"
        SequentialAnimation on opacity {
            running: node.status === "running" || node.status === "waiting"
            loops: Animation.Infinite
            NumberAnimation { from: 1; to: 0.25; duration: 700; easing.type: Easing.InOutQuad }
            NumberAnimation { from: 0.25; to: 1; duration: 700; easing.type: Easing.InOutQuad }
        }
    }

    Rectangle {
        id: card
        anchors.fill: parent
        radius: LingmoUI.Theme.bigRadius
        color: LingmoUI.Theme.secondBackgroundColor
        border.width: node.selected ? 2 : 1
        border.color: node.selected ? LingmoUI.Theme.highlightColor
                     : node.issueLevel === "error" ? LingmoUI.Theme.redColor
                     : LingmoUI.Theme.borderColor
        Behavior on border.color { ColorAnimation { duration: LingmoUI.Units.shortDuration } }

        // category stripe
        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 4
            radius: 2
            anchors.topMargin: LingmoUI.Theme.bigRadius
            anchors.bottomMargin: LingmoUI.Theme.bigRadius
            color: Ui.color(node.category)
        }

        RowLayout {
            id: head
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            anchors.topMargin: 12
            spacing: 10

            Rectangle {
                Layout.preferredWidth: 30
                Layout.preferredHeight: 30
                radius: LingmoUI.Theme.mediumRadius
                color: Ui.color(node.category)
                LingmoUI.IconItem {
                    anchors.centerIn: parent
                    width: 18; height: 18
                    source: node.typeInfo.icon || "application-x-executable"
                    color: "white"
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Label {
                    Layout.fillWidth: true
                    text: node.label !== "" ? node.label : (node.typeInfo.label || node.nodeType)
                    font.bold: true
                    font.pointSize: LingmoUI.Units.fontBody
                    elide: Text.ElideRight
                    color: LingmoUI.Theme.textColor
                }
                Label {
                    Layout.fillWidth: true
                    text: node.isTrigger ? qsTr("Trigger") + " · " + (node.typeInfo.label || "")
                                         : (node.typeInfo.label || "") + " · " + node.nodeId
                    font.pointSize: LingmoUI.Units.fontCaption
                    elide: Text.ElideRight
                    color: LingmoUI.Theme.secondaryTextColor
                }
            }

            // run status / validation
            LingmoUI.IconItem {
                Layout.preferredWidth: 16
                Layout.preferredHeight: 16
                visible: source !== ""
                source: node.status === "done" ? "dialog-ok-apply"
                      : node.status === "error" ? "dialog-error"
                      : node.status === "declined" ? "dialog-cancel"
                      : node.status === "waiting" ? "dialog-question"
                      : node.issueLevel === "error" ? "dialog-error"
                      : node.issueLevel === "warning" ? "dialog-warning" : ""
                color: node.status !== "" ? Ui.statusColor(node.status)
                       : node.issueLevel === "error" ? LingmoUI.Theme.redColor : LingmoUI.Theme.orangeColor
                HoverHandler { id: statusHover }
                ToolTip.visible: statusHover.hovered && (node.error !== "" || node.issue !== "")
                ToolTip.text: node.error !== "" ? node.error : node.issue
            }
        }

        Label {
            id: summaryLabel
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: head.bottom
            anchors.leftMargin: 14
            anchors.rightMargin: node.portList.length > 1 ? 70 : 14
            anchors.topMargin: 6
            text: {
                if (node.status === "done" && node.output !== "")
                    return "→ " + node.output.split("\n")[0]
                if (node.error !== "")
                    return node.error
                node.params
                return node.doc.summary(node.nodeId)
            }
            color: node.error !== "" ? LingmoUI.Theme.redColor
                  : node.status === "done" ? LingmoUI.Theme.greenColor : LingmoUI.Theme.secondaryTextColor
            font.pointSize: LingmoUI.Units.fontCaption
            elide: Text.ElideRight
            maximumLineCount: 1
        }
    }

    // ------------------------------------------------------------ moving and selecting
    // One handler for both gestures: from the right edge (an output port) it
    // draws a connection, anywhere else it moves the block
    DragHandler {
        id: dragHandler
        target: null
        dragThreshold: 3
        margin: 10          // the output ports stick out of the block
        property point start
        property bool connecting: false
        onActiveChanged: {
            if (active) {
                const p = centroid.pressPosition
                connecting = p.x >= node.width - 18 && node.portList.length > 0
                if (connecting) {
                    let i = Math.round((p.y - node.editor.portOffset(0)) / 24)
                    i = Math.max(0, Math.min(node.portList.length - 1, i))
                    node.editor.beginConnect(node.nodeId, node.portList[i])
                } else {
                    start = Qt.point(node.posX, node.posY)
                    node.editor.selected = node.nodeId
                }
            } else if (connecting) {
                connecting = false
                node.editor.endConnect()
            } else {
                node.doc.endMove()
            }
        }
        onCentroidChanged: {
            if (active && connecting)
                node.editor.dragConnect(node.mapToItem(node.editor.world, centroid.position.x, centroid.position.y))
        }
        onActiveTranslationChanged: {
            if (!active || connecting)
                return
            const snap = 10
            const nx = Math.round((start.x + activeTranslation.x / node.editor.zoom) / snap) * snap
            const ny = Math.round((start.y + activeTranslation.y / node.editor.zoom) / snap) * snap
            node.doc.moveNode(node.nodeId, nx, ny)
        }
    }

    TapHandler {
        onTapped: node.editor.selected = node.nodeId
        onDoubleTapped: node.editor.selected = node.nodeId
    }

    // ------------------------------------------------------------ ports
    // input
    Rectangle {
        visible: !node.isTrigger
        x: -width / 2
        y: node.editor.portOffset(0) - height / 2
        width: 14; height: 14
        radius: 7
        color: LingmoUI.Theme.secondBackgroundColor
        border.width: 2
        border.color: node.editor && node.editor.connecting && node.editor.hoverTarget === node.nodeId
                      ? LingmoUI.Theme.highlightColor : LingmoUI.Theme.disabledTextColor
    }

    Repeater {
        model: node.portList
        delegate: Item {
            id: portItem
            required property string modelData
            required property int index
            readonly property string portLabel: { node.params; return node.doc.portLabel(node.nodeId, modelData) }
            x: node.width - width / 2
            y: node.editor.portOffset(index) - height / 2
            width: 16; height: 16

            Label {
                visible: portItem.portLabel !== ""
                anchors.right: parent.left
                anchors.rightMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                text: portItem.portLabel
                font.pointSize: LingmoUI.Units.fontCaption
                color: LingmoUI.Theme.secondaryTextColor
            }

            Rectangle {
                anchors.centerIn: parent
                width: portHover.hovered || (dragHandler.connecting && node.editor.connectPort === portItem.modelData) ? 16 : 13
                height: width
                radius: width / 2
                color: Ui.color(node.category)
                border.width: 2
                border.color: LingmoUI.Theme.secondBackgroundColor
                Behavior on width { NumberAnimation { duration: LingmoUI.Units.shortDuration } }
            }

            HoverHandler { id: portHover; cursorShape: Qt.CrossCursor }

        }
    }
}
