import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI
import Lingmo.Assistant

// Create or edit an agent
Item {
    id: editor

    readonly property var source: Ui.editingAgent || ({})
    readonly property bool isNew: !source.id
    property string emoji: source.emoji || "🤖"
    property var tools: source.tools ? source.tools.slice() : ["read_files", "search_files", "notes_read"]
    property var knowledge: source.knowledge ? source.knowledge.slice() : []
    property string model: source.model || ""
    property real temperature: source.temperature !== undefined ? source.temperature : 0.7
    property var think: source.think === undefined ? null : source.think

    readonly property var emojis: ["🤖", "📧", "🗓️", "📄", "✍️", "🧠", "💼", "📊", "🧾", "🛒", "🎓", "🧑‍💻", "🌍", "🎨", "⚖️", "🩺"]

    Component.onCompleted: assistant.refreshModels()

    function save() {
        const agent = {
            id: source.id || "", name: nameField.text, emoji: emoji, description: descField.text,
            instructions: instructions.text, model: model, tools: tools, knowledge: knowledge,
            temperature: temperature, think: think, starter: source.starter || false
        }
        assistant.saveAgent(agent)
    }

    Connections {
        target: assistant
        function onAgentSaved(id) { Ui.closeAgentEditor() }
    }

    function toggleTool(id, on) {
        let t = tools.slice()
        const i = t.indexOf(id)
        if (on && i < 0) t.push(id)
        if (!on && i >= 0) t.splice(i, 1)
        tools = t
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: LingmoUI.Units.windowHeaderHeight + LingmoUI.Units.smallSpacing
            Layout.leftMargin: LingmoUI.Units.largeSpacing
            Layout.rightMargin: LingmoUI.Units.largeSpacing * 4
            spacing: LingmoUI.Units.smallSpacing
            LingmoUI.IconButton { iconName: "go-previous"; tipText: qsTr("All agents"); onClicked: Ui.closeAgentEditor() }
            Label {
                Layout.fillWidth: true
                text: editor.isNew ? qsTr("New agent") : editor.source.name
                font.pointSize: LingmoUI.Units.fontSubheading
                font.bold: true
                color: LingmoUI.Theme.textColor
                elide: Text.ElideRight
            }
            LingmoUI.ActionButton {
                visible: !editor.isNew
                text: qsTr("Chat")
                iconName: "internet-chat"
                onClicked: { assistant.chatWithAgent(editor.source.id); Ui.closeAgentEditor() }
            }
            LingmoUI.ActionButton {
                primary: true
                text: qsTr("Save")
                iconName: "document-save"
                enabled: nameField.text.trim() !== ""
                onClicked: editor.save()
            }
        }

        Flickable {
            id: flick
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: form.implicitHeight + LingmoUI.Units.largeSpacing * 3
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}

            ColumnLayout {
                id: form
                width: Math.min(flick.width - LingmoUI.Units.largeSpacing * 6, 760)
                x: (flick.width - width) / 2
                y: LingmoUI.Units.largeSpacing
                spacing: LingmoUI.Units.largeSpacing

                // ------------------------------------------------------------ identity
                LingmoUI.Card {
                    Layout.fillWidth: true
                    implicitHeight: identity.implicitHeight + LingmoUI.Units.largeSpacing * 3
                    ColumnLayout {
                        id: identity
                        anchors.fill: parent
                        anchors.margins: LingmoUI.Units.largeSpacing * 1.5
                        spacing: LingmoUI.Units.largeSpacing
                        RowLayout {
                            spacing: LingmoUI.Units.largeSpacing
                            Rectangle {
                                Layout.preferredWidth: 64; Layout.preferredHeight: 64
                                radius: 32
                                color: Qt.rgba(Ui.agentColor(editor.source.id || nameField.text).r, Ui.agentColor(editor.source.id || nameField.text).g,
                                               Ui.agentColor(editor.source.id || nameField.text).b, 0.18)
                                Label { anchors.centerIn: parent; text: editor.emoji; font.pointSize: LingmoUI.Units.fontDisplay }
                                MouseArea { anchors.fill: parent; onClicked: emojiPopup.open() }
                                Popup {
                                    id: emojiPopup
                                    y: parent.height + 4
                                    padding: 8
                                    background: Rectangle { radius: LingmoUI.Theme.mediumRadius; color: LingmoUI.Theme.secondBackgroundColor; border.color: LingmoUI.Theme.borderColor }
                                    contentItem: GridLayout {
                                        columns: 8
                                        Repeater {
                                            model: editor.emojis
                                            delegate: Label {
                                                required property string modelData
                                                text: modelData
                                                font.pointSize: LingmoUI.Units.fontHeading
                                                padding: 4
                                                MouseArea { anchors.fill: parent; onClicked: { editor.emoji = modelData; emojiPopup.close() } }
                                            }
                                        }
                                    }
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: LingmoUI.Units.smallSpacing
                                Label { text: qsTr("Name"); font.pointSize: LingmoUI.Units.fontCaption; font.weight: Font.DemiBold; color: LingmoUI.Theme.secondaryTextColor }
                                TextField { id: nameField; Layout.fillWidth: true; text: editor.source.name || ""; placeholderText: qsTr("E.g. Travel planner") }
                                Label { text: qsTr("Description"); font.pointSize: LingmoUI.Units.fontCaption; font.weight: Font.DemiBold; color: LingmoUI.Theme.secondaryTextColor }
                                TextField { id: descField; Layout.fillWidth: true; text: editor.source.description || ""; placeholderText: qsTr("What it helps with") }
                            }
                        }
                        Label { text: qsTr("Instructions"); font.pointSize: LingmoUI.Units.fontCaption; font.weight: Font.DemiBold; color: LingmoUI.Theme.secondaryTextColor }
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: Math.min(Math.max(instructions.implicitHeight, 140), 320)
                            radius: LingmoUI.Theme.smallRadius
                            color: LingmoUI.Theme.alternateBackgroundColor
                            border.width: instructions.activeFocus ? 1.5 : 0
                            border.color: LingmoUI.Theme.highlightColor
                            ScrollView {
                                anchors.fill: parent
                                TextArea {
                                    id: instructions
                                    text: editor.source.instructions || ""
                                    wrapMode: TextArea.Wrap
                                    placeholderText: qsTr("How it should behave: role, tone, what to always do and never do…")
                                    background: Item {}
                                }
                            }
                        }
                    }
                }

                // ------------------------------------------------------------ model
                LingmoUI.Card {
                    Layout.fillWidth: true
                    implicitHeight: modelColumn.implicitHeight + LingmoUI.Units.largeSpacing * 3
                    ColumnLayout {
                        id: modelColumn
                        anchors.fill: parent
                        anchors.margins: LingmoUI.Units.largeSpacing * 1.5
                        spacing: LingmoUI.Units.smallSpacing
                        Label { text: qsTr("Model"); font.bold: true; color: LingmoUI.Theme.textColor }
                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            text: qsTr("Installed Ollama models. To use tools the model needs the “Tools” tag.")
                            font.pointSize: LingmoUI.Units.fontCaption
                            color: LingmoUI.Theme.secondaryTextColor
                        }
                        ButtonGroup { id: modelGroup }
                        RadioButton {
                            text: qsTr("The model chosen in Settings")
                            checked: editor.model === ""
                            ButtonGroup.group: modelGroup
                            onToggled: if (checked) editor.model = ""
                        }
                        Repeater {
                            model: assistant.models.filter(m => !m.embedding)
                            delegate: RowLayout {
                                required property var modelData
                                spacing: LingmoUI.Units.smallSpacing
                                RadioButton {
                                    text: modelData.name
                                    checked: editor.model === modelData.name
                                    ButtonGroup.group: modelGroup
                                    onToggled: if (checked) editor.model = modelData.name
                                }
                                Repeater {
                                    model: modelData.tags
                                    delegate: LingmoUI.Badge {
                                        required property var modelData
                                        text: modelData.text
                                        tone: modelData.id === "tools" ? LingmoUI.Theme.greenColor
                                            : modelData.id === "thinking" ? LingmoUI.Theme.purpleColor
                                            : modelData.id === "fast" ? LingmoUI.Theme.orangeColor : LingmoUI.Theme.highlightColor
                                        subtle: true
                                    }
                                }
                                LingmoUI.Badge {
                                    visible: modelData.in_use
                                    text: qsTr("In Settings")
                                    subtle: true
                                }
                            }
                        }
                        Label {
                            visible: assistant.models.length === 0
                            text: qsTr("Ollama isn't answering: the model from Settings will be used.")
                            font.pointSize: LingmoUI.Units.fontCaption
                            color: LingmoUI.Theme.secondaryTextColor
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.topMargin: LingmoUI.Units.largeSpacing
                            Label { text: qsTr("Creativity"); color: LingmoUI.Theme.textColor }
                            Slider {
                                id: tempSlider
                                Layout.fillWidth: true
                                from: 0; to: 1.5; stepSize: 0.1
                                value: editor.temperature
                                onMoved: editor.temperature = Math.round(value * 10) / 10
                            }
                            Label {
                                Layout.preferredWidth: 90
                                text: editor.temperature <= 0.3 ? qsTr("Precise") : editor.temperature <= 0.8 ? qsTr("Balanced") : qsTr("Creative")
                                color: LingmoUI.Theme.secondaryTextColor
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: qsTr("Reasoning (think)"); color: LingmoUI.Theme.textColor; Layout.fillWidth: true }
                            ComboBox {
                                Layout.preferredWidth: 220
                                model: [qsTr("As in Settings"), qsTr("On"), qsTr("Off")]
                                currentIndex: editor.think === null ? 0 : editor.think ? 1 : 2
                                onActivated: (i) => editor.think = i === 0 ? null : i === 1
                            }
                        }
                    }
                }

                // ------------------------------------------------------------ tools
                LingmoUI.Card {
                    Layout.fillWidth: true
                    implicitHeight: toolsColumn.implicitHeight + LingmoUI.Units.largeSpacing * 3
                    ColumnLayout {
                        id: toolsColumn
                        anchors.fill: parent
                        anchors.margins: LingmoUI.Units.largeSpacing * 1.5
                        spacing: LingmoUI.Units.smallSpacing
                        Label { text: qsTr("Tools"); font.bold: true; color: LingmoUI.Theme.textColor }
                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            text: qsTr("What this agent may use. Tools turned off in Settings › AI stay off, and every change still asks for your permission.")
                            font.pointSize: LingmoUI.Units.fontCaption
                            color: LingmoUI.Theme.secondaryTextColor
                        }
                        Repeater {
                            model: assistant.agentTools
                            delegate: RowLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: LingmoUI.Units.largeSpacing
                                CheckBox {
                                    checked: editor.tools.indexOf(modelData.id) >= 0
                                    onToggled: editor.toggleTool(modelData.id, checked)
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0
                                    RowLayout {
                                        Label { text: assistant.toolTitle(modelData.id); color: modelData.enabled ? LingmoUI.Theme.textColor : LingmoUI.Theme.secondaryTextColor }
                                        LingmoUI.Badge {
                                            text: modelData.group === "write" ? qsTr("writes") : qsTr("reads")
                                            tone: modelData.group === "write" ? LingmoUI.Theme.orangeColor : LingmoUI.Theme.highlightColor
                                            subtle: true
                                        }
                                        LingmoUI.Badge {
                                            visible: !modelData.enabled
                                            text: qsTr("off in Settings")
                                            tone: LingmoUI.Theme.greyColor
                                            subtle: true
                                        }
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: assistant.toolDescription(modelData.id)
                                        wrapMode: Text.Wrap
                                        font.pointSize: LingmoUI.Units.fontCaption
                                        color: LingmoUI.Theme.secondaryTextColor
                                    }
                                }
                            }
                        }
                    }
                }

                // ------------------------------------------------------------ knowledge
                LingmoUI.Card {
                    Layout.fillWidth: true
                    implicitHeight: knowColumn.implicitHeight + LingmoUI.Units.largeSpacing * 3
                    ColumnLayout {
                        id: knowColumn
                        anchors.fill: parent
                        anchors.margins: LingmoUI.Units.largeSpacing * 1.5
                        spacing: LingmoUI.Units.smallSpacing
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: qsTr("Knowledge"); font.bold: true; color: LingmoUI.Theme.textColor; Layout.fillWidth: true }
                            LingmoUI.ActionButton { text: qsTr("Add folder…"); iconName: "folder-new"; onClicked: knowledgeDialog.open() }
                        }
                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            text: qsTr("Folders the agent searches (read only) before answering, with the local embedding model. Only folders allowed in Settings › AI are used.")
                            font.pointSize: LingmoUI.Units.fontCaption
                            color: LingmoUI.Theme.secondaryTextColor
                        }
                        Repeater {
                            model: editor.knowledge
                            delegate: RowLayout {
                                required property string modelData
                                required property int index
                                Layout.fillWidth: true
                                LingmoUI.IconItem { Layout.preferredWidth: 18; Layout.preferredHeight: 18; source: "folder" }
                                Label { Layout.fillWidth: true; text: modelData; elide: Text.ElideMiddle; color: LingmoUI.Theme.textColor }
                                LingmoUI.IconButton {
                                    iconName: "list-remove"
                                    tipText: qsTr("Remove from the list")
                                    onClicked: { let k = editor.knowledge.slice(); k.splice(index, 1); editor.knowledge = k }
                                }
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    visible: !editor.isNew
                    Item { Layout.fillWidth: true }
                    LingmoUI.ActionButton {
                        text: qsTr("Remove agent")
                        iconName: "edit-delete"
                        destructive: true
                        subtle: true
                        onClicked: { assistant.removeAgent(editor.source.id); Ui.closeAgentEditor() }
                    }
                }
            }
        }
    }

    FolderDialog {
        id: knowledgeDialog
        title: qsTr("Knowledge folder")
        onAccepted: {
            const path = decodeURIComponent(selectedFolder.toString().replace(/^file:\/\//, ""))
            if (editor.knowledge.indexOf(path) < 0)
                editor.knowledge = editor.knowledge.concat([path])
        }
    }
}
