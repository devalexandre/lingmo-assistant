import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI
import Lingmo.Assistant

LingmoUI.Window {
    id: rootWindow
    width: 1360
    height: 840
    minimumWidth: 820
    minimumHeight: 580
    title: qsTr("Assistant")
    visible: !startHidden

    // Same window look as Lingmo Settings
    background.opacity: LingmoUI.Theme.darkMode ? 0.88 : 0.97
    header.height: LingmoUI.Units.windowHeaderHeight
    contentTopMargin: 0

    LingmoUI.WindowBlur {
        view: rootWindow
        geometry: Qt.rect(rootWindow.x, rootWindow.y, rootWindow.width, rootWindow.height)
        windowRadius: rootWindow.windowRadius
        enabled: true
    }

    // The model and permissions are chosen in Lingmo Settings: pick up changes
    onActiveChanged: if (active) assistant.refresh()

    readonly property var sections: ["chat", "flows", "agents"]

    function focusComposer() { chatPage.focusComposer() }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ------------------------------------------------------------ sidebar
        Item {
            id: sideBar
            Layout.fillHeight: true
            implicitWidth: LingmoUI.Units.sideBarWidth

            Rectangle {
                anchors.fill: parent
                color: LingmoUI.Theme.sideBarColor
                Behavior on color {
                    ColorAnimation { duration: LingmoUI.Units.longDuration; easing.type: Easing.Linear }
                }
            }

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                // The window's buttons sit in this strip
                Item { Layout.preferredHeight: rootWindow.header.height }

                Label {
                    text: rootWindow.title
                    color: rootWindow.active ? LingmoUI.Theme.textColor : LingmoUI.Theme.secondaryTextColor
                    leftPadding: LingmoUI.Units.largeSpacing + LingmoUI.Units.smallSpacing
                    rightPadding: LingmoUI.Units.largeSpacing + LingmoUI.Units.smallSpacing
                    topPadding: 2
                    bottomPadding: LingmoUI.Units.smallSpacing * 1.5
                    font.pointSize: LingmoUI.Units.fontTitle
                    font.bold: true
                    fontSizeMode: Text.HorizontalFit
                    minimumPointSize: LingmoUI.Units.fontSubheading
                    Layout.fillWidth: true
                }

                LingmoUI.SegmentedControl {
                    Layout.fillWidth: true
                    Layout.leftMargin: LingmoUI.Units.largeSpacing
                    Layout.rightMargin: LingmoUI.Units.largeSpacing
                    Layout.bottomMargin: LingmoUI.Units.largeSpacing
                    fillWidth: true
                    model: [qsTr("Chat"), qsTr("Workflows"), qsTr("Agents")]
                    currentIndex: Math.max(0, rootWindow.sections.indexOf(assistant.section))
                    onActivated: (index) => assistant.section = rootWindow.sections[index]
                }

                StackLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: assistant.section === "flows" ? 1 : assistant.section === "agents" ? 2 : 0

                    // Conversations
                    ColumnLayout {
                        spacing: 0

                        LingmoUI.SideBarItem {
                            Layout.fillWidth: true
                            Layout.leftMargin: LingmoUI.Units.largeSpacing
                            Layout.rightMargin: LingmoUI.Units.largeSpacing
                            title: qsTr("New conversation")
                            iconName: "document-new"
                            isCurrent: assistant.section === "chat" && assistant.messages.count === 0
                            onClicked: {
                                assistant.section = "chat"
                                assistant.newConversation()
                                rootWindow.focusComposer()
                            }
                        }

                        Label {
                            visible: conversationList.count > 0
                            text: qsTr("History")
                            color: LingmoUI.Theme.secondaryTextColor
                            font.pointSize: LingmoUI.Units.fontCaption
                            font.weight: Font.DemiBold
                            leftPadding: LingmoUI.Units.largeSpacing + LingmoUI.Units.smallSpacing
                            topPadding: LingmoUI.Units.largeSpacing
                            bottomPadding: LingmoUI.Units.smallSpacing
                        }

                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true

                            ListView {
                                id: conversationList
                                anchors.fill: parent
                                clip: true
                                model: assistant.conversations
                                spacing: LingmoUI.Units.smallSpacing / 2
                                leftMargin: LingmoUI.Units.largeSpacing
                                rightMargin: LingmoUI.Units.largeSpacing
                                bottomMargin: LingmoUI.Units.largeSpacing
                                boundsBehavior: Flickable.StopAtBounds
                                ScrollBar.vertical: ScrollBar {}

                                LingmoUI.WheelHandler { target: conversationList }

                                delegate: LingmoUI.SideBarItem {
                                    id: conversationItem
                                    required property var model
                                    readonly property string conversationId: model.conversationId

                                    width: ListView.view.width - ListView.view.leftMargin - ListView.view.rightMargin
                                    title: model.title
                                    isCurrent: assistant.section === "chat" && conversationId === assistant.conversationId
                                               && assistant.messages.count > 0
                                    onClicked: {
                                        assistant.section = "chat"
                                        assistant.openConversation(conversationId)
                                    }

                                    LingmoUI.IconButton {
                                        visible: conversationItem.hovered || hovered
                                        iconName: "edit-delete"
                                        tipText: qsTr("Delete conversation")
                                        size: LingmoUI.Units.iconSizes.smallMedium + 4
                                        onClicked: assistant.deleteConversation(conversationItem.conversationId)
                                    }
                                }
                            }

                            LingmoUI.EmptyState {
                                visible: conversationList.count === 0
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.verticalCenterOffset: -LingmoUI.Units.largeSpacing * 3
                                anchors.leftMargin: LingmoUI.Units.largeSpacing * 1.5
                                anchors.rightMargin: LingmoUI.Units.largeSpacing * 1.5
                                iconName: "document-open-recent"
                                iconSize: LingmoUI.Units.iconSizes.large
                                text: qsTr("Your conversations will appear here.")
                            }
                        }
                    }

                    // Workflows
                    FlowList {}

                    // Agents
                    AgentList {}
                }

                LingmoUI.SideBarItem {
                    Layout.fillWidth: true
                    Layout.leftMargin: LingmoUI.Units.largeSpacing
                    Layout.rightMargin: LingmoUI.Units.largeSpacing
                    Layout.bottomMargin: LingmoUI.Units.largeSpacing
                    title: qsTr("Voice and settings")
                    iconName: "preferences-system"
                    isCurrent: assistant.section === "settings"
                    onClicked: assistant.section = "settings"
                }
            }
        }

        // ------------------------------------------------------------ pages
        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: ["chat", "flows", "agents", "settings"].indexOf(assistant.section)

            ChatPage { id: chatPage }
            FlowsPage {}
            AgentsPage {}
            SettingsPage {}
        }
    }

    // ------------------------------------------------------------ shared overlays

    ApprovalDialog { id: approvalDialog }

    Connections {
        target: Ui
        function onApprovalRequested(info) { approvalDialog.openFor(info) }
    }

    Connections {
        target: assistant
        function onApprovalNeeded(info) { approvalDialog.openFor(info) }
        function onToast(message) { LingmoUI.Toast.showNotification(message, 3500) }
    }

    // Push-to-talk pill (global shortcut Meta+Shift+I or the microphone button)
    VoicePill {}
}
