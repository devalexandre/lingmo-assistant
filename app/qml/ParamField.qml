import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI
import Lingmo.Assistant

// One parameter of a block, with the right editor for its kind. Text fields
// take {{node.output}} templates: typing "{{" (or the {x} button) lists what
// earlier blocks produce.
ColumnLayout {
    id: field

    required property var param          // {name, label, kind, default, options, placeholder, help, template}
    property var value
    property string nodeId
    property var editor
    signal edited(var value)

    spacing: 4

    readonly property var doc: assistant.flow
    readonly property bool isText: ["text", "textarea", "path", "key", "time", "number", "language"].indexOf(param.kind) >= 0

    function insertVariable(text) {
        const target = textLoader.item
        if (!target || !target.input)
            return
        const input = target.input
        let pos = input.cursorPosition
        let t = input.text
        // replace an unfinished "{{" before the cursor
        const open = t.lastIndexOf("{{", pos)
        if (open >= 0 && t.indexOf("}}", open) < 0 && pos - open <= 40) {
            t = t.slice(0, open) + text + t.slice(pos)
            pos = open + text.length
        } else {
            t = t.slice(0, pos) + text + t.slice(pos)
            pos += text.length
        }
        input.text = t
        input.cursorPosition = pos
        field.edited(t)
        input.forceActiveFocus()
    }

    RowLayout {
        Layout.fillWidth: true
        Label {
            Layout.fillWidth: true
            text: field.param.label + (field.param.required ? " *" : "")
            font.pointSize: LingmoUI.Units.fontCaption
            font.weight: Font.DemiBold
            color: LingmoUI.Theme.secondaryTextColor
            elide: Text.ElideRight
        }
        LingmoUI.IconButton {
            visible: field.param.template === true || field.param.kind === "number" || field.param.kind === "time"
            iconName: "code-context"
            tipText: qsTr("Insert a value from an earlier block")
            size: 22
            iconSize: 14
            onClicked: variableMenu.openAt(this)
        }
    }

    // ------------------------------------------------------------ text kinds
    Loader {
        id: textLoader
        Layout.fillWidth: true
        active: field.isText
        sourceComponent: field.param.kind === "textarea" ? areaComponent : lineComponent
    }

    Component {
        id: lineComponent
        Item {
            property alias input: line
            implicitHeight: line.implicitHeight
            TextField {
                id: line
                anchors.left: parent.left
                anchors.right: parent.right
                text: field.value === undefined || field.value === null ? "" : String(field.value)
                placeholderText: field.param.placeholder || (field.param.kind === "time" ? "07:30" : field.param.kind === "key" ? "Meta+Shift+F" : "")
                onTextEdited: {
                    field.edited(field.param.kind === "number" && text !== "" && !isNaN(Number(text)) ? Number(text) : text)
                    if (text.slice(Math.max(0, cursorPosition - 2), cursorPosition) === "{{")
                        variableMenu.openAt(line)
                }
            }
        }
    }

    Component {
        id: areaComponent
        Rectangle {
            property alias input: area
            implicitHeight: Math.min(Math.max(area.implicitHeight, 72), 220)
            radius: LingmoUI.Theme.smallRadius
            color: LingmoUI.Theme.alternateBackgroundColor
            border.width: area.activeFocus ? 1.5 : 0
            border.color: LingmoUI.Theme.highlightColor
            ScrollView {
                anchors.fill: parent
                TextArea {
                    id: area
                    text: field.value === undefined || field.value === null ? "" : String(field.value)
                    wrapMode: TextArea.Wrap
                    placeholderText: field.param.placeholder || ""
                    font.pointSize: LingmoUI.Units.fontBody
                    background: Item {}
                    onTextChanged: if (activeFocus) {
                        field.edited(text)
                        if (text.slice(Math.max(0, cursorPosition - 2), cursorPosition) === "{{")
                            variableMenu.openAt(area)
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------ other kinds
    Switch {
        visible: field.param.kind === "bool"
        checked: field.value === true
        onToggled: field.edited(checked)
    }

    ComboBox {
        visible: field.param.kind === "select"
        Layout.fillWidth: true
        model: field.param.options || []
        textRole: "label"
        valueRole: "value"
        currentIndex: { const o = field.param.options || []; for (let i = 0; i < o.length; ++i) if (o[i].value === field.value) return i; return 0 }
        onActivated: field.edited(currentValue)
    }

    // mail account: first account, a specific one, or the trigger's
    ComboBox {
        id: accountBox
        visible: field.param.kind === "account"
        Layout.fillWidth: true
        readonly property var choices: {
            let out = [{ value: "", label: qsTr("First account") }]
            for (const a of assistant.accounts)
                out.push({ value: a.id, label: a.email })
            out.push({ value: "{{trigger.account}}", label: qsTr("The trigger's account") })
            if (field.value && !out.some(c => c.value === field.value))
                out.push({ value: field.value, label: field.value })
            return out
        }
        model: choices
        textRole: "label"
        valueRole: "value"
        currentIndex: Math.max(0, choices.findIndex(c => c.value === (field.value || "")))
        onActivated: field.edited(currentValue)
    }

    ComboBox {
        id: agentBox
        visible: field.param.kind === "agent"
        Layout.fillWidth: true
        readonly property var choices: {
            let out = [{ value: "", label: qsTr("Assistant (default)") }]
            for (const a of assistant.agentChoices)
                out.push({ value: a.id, label: a.emoji + "  " + a.name })
            return out
        }
        model: choices
        textRole: "label"
        valueRole: "value"
        currentIndex: Math.max(0, choices.findIndex(c => c.value === (field.value || "")))
        onActivated: field.edited(currentValue)
    }

    ComboBox {
        id: folderBox
        visible: field.param.kind === "folder"
        Layout.fillWidth: true
        editable: true
        model: assistant.allowedFolders
        editText: typeof field.value === "string" ? field.value : ""
        onAccepted: field.edited(editText)
        onActivated: field.edited(currentText)
        onEditTextChanged: if (activeFocus) field.edited(editText)
    }

    // one item per line
    Rectangle {
        visible: field.param.kind === "list"
        Layout.fillWidth: true
        implicitHeight: Math.min(Math.max(listArea.implicitHeight, 64), 180)
        radius: LingmoUI.Theme.smallRadius
        color: LingmoUI.Theme.alternateBackgroundColor
        border.width: listArea.activeFocus ? 1.5 : 0
        border.color: LingmoUI.Theme.highlightColor
        TextArea {
            id: listArea
            anchors.fill: parent
            text: Array.isArray(field.value) ? field.value.join("\n") : (typeof field.value === "string" ? field.value : "")
            wrapMode: TextArea.Wrap
            font.pointSize: LingmoUI.Units.fontBody
            background: Item {}
            onTextChanged: if (activeFocus) field.edited(text.split("\n").map(s => s.trim()).filter(s => s !== ""))
        }
    }
    Label {
        visible: field.param.kind === "list"
        text: qsTr("One per line")
        font.pointSize: LingmoUI.Units.fontCaption
        color: LingmoUI.Theme.secondaryTextColor
    }

    ScheduleEditor {
        visible: field.param.kind === "schedule"
        Layout.fillWidth: true
        value: field.param.kind === "schedule" ? (field.value || ({})) : ({})
        onEdited: (v) => field.edited(v)
    }

    Label {
        visible: (field.param.help || "") !== ""
        Layout.fillWidth: true
        text: field.param.help || ""
        wrapMode: Text.Wrap
        font.pointSize: LingmoUI.Units.fontCaption
        color: LingmoUI.Theme.secondaryTextColor
    }

    // ------------------------------------------------------------ variable autocomplete
    Popup {
        id: variableMenu
        width: 300
        height: Math.min(list.contentHeight + 16, 260)
        padding: 8
        property var items: []
        function openAt(item) {
            items = field.doc.variablesFor(field.nodeId)
            const p = item.mapToItem(field, 0, item.height)
            x = Math.min(p.x, field.width - width)
            y = p.y + 4
            open()
        }
        background: Rectangle {
            radius: LingmoUI.Theme.mediumRadius
            color: LingmoUI.Theme.secondBackgroundColor
            border.color: LingmoUI.Theme.borderColor
        }
        contentItem: ListView {
            id: list
            clip: true
            model: variableMenu.items
            delegate: ItemDelegate {
                required property var modelData
                width: ListView.view.width
                contentItem: ColumnLayout {
                    spacing: 0
                    Label { text: modelData.label; color: LingmoUI.Theme.textColor; elide: Text.ElideRight; Layout.fillWidth: true }
                    Label { text: modelData.text; color: LingmoUI.Theme.secondaryTextColor; font.family: "monospace"; font.pointSize: LingmoUI.Units.fontCaption }
                }
                onClicked: {
                    variableMenu.close()
                    field.insertVariable(modelData.text)
                }
            }
            Label {
                visible: variableMenu.items.length === 0
                text: qsTr("Connect this block after others to use their results.")
                wrapMode: Text.Wrap
                width: parent.width
                color: LingmoUI.Theme.secondaryTextColor
            }
        }
    }
}
