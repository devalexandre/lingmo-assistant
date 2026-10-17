import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI

// A write the assistant wants to make: exactly what and where, Allow / Decline
LingmoUI.Card {
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
        Behavior on opacity { NumberAnimation { duration: LingmoUI.Units.shortDuration } }
    }

    ColumnLayout {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: LingmoUI.Units.largeSpacing
        anchors.leftMargin: card.padding
        anchors.rightMargin: card.padding
        spacing: LingmoUI.Units.smallSpacing

        Label {
            text: qsTr("The assistant asks for permission")
            color: LingmoUI.Theme.secondaryTextColor
            font.pointSize: LingmoUI.Units.fontCaption
        }

        Label {
            Layout.fillWidth: true
            text: card.title
            font.bold: true
            font.pointSize: LingmoUI.Units.fontSubheading
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
                    font.pointSize: LingmoUI.Units.fontCaption
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
                font.pointSize: LingmoUI.Units.fontBody
                color: card.confirmState === "allowed" ? LingmoUI.Theme.successColor : LingmoUI.Theme.secondaryTextColor
            }

            Item { Layout.fillWidth: true; visible: card.confirmState === "pending" }

            LingmoUI.ActionButton {
                visible: card.confirmState === "pending"
                text: qsTr("Decline")
                destructive: true
                subtle: true
                onClicked: assistant.confirm(card.requestId, false)
            }

            LingmoUI.ActionButton {
                visible: card.confirmState === "pending"
                text: qsTr("Allow")
                primary: true
                onClicked: assistant.confirm(card.requestId, true)
            }
        }
    }
}
