import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI

// A running workflow waits for you: confirm a change (exactly what will be
// sent or written) or answer a question.
LingmoUI.Card {
    id: card
    required property var modelData
    readonly property bool input: modelData.kind === "input"
    elevation: 3
    implicitHeight: column.implicitHeight + LingmoUI.Units.largeSpacing * 2

    Rectangle {
        anchors.fill: parent
        radius: card.radius
        color: "transparent"
        border.width: 1.5
        border.color: card.modelData.external ? LingmoUI.Theme.orangeColor : LingmoUI.Theme.highlightColor
    }

    ColumnLayout {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: LingmoUI.Units.largeSpacing
        spacing: LingmoUI.Units.smallSpacing

        Label {
            text: card.input ? qsTr("The workflow asks you") : card.modelData.external
                  ? qsTr("The workflow wants to act on your behalf") : qsTr("The workflow asks for permission")
            color: LingmoUI.Theme.secondaryTextColor
            font.pointSize: LingmoUI.Units.fontCaption
        }
        Label {
            Layout.fillWidth: true
            text: card.modelData.title
            font.bold: true
            font.pointSize: LingmoUI.Units.fontSubheading
            wrapMode: Text.Wrap
            color: LingmoUI.Theme.textColor
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(details.implicitHeight + LingmoUI.Units.largeSpacing, 220)
            radius: LingmoUI.Theme.smallRadius
            color: LingmoUI.Theme.alternateBackgroundColor
            clip: true
            Flickable {
                anchors.fill: parent
                anchors.margins: LingmoUI.Units.smallSpacing
                contentHeight: details.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}
                TextEdit {
                    id: details
                    width: parent.width
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.Wrap
                    textFormat: TextEdit.PlainText
                    text: card.modelData.details
                    font.family: card.input ? LingmoUI.Theme.fontFamily : "monospace"
                    font.pointSize: card.input ? LingmoUI.Units.fontBody : LingmoUI.Units.fontCaption
                    color: LingmoUI.Theme.textColor
                }
            }
        }

        TextField {
            id: answer
            visible: card.input
            Layout.fillWidth: true
            placeholderText: qsTr("Your answer")
            onAccepted: assistant.answerAsk(card.modelData.request_id, true, false, text)
        }

        CheckBox {
            id: dontAsk
            visible: card.modelData.external === true
            text: qsTr("Don't ask again for this workflow")
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            LingmoUI.ActionButton {
                text: card.input ? qsTr("Cancel") : qsTr("Decline")
                destructive: !card.input
                subtle: true
                onClicked: assistant.answerAsk(card.modelData.request_id, false, false, "")
            }
            LingmoUI.ActionButton {
                text: card.input ? qsTr("Send") : qsTr("Allow")
                primary: true
                onClicked: assistant.answerAsk(card.modelData.request_id, true, dontAsk.checked, answer.text)
            }
        }
    }
}
