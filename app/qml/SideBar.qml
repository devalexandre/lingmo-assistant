import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI

// Conversations on the left, in the style of Lingmo Settings' SideBar
Item {
    id: control

    implicitWidth: 240

    Rectangle {
        anchors.fill: parent
        // Same panel tone as Lingmo Settings and Lingmo Store
        color: LingmoUI.Theme.darkMode ? Qt.rgba(0.11, 0.11, 0.15, 0.55) : "#EDEEF2"

        Behavior on color {
            ColorAnimation { duration: 250; easing.type: Easing.Linear }
        }
    }

    component SideItem: Item {
        id: sideItem

        property string text
        property string iconName
        property bool selected: false
        property bool showDelete: false
        signal clicked()
        signal deleteClicked()

        width: ListView.view ? ListView.view.width - ListView.view.leftMargin - ListView.view.rightMargin
                             : parent.width
        height: LingmoUI.Units.fontMetrics.height + LingmoUI.Units.largeSpacing * 1.5

        Rectangle {
            anchors.fill: parent
            radius: LingmoUI.Theme.mediumRadius
            color: sideItem.selected ? LingmoUI.Theme.highlightColor
                 : mouseArea.containsMouse ? Qt.rgba(LingmoUI.Theme.textColor.r, LingmoUI.Theme.textColor.g,
                                                     LingmoUI.Theme.textColor.b, 0.1)
                 : "transparent"

            Behavior on color { ColorAnimation { duration: 120 } }
        }

        MouseArea {
            id: mouseArea
            anchors.fill: parent
            hoverEnabled: true
            onClicked: sideItem.clicked()
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: LingmoUI.Units.largeSpacing
            anchors.rightMargin: LingmoUI.Units.smallSpacing
            spacing: LingmoUI.Units.smallSpacing * 1.5

            LingmoUI.IconItem {
                visible: sideItem.iconName !== ""
                Layout.preferredWidth: LingmoUI.Units.iconSizes.small
                Layout.preferredHeight: LingmoUI.Units.iconSizes.small
                source: sideItem.iconName
            }

            Label {
                text: sideItem.text
                color: sideItem.selected ? LingmoUI.Theme.highlightedTextColor : LingmoUI.Theme.textColor
                elide: Text.ElideRight
                Layout.fillWidth: true
            }

            IconButton {
                visible: sideItem.showDelete && (mouseArea.containsMouse || hovered)
                iconName: "edit-delete"
                tipText: qsTr("Delete conversation")
                implicitWidth: LingmoUI.Units.iconSizes.smallMedium + 4
                implicitHeight: implicitWidth
                onClicked: sideItem.deleteClicked()
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // The window's buttons sit in this strip
        Item { Layout.preferredHeight: rootWindow.header.height }

        Label {
            text: rootWindow.title
            color: rootWindow.active ? LingmoUI.Theme.textColor : LingmoUI.Theme.disabledTextColor
            leftPadding: LingmoUI.Units.largeSpacing + LingmoUI.Units.smallSpacing
            rightPadding: LingmoUI.Units.largeSpacing + LingmoUI.Units.smallSpacing
            topPadding: 2
            bottomPadding: LingmoUI.Units.smallSpacing * 1.5
            font.pointSize: 17
            font.bold: true
            fontSizeMode: Text.HorizontalFit
            minimumPointSize: 12
            Layout.fillWidth: true
        }

        SideItem {
            Layout.fillWidth: true
            Layout.leftMargin: LingmoUI.Units.largeSpacing
            Layout.rightMargin: LingmoUI.Units.largeSpacing
            text: qsTr("New conversation")
            iconName: "document-new"
            selected: assistant.messages.count === 0
            onClicked: {
                assistant.newConversation()
                rootWindow.focusComposer()
            }
        }

        Label {
            visible: conversationList.count > 0
            text: qsTr("History")
            color: LingmoUI.Theme.disabledTextColor
            font.pointSize: LingmoUI.Theme.fontSize * 0.9
            leftPadding: LingmoUI.Units.largeSpacing * 2
            topPadding: LingmoUI.Units.largeSpacing
            bottomPadding: LingmoUI.Units.smallSpacing
        }

        ListView {
            id: conversationList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: assistant.conversations
            spacing: LingmoUI.Units.smallSpacing / 2
            leftMargin: LingmoUI.Units.largeSpacing
            rightMargin: LingmoUI.Units.largeSpacing
            bottomMargin: LingmoUI.Units.largeSpacing
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}

            LingmoUI.WheelHandler { target: conversationList }

            delegate: SideItem {
                required property string conversationId
                required property string title
                text: title
                showDelete: true
                selected: conversationId === assistant.conversationId && assistant.messages.count > 0
                onClicked: assistant.openConversation(conversationId)
                onDeleteClicked: assistant.deleteConversation(conversationId)
            }
        }
    }
}
