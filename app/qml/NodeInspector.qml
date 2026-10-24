import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI
import Lingmo.Assistant

// The selected block: name, what it does, its fields and its outputs
Item {
    id: inspector
    property var editor
    property string nodeId
    readonly property var doc: assistant.flow
    property int tick: 0
    readonly property var info: { tick; return doc.node(nodeId) }
    readonly property var typeInfo: doc.nodeType(info.type || "")
    readonly property var values: { tick; return doc.params(nodeId) }
    readonly property int row: doc.nodes.indexOf(nodeId)

    Connections {
        target: inspector.doc.nodes
        function onDataChanged(topLeft) { if (topLeft.row === inspector.row) inspector.tick++ }
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

            RowLayout {
                Layout.fillWidth: true
                spacing: LingmoUI.Units.largeSpacing
                Rectangle {
                    Layout.preferredWidth: 40; Layout.preferredHeight: 40
                    radius: LingmoUI.Theme.bigRadius
                    color: Ui.color(inspector.typeInfo.category || "")
                    LingmoUI.IconItem { anchors.centerIn: parent; width: 22; height: 22; source: inspector.typeInfo.icon || ""; color: "white" }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    Label {
                        Layout.fillWidth: true
                        text: inspector.typeInfo.label || ""
                        font.pointSize: LingmoUI.Units.fontSubheading
                        font.bold: true
                        color: LingmoUI.Theme.textColor
                        wrapMode: Text.Wrap
                    }
                    Label {
                        Layout.fillWidth: true
                        text: inspector.typeInfo.description || ""
                        wrapMode: Text.Wrap
                        font.pointSize: LingmoUI.Units.fontCaption
                        color: LingmoUI.Theme.secondaryTextColor
                    }
                }
            }

            // what this block can do to your things
            LingmoUI.Banner {
                Layout.fillWidth: true
                visible: !!inspector.typeInfo.capability && inspector.typeInfo.capability.writes
                type: inspector.typeInfo.capability && inspector.typeInfo.capability.external ? LingmoUI.Banner.Warning : LingmoUI.Banner.Info
                closable: false
                text: !inspector.typeInfo.capability ? ""
                      : inspector.typeInfo.capability.external
                        ? qsTr("This block acts on your behalf (%1). It asks you before every run unless you allow it for this workflow.").arg(inspector.typeInfo.capability.verb.replace("{account}", qsTr("your account")))
                        : qsTr("This block can %1. You approve it once when saving.").arg(inspector.typeInfo.capability.verb)
            }

            LingmoUI.Banner {
                readonly property var problem: { inspector.tick; return inspector.doc.issue(inspector.nodeId) }
                Layout.fillWidth: true
                visible: (problem.message || "") !== ""
                type: problem.level === "error" ? LingmoUI.Banner.Error : LingmoUI.Banner.Warning
                closable: false
                text: problem.message || ""
            }

            LingmoUI.Card {
                Layout.fillWidth: true
                implicitHeight: basics.implicitHeight + LingmoUI.Units.largeSpacing * 2
                ColumnLayout {
                    id: basics
                    anchors.fill: parent
                    anchors.margins: LingmoUI.Units.largeSpacing
                    spacing: LingmoUI.Units.smallSpacing
                    Label { text: qsTr("Name on the canvas"); font.pointSize: LingmoUI.Units.fontCaption; font.weight: Font.DemiBold; color: LingmoUI.Theme.secondaryTextColor }
                    TextField {
                        Layout.fillWidth: true
                        text: inspector.info.label || ""
                        placeholderText: inspector.typeInfo.label || ""
                        onEditingFinished: inspector.doc.setLabel(inspector.nodeId, text)
                    }
                    Label {
                        visible: !(inspector.info.type || "").startsWith("trigger.")
                        text: qsTr("Name for variables")
                        font.pointSize: LingmoUI.Units.fontCaption; font.weight: Font.DemiBold; color: LingmoUI.Theme.secondaryTextColor
                    }
                    TextField {
                        id: idField
                        visible: !(inspector.info.type || "").startsWith("trigger.")
                        Layout.fillWidth: true
                        font.family: "monospace"
                        text: inspector.nodeId
                        validator: RegularExpressionValidator { regularExpression: /[a-z][a-z0-9_]{0,39}/ }
                        onEditingFinished: {
                            const newId = text
                            if (newId !== inspector.nodeId && inspector.doc.renameNode(inspector.nodeId, newId))
                                inspector.editor.selected = newId
                            else
                                text = inspector.nodeId
                        }
                    }
                }
            }

            LingmoUI.Card {
                Layout.fillWidth: true
                visible: (inspector.typeInfo.params || []).length > 0
                implicitHeight: paramsColumn.implicitHeight + LingmoUI.Units.largeSpacing * 2
                ColumnLayout {
                    id: paramsColumn
                    anchors.fill: parent
                    anchors.margins: LingmoUI.Units.largeSpacing
                    spacing: LingmoUI.Units.largeSpacing
                    Repeater {
                        model: inspector.typeInfo.params || []
                        delegate: ParamField {
                            required property var modelData
                            Layout.fillWidth: true
                            param: modelData
                            value: inspector.values[modelData.name]
                            nodeId: inspector.nodeId
                            editor: inspector.editor
                            onEdited: (v) => inspector.doc.setParam(inspector.nodeId, modelData.name, v)
                        }
                    }
                }
            }

            // outputs to reuse
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                visible: outputsRepeater.count > 0
                Label { text: qsTr("Results you can use later"); font.pointSize: LingmoUI.Units.fontCaption; font.weight: Font.DemiBold; color: LingmoUI.Theme.secondaryTextColor }
                Flow {
                    Layout.fillWidth: true
                    spacing: 4
                    Repeater {
                        id: outputsRepeater
                        model: { inspector.tick; return inspector.doc.outputs(inspector.nodeId) }
                        delegate: LingmoUI.Badge {
                            required property string modelData
                            text: "{{" + ((inspector.info.type || "").startsWith("trigger.") ? "trigger" : inspector.nodeId) + "." + modelData + "}}"
                            subtle: true
                            font.family: "monospace"
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: LingmoUI.Units.smallSpacing
                LingmoUI.ActionButton {
                    visible: !(inspector.info.type || "").startsWith("trigger.")
                    text: qsTr("Duplicate")
                    iconName: "edit-copy"
                    subtle: true
                    onClicked: inspector.editor.selected = inspector.doc.duplicateNode(inspector.nodeId)
                }
                Item { Layout.fillWidth: true }
                LingmoUI.ActionButton {
                    text: qsTr("Remove block")
                    iconName: "edit-delete"
                    destructive: true
                    subtle: true
                    onClicked: { const id = inspector.nodeId; inspector.editor.selected = ""; inspector.doc.removeNode(id) }
                }
            }
        }
    }
}
