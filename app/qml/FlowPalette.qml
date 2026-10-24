import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI
import Lingmo.Assistant

// The blocks you can add, by category. Drag one onto the canvas, or click to
// add it next to the selected block (connected to it).
Item {
    id: blockPalette
    property var editor
    property string filter: ""

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: LingmoUI.Units.largeSpacing
        spacing: LingmoUI.Units.smallSpacing

        TextField {
            Layout.fillWidth: true
            placeholderText: qsTr("Search blocks")
            onTextChanged: blockPalette.filter = text
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 4
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            model: { assistant.flow.catalogue; return assistant.flow.palette(blockPalette.filter) }
            // "actions|Relógio": the actions are grouped by app (Lingmo Intents)
            section.property: "section"
            section.delegate: Label {
                required property string section
                readonly property string category: section.split("|")[0]
                readonly property string app: section.indexOf("|") >= 0 ? section.slice(section.indexOf("|") + 1) : ""
                width: ListView.view.width
                topPadding: LingmoUI.Units.largeSpacing
                bottomPadding: 4
                text: {
                    let label = category
                    for (const c of assistant.categories)
                        if (c.id === category)
                            label = c.label
                    return app !== "" ? label + " · " + app : label
                }
                font.pointSize: LingmoUI.Units.fontCaption
                font.weight: Font.DemiBold
                color: Ui.color(category)
            }

            delegate: Rectangle {
                id: item
                required property var modelData
                width: ListView.view.width
                height: 44
                radius: LingmoUI.Theme.mediumRadius
                color: itemHover.hovered ? LingmoUI.Theme.hoverColor : "transparent"
                Behavior on color { ColorAnimation { duration: LingmoUI.Units.shortDuration } }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 6
                    anchors.rightMargin: 6
                    spacing: 8
                    Rectangle {
                        Layout.preferredWidth: 28; Layout.preferredHeight: 28
                        radius: LingmoUI.Theme.smallRadius
                        color: Ui.color(item.modelData.category)
                        LingmoUI.IconItem { anchors.centerIn: parent; width: 16; height: 16; source: item.modelData.icon; color: "white" }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        Label {
                            Layout.fillWidth: true
                            text: item.modelData.label
                            elide: Text.ElideRight
                            color: LingmoUI.Theme.textColor
                            font.pointSize: LingmoUI.Units.fontBody
                        }
                        Label {
                            // grouped by app already (section): show what it does instead
                            readonly property bool byApp: (item.modelData.section || "").indexOf("|") >= 0
                            Layout.fillWidth: true
                            visible: text !== ""
                            text: byApp ? item.modelData.description : item.modelData.group
                            elide: Text.ElideRight
                            color: LingmoUI.Theme.secondaryTextColor
                            font.pointSize: LingmoUI.Units.fontCaption
                        }
                    }
                    LingmoUI.IconItem {
                        Layout.preferredWidth: 14; Layout.preferredHeight: 14
                        visible: item.modelData.capability && item.modelData.capability.external
                        source: "mail-send"
                        color: LingmoUI.Theme.orangeColor
                    }
                }

                // keeps the press from reaching the window's move area (see FlowEditor)
                MouseArea { anchors.fill: parent; z: -1; acceptedButtons: Qt.LeftButton }
                HoverHandler { id: itemHover; cursorShape: Qt.OpenHandCursor }
                ToolTip.visible: itemHover.hovered && !drag.active
                ToolTip.delay: 600
                ToolTip.text: item.modelData.description

                TapHandler { onTapped: blockPalette.editor.paletteAdd(item.modelData.type) }
                DragHandler {
                    id: drag
                    target: null
                    onActiveChanged: blockPalette.editor.paletteDrag(item.modelData.type, item.modelData, item, centroid.position, active)
                    onCentroidChanged: if (active) blockPalette.editor.paletteDrag(item.modelData.type, item.modelData, item, centroid.position, true)
                }
            }
        }
    }
}
