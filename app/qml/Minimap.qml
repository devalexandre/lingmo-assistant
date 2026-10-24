import QtQuick
import QtQuick.Controls
import LingmoUI.CompatibleModule 3.0 as LingmoUI
import Lingmo.Assistant

// Overview of the whole workflow; the frame is the visible part. Click or
// drag to move the view.
Rectangle {
    id: map
    property var editor
    property Item viewport

    width: 190
    height: 124
    radius: LingmoUI.Theme.mediumRadius
    color: LingmoUI.Theme.secondBackgroundColor
    border.color: LingmoUI.Theme.borderColor
    opacity: 0.95
    visible: editor.doc.nodes.count > 1

    clip: true
    readonly property rect area: {
        editor.geometryTick
        const b = editor.doc.bounds
        return Qt.rect(b.x - 60, b.y - 60, b.width + 120, b.height + 120)
    }
    readonly property real k: Math.min((width - 12) / area.width, (height - 12) / area.height)
    readonly property real ox: 6 + ((width - 12) - area.width * k) / 2
    readonly property real oy: 6 + ((height - 12) - area.height * k) / 2

    Repeater {
        model: map.editor.doc.nodes
        delegate: Rectangle {
            required property string nodeId
            required property real posX
            required property real posY
            required property string status
            x: map.ox + (posX - map.area.x) * map.k
            y: map.oy + (posY - map.area.y) * map.k
            width: map.editor.nodeWidth * map.k
            height: Math.max(3, 76 * map.k)
            radius: 2
            color: status !== "" ? Ui.statusColor(status) : Ui.color(map.editor.doc.category(nodeId))
            opacity: 0.85
        }
    }

    Rectangle {
        x: map.ox + (-map.editor.panX / map.editor.zoom - map.area.x) * map.k
        y: map.oy + (-map.editor.panY / map.editor.zoom - map.area.y) * map.k
        width: map.viewport.width / map.editor.zoom * map.k
        height: map.viewport.height / map.editor.zoom * map.k
        color: Qt.rgba(LingmoUI.Theme.highlightColor.r, LingmoUI.Theme.highlightColor.g, LingmoUI.Theme.highlightColor.b, 0.12)
        border.color: LingmoUI.Theme.highlightColor
        border.width: 1.5
        radius: 3
    }

    function centerOn(px, py) {
        const wx = map.area.x + (px - map.ox) / map.k
        const wy = map.area.y + (py - map.oy) / map.k
        editor.panX = viewport.width / 2 - wx * editor.zoom
        editor.panY = viewport.height / 2 - wy * editor.zoom
    }

    MouseArea {
        anchors.fill: parent
        onPressed: (mouse) => map.centerOn(mouse.x, mouse.y)
        onPositionChanged: (mouse) => { if (pressed) map.centerOn(mouse.x, mouse.y) }
    }
}
