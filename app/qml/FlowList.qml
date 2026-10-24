import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI
import Lingmo.Assistant

// Sidebar of the "Fluxos" section: new, import, and the saved workflows
ColumnLayout {
    spacing: 0

    LingmoUI.SideBarItem {
        Layout.fillWidth: true
        Layout.leftMargin: LingmoUI.Units.largeSpacing
        Layout.rightMargin: LingmoUI.Units.largeSpacing
        title: qsTr("New workflow")
        iconName: "list-add"
        isCurrent: assistant.section === "flows" && !assistant.flow.loaded
        onClicked: {
            assistant.section = "flows"
            assistant.closeFlow()
        }
    }

    LingmoUI.SideBarItem {
        Layout.fillWidth: true
        Layout.leftMargin: LingmoUI.Units.largeSpacing
        Layout.rightMargin: LingmoUI.Units.largeSpacing
        title: qsTr("Import…")
        iconName: "document-import"
        onClicked: importDialog.open()
    }

    Label {
        visible: flowList.count > 0
        text: qsTr("Your workflows")
        color: LingmoUI.Theme.secondaryTextColor
        font.pointSize: LingmoUI.Units.fontCaption
        font.weight: Font.DemiBold
        leftPadding: LingmoUI.Units.largeSpacing + LingmoUI.Units.smallSpacing
        topPadding: LingmoUI.Units.largeSpacing
        bottomPadding: LingmoUI.Units.smallSpacing
    }

    ListView {
        id: flowList
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        model: assistant.flows
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
            iconName: Ui.triggerIcon(modelData.trigger_type)
            tileColor: modelData.enabled ? Ui.color("triggers") : LingmoUI.Theme.greyColor
            trailing: !modelData.enabled ? qsTr("off") : !modelData.approved ? qsTr("review") : ""
            isCurrent: assistant.section === "flows" && assistant.flow.flowId === modelData.id
            onClicked: assistant.openFlow(modelData.id)
        }
    }

    Item { Layout.fillHeight: flowList.count === 0 }

    FileDialog {
        id: importDialog
        title: qsTr("Import a workflow")
        nameFilters: [qsTr("Workflows (*.json)")]
        onAccepted: {
            assistant.section = "flows"
            assistant.closeFlow()
            assistant.importFlow(selectedFile)
        }
    }
}
