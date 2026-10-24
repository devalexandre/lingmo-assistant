import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI
import Lingmo.Assistant

// Sidebar of the "Agentes" section
ColumnLayout {
    spacing: 0

    LingmoUI.SideBarItem {
        Layout.fillWidth: true
        Layout.leftMargin: LingmoUI.Units.largeSpacing
        Layout.rightMargin: LingmoUI.Units.largeSpacing
        title: qsTr("New agent")
        iconName: "list-add"
        onClicked: {
            assistant.section = "agents"
            Ui.editAgent({})
        }
    }

    Label {
        visible: agentList.count > 0
        text: qsTr("Your agents")
        color: LingmoUI.Theme.secondaryTextColor
        font.pointSize: LingmoUI.Units.fontCaption
        font.weight: Font.DemiBold
        leftPadding: LingmoUI.Units.largeSpacing + LingmoUI.Units.smallSpacing
        topPadding: LingmoUI.Units.largeSpacing
        bottomPadding: LingmoUI.Units.smallSpacing
    }

    ListView {
        id: agentList
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        model: assistant.agents
        spacing: LingmoUI.Units.smallSpacing / 2
        leftMargin: LingmoUI.Units.largeSpacing
        rightMargin: LingmoUI.Units.largeSpacing
        bottomMargin: LingmoUI.Units.largeSpacing
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        delegate: LingmoUI.SideBarItem {
            required property var modelData
            width: ListView.view.width - ListView.view.leftMargin - ListView.view.rightMargin
            title: modelData.name
            tileText: modelData.emoji
            tileColor: Ui.agentColor(modelData.id)
            isCurrent: assistant.section === "agents" && Ui.editingAgentId === modelData.id
            onClicked: Ui.editAgent(modelData)
        }
    }
}
