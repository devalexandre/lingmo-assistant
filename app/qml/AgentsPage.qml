import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI
import Lingmo.Assistant

// "Agentes": your custom agents, or the editor of one
Item {
    id: page

    Loader {
        anchors.fill: parent
        active: Ui.editingAgentId !== ""
        sourceComponent: AgentEditor {}
    }

    Flickable {
        id: gallery
        anchors.fill: parent
        visible: Ui.editingAgentId === ""
        contentHeight: column.implicitHeight + LingmoUI.Units.largeSpacing * 4
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        ColumnLayout {
            id: column
            width: Math.min(gallery.width - LingmoUI.Units.largeSpacing * 6, 920)
            x: (gallery.width - width) / 2
            spacing: LingmoUI.Units.largeSpacing

            LingmoUI.PageHeader {
                Layout.fillWidth: true
                Layout.preferredHeight: LingmoUI.Units.windowHeaderHeight
                large: false
                title: qsTr("Agents")
                subtitle: qsTr("Assistants with their own instructions, model and tools")
            }

            RowLayout {
                Layout.fillWidth: true
                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    color: LingmoUI.Theme.secondaryTextColor
                    text: qsTr("Chat with an agent, call it from a workflow, or from Spotlight with “ai:@name question”. Its tools never go beyond what Settings › AI allows.")
                }
                LingmoUI.ActionButton {
                    primary: true
                    text: qsTr("New agent")
                    iconName: "list-add"
                    onClicked: Ui.editAgent({})
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: width > 720 ? 3 : 2
                columnSpacing: LingmoUI.Units.largeSpacing
                rowSpacing: LingmoUI.Units.largeSpacing

                Repeater {
                    model: assistant.agents
                    delegate: LingmoUI.Card {
                        id: agentCard
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredWidth: 220
                        implicitHeight: 196
                        clickable: true
                        liftOnHover: true
                        onClicked: Ui.editAgent(modelData)

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: LingmoUI.Units.largeSpacing * 1.2
                            spacing: LingmoUI.Units.smallSpacing

                            RowLayout {
                                spacing: LingmoUI.Units.largeSpacing
                                Rectangle {
                                    Layout.preferredWidth: 46; Layout.preferredHeight: 46
                                    radius: 23
                                    color: Qt.rgba(Ui.agentColor(agentCard.modelData.id).r, Ui.agentColor(agentCard.modelData.id).g,
                                                   Ui.agentColor(agentCard.modelData.id).b, 0.18)
                                    Label {
                                        anchors.centerIn: parent
                                        text: agentCard.modelData.emoji
                                        font.pointSize: LingmoUI.Units.fontHeading
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0
                                    Label {
                                        Layout.fillWidth: true
                                        text: agentCard.modelData.name
                                        font.bold: true
                                        elide: Text.ElideRight
                                        color: LingmoUI.Theme.textColor
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: agentCard.modelData.model !== "" ? agentCard.modelData.model : qsTr("Model from Settings")
                                        elide: Text.ElideRight
                                        font.pointSize: LingmoUI.Units.fontCaption
                                        color: LingmoUI.Theme.secondaryTextColor
                                    }
                                }
                            }
                            Label {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                text: agentCard.modelData.description
                                wrapMode: Text.Wrap
                                elide: Text.ElideRight
                                color: LingmoUI.Theme.secondaryTextColor
                                font.pointSize: LingmoUI.Units.fontCaption
                            }
                            Flow {
                                Layout.fillWidth: true
                                spacing: 4
                                clip: true
                                Layout.maximumHeight: 24
                                Repeater {
                                    model: agentCard.modelData.tools.slice(0, 3)
                                    delegate: LingmoUI.Badge {
                                        required property string modelData
                                        text: assistant.toolTitle(modelData)
                                        subtle: true
                                    }
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Item { Layout.fillWidth: true }
                                LingmoUI.ActionButton {
                                    text: qsTr("Chat")
                                    iconName: "internet-chat"
                                    onClicked: assistant.chatWithAgent(agentCard.modelData.id)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
