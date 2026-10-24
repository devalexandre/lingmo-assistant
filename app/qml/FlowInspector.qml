import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI
import Lingmo.Assistant

// No block selected: the workflow itself — description, on/off, what it can
// do (and its approval), problems and the run history with each step's log.
Item {
    id: panel
    property var editor
    readonly property var doc: assistant.flow
    readonly property var info: assistant.flowInfo
    readonly property var issues: info.issues || []
    property string openRunId: ""

    function statusText(s) {
        switch (s) {
        case "done": return qsTr("Finished")
        case "failed": return qsTr("Failed")
        case "refused": return qsTr("Not allowed")
        case "stopped": return qsTr("Stopped")
        case "running": return qsTr("Running")
        case "waiting": return qsTr("Waiting for you")
        case "declined": return qsTr("Declined")
        case "error": return qsTr("Error")
        }
        return s
    }

    Flickable {
        anchors.fill: parent
        contentHeight: column.implicitHeight + LingmoUI.Units.largeSpacing * 2
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        ColumnLayout {
            id: column
            x: LingmoUI.Units.largeSpacing
            y: LingmoUI.Units.largeSpacing
            width: parent.width - LingmoUI.Units.largeSpacing * 2
            spacing: LingmoUI.Units.largeSpacing

            LingmoUI.Card {
                Layout.fillWidth: true
                implicitHeight: about.implicitHeight + LingmoUI.Units.largeSpacing * 2
                ColumnLayout {
                    id: about
                    anchors.fill: parent
                    anchors.margins: LingmoUI.Units.largeSpacing
                    spacing: LingmoUI.Units.smallSpacing

                    RowLayout {
                        Layout.fillWidth: true
                        Label {
                            Layout.fillWidth: true
                            text: qsTr("Active")
                            font.bold: true
                            color: LingmoUI.Theme.textColor
                        }
                        Switch {
                            checked: panel.doc.enabled
                            onToggled: panel.doc.enabled = checked
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        font.pointSize: LingmoUI.Units.fontCaption
                        color: LingmoUI.Theme.secondaryTextColor
                        text: panel.info.background
                              ? qsTr("Runs by itself in the background, even with this window closed.")
                              : qsTr("Runs when you start it, by voice or by its shortcut.")
                    }
                    Label { text: qsTr("Description"); font.pointSize: LingmoUI.Units.fontCaption; font.weight: Font.DemiBold; color: LingmoUI.Theme.secondaryTextColor; Layout.topMargin: LingmoUI.Units.smallSpacing }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: Math.max(descArea.implicitHeight, 56)
                        radius: LingmoUI.Theme.smallRadius
                        color: LingmoUI.Theme.alternateBackgroundColor
                        TextArea {
                            id: descArea
                            anchors.fill: parent
                            wrapMode: TextArea.Wrap
                            text: panel.doc.description
                            placeholderText: qsTr("What this workflow is for")
                            background: Item {}
                            onEditingFinished: panel.doc.description = text
                        }
                    }
                }
            }

            // ------------------------------------------------------------ permissions
            LingmoUI.Card {
                Layout.fillWidth: true
                implicitHeight: perms.implicitHeight + LingmoUI.Units.largeSpacing * 2
                ColumnLayout {
                    id: perms
                    anchors.fill: parent
                    anchors.margins: LingmoUI.Units.largeSpacing
                    spacing: LingmoUI.Units.smallSpacing

                    RowLayout {
                        Layout.fillWidth: true
                        LingmoUI.IconItem {
                            Layout.preferredWidth: 18; Layout.preferredHeight: 18
                            source: panel.info.approved ? "security-high" : "security-medium"
                            color: panel.info.approved ? LingmoUI.Theme.greenColor : LingmoUI.Theme.orangeColor
                        }
                        Label {
                            Layout.fillWidth: true
                            text: qsTr("What it can do")
                            font.bold: true
                            elide: Text.ElideRight
                            color: LingmoUI.Theme.textColor
                        }
                        LingmoUI.Badge {
                            text: panel.info.approved ? qsTr("Approved") : qsTr("Needs approval")
                            tone: panel.info.approved ? LingmoUI.Theme.greenColor : LingmoUI.Theme.orangeColor
                            subtle: true
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: panel.info.summary || ""
                        color: LingmoUI.Theme.textColor
                    }
                    Repeater {
                        model: panel.info.blocked || []
                        delegate: Label {
                            required property string modelData
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            text: "⚠ " + modelData
                            font.pointSize: LingmoUI.Units.fontCaption
                            color: LingmoUI.Theme.orangeColor
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        visible: panel.info.dont_ask === true
                        wrapMode: Text.Wrap
                        text: qsTr("It sends without asking each time (you chose “don't ask again”).")
                        font.pointSize: LingmoUI.Units.fontCaption
                        color: LingmoUI.Theme.secondaryTextColor
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: LingmoUI.Units.smallSpacing
                        LingmoUI.ActionButton {
                            visible: !panel.info.approved && panel.doc.revision > 0 && !panel.doc.dirty
                            text: qsTr("Review and approve")
                            primary: true
                            onClicked: Ui.approvalRequested(panel.info)
                        }
                        LingmoUI.ActionButton {
                            visible: panel.info.dont_ask === true
                            text: qsTr("Ask me again")
                            subtle: true
                            onClicked: assistant.approveFlow(false)
                        }
                        LingmoUI.ActionButton {
                            text: qsTr("AI settings")
                            subtle: true
                            onClicked: assistant.openSettings()
                        }
                    }
                }
            }

            // ------------------------------------------------------------ problems
            LingmoUI.Card {
                Layout.fillWidth: true
                visible: panel.issues.length > 0
                implicitHeight: problems.implicitHeight + LingmoUI.Units.largeSpacing * 2
                ColumnLayout {
                    id: problems
                    anchors.fill: parent
                    anchors.margins: LingmoUI.Units.largeSpacing
                    spacing: 6
                    Label { text: qsTr("To check"); font.bold: true; color: LingmoUI.Theme.textColor }
                    Repeater {
                        model: panel.issues
                        delegate: RowLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 6
                            LingmoUI.IconItem {
                                Layout.preferredWidth: 14; Layout.preferredHeight: 14
                                Layout.alignment: Qt.AlignTop
                                source: modelData.level === "error" ? "dialog-error" : "dialog-warning"
                                color: modelData.level === "error" ? LingmoUI.Theme.redColor : LingmoUI.Theme.orangeColor
                            }
                            Label {
                                Layout.fillWidth: true
                                wrapMode: Text.Wrap
                                text: (modelData.node ? modelData.node + ": " : "") + modelData.message
                                font.pointSize: LingmoUI.Units.fontCaption
                                color: LingmoUI.Theme.textColor
                                MouseArea { anchors.fill: parent; onClicked: if (modelData.node) panel.editor.selected = modelData.node }
                            }
                        }
                    }
                }
            }

            // ------------------------------------------------------------ history
            Label {
                text: qsTr("Run history")
                font.bold: true
                color: LingmoUI.Theme.textColor
            }
            Label {
                visible: assistant.flowRuns.length === 0
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: qsTr("Every run is logged here, step by step.")
                font.pointSize: LingmoUI.Units.fontCaption
                color: LingmoUI.Theme.secondaryTextColor
            }
            Repeater {
                model: assistant.flowRuns
                delegate: LingmoUI.Card {
                    id: runCard
                    required property var modelData
                    readonly property bool open: panel.openRunId === modelData.id
                    Layout.fillWidth: true
                    clickable: true
                    implicitHeight: runColumn.implicitHeight + LingmoUI.Units.largeSpacing * 1.4
                    onClicked: {
                        panel.openRunId = open ? "" : modelData.id
                        if (!open) assistant.openRun(modelData.id)
                        else assistant.flow.clearRunState()
                    }
                    ColumnLayout {
                        id: runColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: LingmoUI.Units.largeSpacing * 0.7
                        spacing: 4
                        RowLayout {
                            Layout.fillWidth: true
                            Rectangle { Layout.preferredWidth: 8; Layout.preferredHeight: 8; radius: 4; color: Ui.statusColor(runCard.modelData.status) }
                            Label {
                                Layout.fillWidth: true
                                text: new Date(runCard.modelData.started * 1000).toLocaleString(Qt.locale(), Locale.ShortFormat)
                                color: LingmoUI.Theme.textColor
                                font.pointSize: LingmoUI.Units.fontCaption
                            }
                            Label {
                                text: panel.statusText(runCard.modelData.status) + (runCard.modelData.mode === "test" ? " · " + qsTr("test") : "")
                                color: Ui.statusColor(runCard.modelData.status)
                                font.pointSize: LingmoUI.Units.fontCaption
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            visible: (runCard.modelData.error || "") !== ""
                            text: runCard.modelData.error || ""
                            wrapMode: Text.Wrap
                            color: LingmoUI.Theme.secondaryTextColor
                            font.pointSize: LingmoUI.Units.fontCaption
                        }
                        // the steps of the open run
                        Repeater {
                            model: runCard.open && assistant.runLog.id === runCard.modelData.id ? assistant.runLog.steps : []
                            delegate: ColumnLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: 1
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: "•"; color: Ui.statusColor(modelData.status) }
                                    Label {
                                        Layout.fillWidth: true
                                        text: (modelData.label || modelData.node) + " — " + panel.statusText(modelData.status)
                                        elide: Text.ElideRight
                                        font.pointSize: LingmoUI.Units.fontCaption
                                        color: LingmoUI.Theme.textColor
                                    }
                                }
                                Label {
                                    Layout.fillWidth: true
                                    Layout.leftMargin: 12
                                    visible: text !== ""
                                    text: modelData.error || (modelData.outputs && modelData.outputs.output ? modelData.outputs.output.split("\n")[0] : "")
                                    elide: Text.ElideRight
                                    font.pointSize: LingmoUI.Units.fontCaption
                                    color: modelData.error ? LingmoUI.Theme.redColor : LingmoUI.Theme.secondaryTextColor
                                }
                            }
                        }
                    }
                }
            }

            LingmoUI.ActionButton {
                Layout.alignment: Qt.AlignRight
                text: qsTr("Remove workflow")
                iconName: "edit-delete"
                destructive: true
                subtle: true
                visible: panel.doc.revision > 0
                onClicked: assistant.removeFlow(panel.doc.flowId)
            }
        }
    }
}
