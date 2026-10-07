import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI

// A write the assistant wants to make: exactly what and where, Allow / Decline
Card {
    id: card

    property string requestId
    property string title
    property string details
    property string confirmState: "pending"   // pending, allowed, denied, expired

    implicitHeight: column.implicitHeight + LingmoUI.Units.largeSpacing * 2

    // Accent outline while it waits for an answer
    Rectangle {
        anchors.fill: parent
        radius: card.radius
        color: "transparent"
        border.width: 1.5
        border.color: LingmoUI.Theme.highlightColor
        opacity: card.confirmState === "pending" ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 200 } }
    }

    ColumnLayout {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: LingmoUI.Units.largeSpacing
        anchors.leftMargin: LingmoUI.Units.largeSpacing * 1.5
        anchors.rightMargin: LingmoUI.Units.largeSpacing * 1.5
        spacing: LingmoUI.Units.smallSpacing

        Label {
            text: qsTr("The assistant asks for permission")
            color: LingmoUI.Theme.disabledTextColor
            font.pointSize: LingmoUI.Theme.fontSize * 0.9
        }

        Label {
            Layout.fillWidth: true
            text: card.title
            font.bold: true
            font.pointSize: LingmoUI.Theme.fontSize * 1.1
            wrapMode: Text.Wrap
            color: LingmoUI.Theme.textColor
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(detailsText.implicitHeight + LingmoUI.Units.largeSpacing, 320)
            radius: LingmoUI.Theme.smallRadius
            color: LingmoUI.Theme.alternateBackgroundColor
            clip: true

            Flickable {
                id: detailsFlick
                anchors.fill: parent
                anchors.margins: LingmoUI.Units.smallSpacing
                contentHeight: detailsText.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}

                TextEdit {
                    id: detailsText
                    width: detailsFlick.width
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.Wrap
                    textFormat: TextEdit.PlainText
                    text: card.details
                    font.family: "monospace"
                    font.pointSize: LingmoUI.Theme.fontSize * 0.85
                    color: LingmoUI.Theme.textColor
                    selectionColor: LingmoUI.Theme.highlightColor
                    selectedTextColor: LingmoUI.Theme.highlightedTextColor
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: LingmoUI.Units.smallSpacing
            spacing: LingmoUI.Units.smallSpacing

            Label {
                Layout.fillWidth: true
                visible: card.confirmState !== "pending"
                text: card.confirmState === "allowed" ? qsTr("Allowed")
                    : card.confirmState === "denied" ? qsTr("Declined: nothing was changed")
                    : qsTr("This request is no longer valid")
                color: card.confirmState === "allowed" ? LingmoUI.Theme.greenColor : LingmoUI.Theme.disabledTextColor
            }

            Item { Layout.fillWidth: true; visible: card.confirmState === "pending" }

            ActionButton {
                visible: card.confirmState === "pending"
                text: qsTr("Decline")
                destructive: true
                onClicked: assistant.confirm(card.requestId, false)
            }

            ActionButton {
                visible: card.confirmState === "pending"
                text: qsTr("Allow")
                primary: true
                onClicked: assistant.confirm(card.requestId, true)
            }
        }
    }
}
