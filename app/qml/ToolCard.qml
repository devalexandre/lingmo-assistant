import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI

// "Ran: lscpu" — collapsed by default, the tool's output when opened
Card {
    id: card

    property string functionName
    property string args
    property bool ok: true
    property bool running: false
    property string output
    property bool expanded: false

    hoverEnabled: output !== ""
    implicitHeight: column.implicitHeight + LingmoUI.Units.largeSpacing

    ColumnLayout {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: LingmoUI.Units.smallSpacing
        anchors.leftMargin: LingmoUI.Units.largeSpacing
        anchors.rightMargin: LingmoUI.Units.largeSpacing
        spacing: LingmoUI.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 2
            spacing: LingmoUI.Units.smallSpacing

            // Spinning while the tool runs
            LingmoUI.IconItem {
                visible: card.running
                Layout.preferredWidth: LingmoUI.Units.iconSizes.small
                Layout.preferredHeight: LingmoUI.Units.iconSizes.small
                source: "view-refresh"
                RotationAnimator on rotation {
                    running: card.running
                    from: 0
                    to: 360
                    duration: 1000
                    loops: Animation.Infinite
                }
            }

            Rectangle {
                visible: !card.running
                Layout.preferredWidth: LingmoUI.Units.smallSpacing * 1.5
                Layout.preferredHeight: width
                Layout.leftMargin: 3
                Layout.rightMargin: 3
                radius: width / 2
                color: card.ok ? LingmoUI.Theme.greenColor : LingmoUI.Theme.redColor
            }

            Label {
                Layout.fillWidth: true
                text: assistant.toolLabel(card.functionName, card.args, card.running)
                elide: Text.ElideMiddle
                color: LingmoUI.Theme.textColor
                font.pointSize: LingmoUI.Theme.fontSize * 0.95
            }

            LingmoUI.IconItem {
                visible: card.output !== ""
                Layout.preferredWidth: LingmoUI.Units.iconSizes.small
                Layout.preferredHeight: LingmoUI.Units.iconSizes.small
                source: card.expanded ? "go-up" : "go-down"
            }
        }

        TextEdit {
            visible: card.expanded
            Layout.fillWidth: true
            Layout.bottomMargin: LingmoUI.Units.smallSpacing
            readOnly: true
            selectByMouse: true
            wrapMode: TextEdit.WrapAnywhere
            textFormat: TextEdit.PlainText
            text: card.output
            font.family: "monospace"
            font.pointSize: LingmoUI.Theme.fontSize * 0.85
            color: card.ok ? LingmoUI.Theme.textColor : LingmoUI.Theme.redColor
            selectionColor: LingmoUI.Theme.highlightColor
            selectedTextColor: LingmoUI.Theme.highlightedTextColor
        }
    }

    TapHandler {
        enabled: card.output !== ""
        onTapped: card.expanded = !card.expanded
    }
}
