import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI

// Approving what a saved workflow can do, in plain words. Asked once per set
// of capabilities; adding a block that does something new asks again.
Popup {
    id: dialog
    property var info: ({})
    readonly property var caps: info.capabilities || []
    readonly property bool hasExternal: caps.some(c => c.external)

    function openFor(newInfo) {
        info = newInfo
        dontAsk.checked = false
        open()
    }

    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(520, parent ? parent.width - 60 : 520)
    modal: true
    focus: true
    padding: LingmoUI.Units.largeSpacing * 2
    closePolicy: Popup.CloseOnEscape

    Overlay.modal: Rectangle { color: LingmoUI.Theme.overlayScrimColor }

    background: Rectangle {
        radius: LingmoUI.Theme.hugeRadius
        color: LingmoUI.Theme.secondBackgroundColor
        border.color: LingmoUI.Theme.darkMode ? Qt.rgba(1, 1, 1, 0.15) : Qt.rgba(0, 0, 0, 0.15)
    }

    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: LingmoUI.Units.shortDuration } }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: LingmoUI.Units.shortDuration } }

    contentItem: ColumnLayout {
        spacing: LingmoUI.Units.largeSpacing

        RowLayout {
            spacing: LingmoUI.Units.largeSpacing
            Rectangle {
                Layout.preferredWidth: 44; Layout.preferredHeight: 44
                radius: 22
                color: Qt.rgba(LingmoUI.Theme.highlightColor.r, LingmoUI.Theme.highlightColor.g, LingmoUI.Theme.highlightColor.b, 0.15)
                LingmoUI.IconItem { anchors.centerIn: parent; width: 24; height: 24; source: "security-high"; color: LingmoUI.Theme.highlightColor }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Label {
                    text: qsTr("Approve what “%1” can do").arg(dialog.info.name || "")
                    font.pointSize: LingmoUI.Units.fontHeading
                    font.bold: true
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                    color: LingmoUI.Theme.textColor
                }
                Label {
                    text: qsTr("You only need to do this again if the workflow starts doing something new.")
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                    color: LingmoUI.Theme.secondaryTextColor
                    font.pointSize: LingmoUI.Units.fontCaption
                }
            }
        }

        Label {
            Layout.fillWidth: true
            text: dialog.info.summary || ""
            wrapMode: Text.Wrap
            font.pointSize: LingmoUI.Units.fontBody
            color: LingmoUI.Theme.textColor
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: capsColumn.implicitHeight + LingmoUI.Units.largeSpacing * 1.5
            radius: LingmoUI.Theme.bigRadius
            color: LingmoUI.Theme.alternateBackgroundColor
            visible: dialog.caps.length > 0
            ColumnLayout {
                id: capsColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: LingmoUI.Units.largeSpacing
                spacing: LingmoUI.Units.smallSpacing
                Repeater {
                    model: dialog.caps
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: LingmoUI.Units.smallSpacing
                        LingmoUI.IconItem {
                            Layout.preferredWidth: 16; Layout.preferredHeight: 16
                            source: modelData.external ? "mail-send" : modelData.writes ? "document-edit" : "document-preview"
                            color: modelData.external ? LingmoUI.Theme.orangeColor : LingmoUI.Theme.secondaryTextColor
                        }
                        Label {
                            Layout.fillWidth: true
                            text: modelData.text.charAt(0).toUpperCase() + modelData.text.slice(1)
                            wrapMode: Text.Wrap
                            color: LingmoUI.Theme.textColor
                        }
                        LingmoUI.Badge {
                            visible: modelData.external
                            text: qsTr("asks every run")
                            tone: LingmoUI.Theme.orangeColor
                            subtle: true
                        }
                    }
                }
            }
        }

        Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: qsTr("It never deletes anything. The switches in Settings › AI still apply, and every run is logged.")
            font.pointSize: LingmoUI.Units.fontCaption
            color: LingmoUI.Theme.secondaryTextColor
        }

        CheckBox {
            id: dontAsk
            visible: dialog.hasExternal
            text: qsTr("Don't ask again before sending for this workflow")
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: LingmoUI.Units.smallSpacing
            Item { Layout.fillWidth: true }
            LingmoUI.ActionButton {
                text: qsTr("Not now")
                subtle: true
                onClicked: dialog.close()
            }
            LingmoUI.ActionButton {
                text: qsTr("Approve")
                primary: true
                onClicked: {
                    assistant.approveFlow(dontAsk.checked)
                    dialog.close()
                }
            }
        }
    }
}
