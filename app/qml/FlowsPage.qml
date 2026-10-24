import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI
import Lingmo.Assistant

// "Fluxos": the gallery (templates and saved workflows) or the editor
Item {
    id: page

    Loader {
        anchors.fill: parent
        active: assistant.flow.loaded
        sourceComponent: FlowEditor {}
    }

    // ------------------------------------------------------------ gallery
    Flickable {
        id: gallery
        anchors.fill: parent
        visible: !assistant.flow.loaded
        contentHeight: galleryColumn.implicitHeight + LingmoUI.Units.largeSpacing * 4
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        ColumnLayout {
            id: galleryColumn
            width: Math.min(gallery.width - LingmoUI.Units.largeSpacing * 6, 920)
            x: (gallery.width - width) / 2
            spacing: LingmoUI.Units.largeSpacing

            LingmoUI.PageHeader {
                Layout.fillWidth: true
                Layout.preferredHeight: LingmoUI.Units.windowHeaderHeight
                large: false
                title: qsTr("Workflows")
            }

            LingmoUI.Card {
                Layout.fillWidth: true
                implicitHeight: heroRow.implicitHeight + LingmoUI.Units.largeSpacing * 3

                RowLayout {
                    id: heroRow
                    anchors.fill: parent
                    anchors.margins: LingmoUI.Units.largeSpacing * 1.5
                    spacing: LingmoUI.Units.largeSpacing * 1.5

                    Rectangle {
                        Layout.preferredWidth: 64
                        Layout.preferredHeight: 64
                        radius: LingmoUI.Theme.hugeRadius
                        color: Qt.rgba(LingmoUI.Theme.highlightColor.r, LingmoUI.Theme.highlightColor.g,
                                       LingmoUI.Theme.highlightColor.b, 0.15)
                        LingmoUI.IconItem {
                            anchors.centerIn: parent
                            width: 36; height: 36
                            source: "code-branch"
                            color: LingmoUI.Theme.highlightColor
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: LingmoUI.Units.smallSpacing
                        Label {
                            text: qsTr("Automate your day with blocks")
                            font.pointSize: LingmoUI.Units.fontHeading
                            font.bold: true
                            color: LingmoUI.Theme.textColor
                        }
                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            color: LingmoUI.Theme.secondaryTextColor
                            text: qsTr("Pick a trigger, connect actions of your Lingmo apps and let the local AI write, summarise or decide. Nothing is ever deleted, and anything sent on your behalf asks you first.")
                        }
                    }

                    LingmoUI.ActionButton {
                        primary: true
                        text: qsTr("Blank workflow")
                        iconName: "list-add"
                        onClicked: assistant.newFlow("")
                    }
                }
            }

            Label {
                text: qsTr("Start from a template")
                font.pointSize: LingmoUI.Units.fontSubheading
                font.bold: true
                color: LingmoUI.Theme.textColor
                Layout.topMargin: LingmoUI.Units.largeSpacing
            }

            GridLayout {
                Layout.fillWidth: true
                columns: width > 700 ? 3 : 2
                columnSpacing: LingmoUI.Units.largeSpacing
                rowSpacing: LingmoUI.Units.largeSpacing

                Repeater {
                    model: assistant.templates
                    delegate: LingmoUI.Card {
                        id: templateCard
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredWidth: 200
                        implicitHeight: 150
                        clickable: true
                        liftOnHover: true
                        onClicked: assistant.newFlow(modelData.template)

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: LingmoUI.Units.largeSpacing * 1.2
                            spacing: LingmoUI.Units.smallSpacing

                            Rectangle {
                                Layout.preferredWidth: 36
                                Layout.preferredHeight: 36
                                radius: LingmoUI.Theme.mediumRadius
                                color: Ui.color("triggers")
                                LingmoUI.IconItem {
                                    anchors.centerIn: parent
                                    width: 20; height: 20
                                    source: templateCard.modelData.icon
                                    color: "white"
                                }
                            }
                            Label {
                                Layout.fillWidth: true
                                text: templateCard.modelData.name
                                font.bold: true
                                wrapMode: Text.Wrap
                                maximumLineCount: 2
                                elide: Text.ElideRight
                                color: LingmoUI.Theme.textColor
                            }
                            Label {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                text: templateCard.modelData.description
                                wrapMode: Text.Wrap
                                elide: Text.ElideRight
                                color: LingmoUI.Theme.secondaryTextColor
                                font.pointSize: LingmoUI.Units.fontCaption
                            }
                        }
                    }
                }
            }

            Label {
                visible: assistant.flows.length > 0
                text: qsTr("Your workflows")
                font.pointSize: LingmoUI.Units.fontSubheading
                font.bold: true
                color: LingmoUI.Theme.textColor
                Layout.topMargin: LingmoUI.Units.largeSpacing
            }

            Repeater {
                model: assistant.flows
                delegate: LingmoUI.Card {
                    id: flowCard
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: flowRow.implicitHeight + LingmoUI.Units.largeSpacing * 2
                    clickable: true
                    onClicked: assistant.openFlow(modelData.id)

                    RowLayout {
                        id: flowRow
                        anchors.fill: parent
                        anchors.leftMargin: flowCard.padding
                        anchors.rightMargin: flowCard.padding
                        spacing: LingmoUI.Units.largeSpacing

                        Rectangle {
                            Layout.preferredWidth: 36
                            Layout.preferredHeight: 36
                            radius: LingmoUI.Theme.mediumRadius
                            color: flowCard.modelData.enabled ? Ui.color("triggers") : LingmoUI.Theme.greyColor
                            LingmoUI.IconItem {
                                anchors.centerIn: parent
                                width: 20; height: 20
                                source: Ui.triggerIcon(flowCard.modelData.trigger_type)
                                color: "white"
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Label {
                                text: flowCard.modelData.name
                                font.bold: true
                                color: LingmoUI.Theme.textColor
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            Label {
                                text: flowCard.modelData.trigger_text
                                color: LingmoUI.Theme.secondaryTextColor
                                font.pointSize: LingmoUI.Units.fontCaption
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                        }
                        LingmoUI.Badge {
                            visible: !flowCard.modelData.approved
                            text: qsTr("Needs approval")
                            tone: LingmoUI.Theme.orangeColor
                            subtle: true
                        }
                        LingmoUI.Badge {
                            visible: flowCard.modelData.background && flowCard.modelData.enabled
                            text: qsTr("Runs in the background")
                            subtle: true
                        }
                        Switch {
                            checked: flowCard.modelData.enabled
                            onToggled: assistant.setFlowEnabled(flowCard.modelData.id, checked)
                        }
                    }
                }
            }
        }
    }
}
