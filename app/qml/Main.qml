import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI

LingmoUI.Window {
    id: rootWindow
    width: 980
    height: 680
    minimumWidth: 760
    minimumHeight: 560
    title: qsTr("Assistant")
    visible: true

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

    function focusComposer() { input.forceActiveFocus() }

    function submit() {
        if (assistant.busy || input.text.trim() === "")
            return
        assistant.send(input.text)
        input.text = ""
        focusComposer()
    }

    // Seconds since the question was sent, so a slow model visibly isn't stuck
    property int waited: 0
    Timer {
        interval: 1000
        repeat: true
        running: assistant.busy
        onRunningChanged: if (running) rootWindow.waited = 0
        onTriggered: rootWindow.waited++
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // Conversations on the left, in the style of Lingmo Settings' sidebar
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

                LingmoUI.SideBarItem {
                    Layout.fillWidth: true
                    Layout.leftMargin: LingmoUI.Units.largeSpacing
                    Layout.rightMargin: LingmoUI.Units.largeSpacing
                    title: qsTr("New conversation")
                    iconName: "document-new"
                    isCurrent: assistant.messages.count === 0
                    onClicked: {
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
                            isCurrent: conversationId === assistant.conversationId && assistant.messages.count > 0
                            onClicked: assistant.openConversation(conversationId)

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
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // Page title, in the window's header strip
            LingmoUI.PageHeader {
                Layout.fillWidth: true
                Layout.preferredHeight: rootWindow.header.height
                leftPadding: LingmoUI.Units.largeSpacing * 3
                rightPadding: LingmoUI.Units.largeSpacing * 3
                large: false
                title: assistant.title !== "" ? assistant.title : qsTr("New conversation")
            }

            // ------------------------------------------------ empty state
            ColumnLayout {
                visible: assistant.messages.count === 0
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.leftMargin: LingmoUI.Units.largeSpacing * 3
                Layout.rightMargin: LingmoUI.Units.largeSpacing * 3
                spacing: LingmoUI.Units.largeSpacing

                Item { Layout.fillHeight: true }

                LingmoUI.EmptyState {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.fillWidth: true
                    Layout.maximumWidth: 640
                    iconName: "internet-chat"
                    iconSize: LingmoUI.Units.iconSizes.large * 1.5
                    title: qsTr("How can I help?")
                    text: assistant.engineInstalled
                          ? qsTr("I run on this computer. I can read your documents, notes and calendar, look at the system and, with your permission, write notes, events and files.")
                          : qsTr("The assistant engine isn't installed.")
                }

                GridLayout {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.topMargin: LingmoUI.Units.largeSpacing
                    Layout.maximumWidth: 640
                    columns: 2
                    columnSpacing: LingmoUI.Units.smallSpacing
                    rowSpacing: LingmoUI.Units.smallSpacing
                    visible: assistant.engineInstalled

                    Repeater {
                        model: [
                            { text: qsTr("Summarize the PDF "), send: false, icon: "application-pdf" },
                            { text: qsTr("What's my hardware configuration?"), send: true, icon: "computer" },
                            { text: qsTr("Create a note with "), send: false, icon: "document-edit" },
                            { text: qsTr("Remind me tomorrow at 9 to "), send: false, icon: "appointment-new" },
                        ]
                        delegate: LingmoUI.Card {
                            id: exampleCard
                            required property var modelData
                            clickable: true
                            Layout.fillWidth: true
                            Layout.preferredWidth: 300
                            implicitHeight: exampleRow.implicitHeight + LingmoUI.Units.largeSpacing * 2

                            RowLayout {
                                id: exampleRow
                                anchors.fill: parent
                                anchors.leftMargin: exampleCard.padding
                                anchors.rightMargin: exampleCard.padding
                                spacing: LingmoUI.Units.largeSpacing

                                LingmoUI.IconItem {
                                    Layout.preferredWidth: LingmoUI.Units.iconSizes.smallMedium
                                    Layout.preferredHeight: LingmoUI.Units.iconSizes.smallMedium
                                    source: modelData.icon
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: modelData.text.trim() + (modelData.send ? "" : "…")
                                    wrapMode: Text.Wrap
                                    font.pointSize: LingmoUI.Units.fontBody
                                    color: LingmoUI.Theme.textColor
                                }
                            }

                            onClicked: {
                                if (modelData.send) {
                                    assistant.send(modelData.text)
                                    rootWindow.focusComposer()
                                } else {
                                    input.text = modelData.text
                                    input.cursorPosition = input.text.length
                                    rootWindow.focusComposer()
                                }
                            }
                        }
                    }
                }

                Item { Layout.fillHeight: true }
            }

            // ------------------------------------------------ conversation
            ListView {
                id: chatView
                visible: assistant.messages.count > 0
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: assistant.messages
                spacing: LingmoUI.Units.largeSpacing
                leftMargin: LingmoUI.Units.largeSpacing * 3
                rightMargin: LingmoUI.Units.largeSpacing * 3
                topMargin: LingmoUI.Units.largeSpacing
                bottomMargin: LingmoUI.Units.largeSpacing
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}

                LingmoUI.WheelHandler { target: chatView }

                // Follow the answer as it streams in
                onCountChanged: Qt.callLater(positionViewAtEnd)
                Connections {
                    target: assistant.messages
                    function onDataChanged() { if (chatView.atYEnd || assistant.busy) Qt.callLater(chatView.positionViewAtEnd) }
                }

                delegate: Item {
                    id: row

                    required property int index
                    required property string kind
                    required property string text
                    required property bool thinking
                    required property string stats
                    required property string functionName
                    required property string args
                    required property bool ok
                    required property bool running
                    required property string output
                    required property string requestId
                    required property string title
                    required property string details
                    required property string confirmState

                    readonly property real contentWidth: ListView.view.width - ListView.view.leftMargin - ListView.view.rightMargin

                    width: contentWidth
                    height: loader.item ? loader.item.implicitHeight : 0

                    Loader {
                        id: loader
                        width: row.contentWidth
                        sourceComponent: row.kind === "user" ? userBubble
                                       : row.kind === "assistant" ? answerBubble
                                       : row.kind === "tool" ? toolCard
                                       : row.kind === "confirm" ? confirmCard
                                       : noticeRow
                    }

                    Component {
                        id: userBubble
                        Item {
                            implicitHeight: bubble.height
                            Rectangle {
                                id: bubble
                                anchors.right: parent.right
                                width: Math.min(userText.implicitWidth + LingmoUI.Units.largeSpacing * 2, parent.width * 0.8)
                                height: userText.implicitHeight + LingmoUI.Units.largeSpacing * 1.4
                                radius: LingmoUI.Theme.bigRadius
                                color: LingmoUI.Theme.highlightColor

                                TextEdit {
                                    id: userText
                                    x: LingmoUI.Units.largeSpacing
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: Math.min(implicitWidth, row.contentWidth * 0.8 - LingmoUI.Units.largeSpacing * 2)
                                    readOnly: true
                                    selectByMouse: true
                                    wrapMode: TextEdit.Wrap
                                    textFormat: TextEdit.PlainText
                                    text: row.text
                                    color: LingmoUI.Theme.highlightedTextColor
                                    font.pointSize: LingmoUI.Units.fontBody
                                }
                            }
                        }
                    }

                    Component {
                        id: answerBubble
                        ColumnLayout {
                            spacing: 2
                            HoverHandler { id: answerHover }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: LingmoUI.Units.smallSpacing

                                // Waiting for the first words of the answer
                                LingmoUI.Spinner {
                                    visible: row.text === ""
                                    running: visible
                                    size: LingmoUI.Units.iconSizes.small
                                    Layout.alignment: Qt.AlignVCenter
                                }

                                TextEdit {
                                    Layout.fillWidth: true
                                    readOnly: true
                                    selectByMouse: true
                                    wrapMode: TextEdit.Wrap
                                    textFormat: row.text !== "" ? TextEdit.MarkdownText : TextEdit.PlainText
                                    text: row.text !== "" ? row.text
                                          : (row.thinking ? qsTr("Reasoning… %1 s") : qsTr("Thinking… %1 s")).arg(rootWindow.waited)
                                    color: row.text !== "" ? LingmoUI.Theme.textColor : LingmoUI.Theme.secondaryTextColor
                                    font.pointSize: LingmoUI.Units.fontBody
                                    selectionColor: LingmoUI.Theme.highlightColor
                                    selectedTextColor: LingmoUI.Theme.highlightedTextColor
                                    onLinkActivated: (link) => {
                                        if (/^https?:\/\//.test(link))
                                            Qt.openUrlExternally(link)
                                    }
                                }
                            }

                            RowLayout {
                                spacing: LingmoUI.Units.largeSpacing
                                Layout.preferredHeight: copyLabel.implicitHeight

                                Label {
                                    visible: row.stats.trim() !== ""
                                    text: row.stats
                                    color: LingmoUI.Theme.secondaryTextColor
                                    font.pointSize: LingmoUI.Units.fontCaption
                                }
                                Label {
                                    id: copyLabel
                                    opacity: answerHover.hovered && row.stats !== "" ? 1 : 0
                                    text: copied.running ? qsTr("Copied") : qsTr("Copy")
                                    color: LingmoUI.Theme.linkColor
                                    font.pointSize: LingmoUI.Units.fontCaption
                                    Behavior on opacity { NumberAnimation { duration: LingmoUI.Units.shortDuration } }
                                    Timer { id: copied; interval: 1500 }
                                    TapHandler {
                                        onTapped: {
                                            assistant.copy(row.text)
                                            copied.restart()
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Component {
                        id: toolCard
                        ToolCard {
                            functionName: row.functionName
                            args: row.args
                            ok: row.ok
                            running: row.running
                            output: row.output
                        }
                    }

                    Component {
                        id: confirmCard
                        ConfirmCard {
                            requestId: row.requestId
                            title: row.title
                            details: row.details
                            confirmState: row.confirmState
                        }
                    }

                    Component {
                        id: noticeRow
                        Label {
                            wrapMode: Text.Wrap
                            text: row.text
                            color: LingmoUI.Theme.secondaryTextColor
                            font.pointSize: LingmoUI.Units.fontCaption
                        }
                    }
                }
            }

            // Errors from the engine or the model server
            LingmoUI.Banner {
                Layout.fillWidth: true
                Layout.leftMargin: LingmoUI.Units.largeSpacing * 2
                Layout.rightMargin: LingmoUI.Units.largeSpacing * 2
                Layout.topMargin: LingmoUI.Units.smallSpacing
                type: LingmoUI.Banner.Error
                // Cleared by the next question or conversation
                closable: false
                text: assistant.error
            }

            // ------------------------------------------------ composer
            LingmoUI.Card {
                Layout.fillWidth: true
                Layout.leftMargin: LingmoUI.Units.largeSpacing * 2
                Layout.rightMargin: LingmoUI.Units.largeSpacing * 2
                Layout.topMargin: LingmoUI.Units.smallSpacing
                implicitHeight: Math.min(Math.max(input.implicitHeight, sendButton.implicitHeight), 160)
                                + LingmoUI.Units.largeSpacing * 1.4

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: LingmoUI.Units.largeSpacing
                    anchors.rightMargin: LingmoUI.Units.smallSpacing * 1.5
                    spacing: LingmoUI.Units.smallSpacing

                    ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        TextArea {
                            id: input
                            placeholderText: assistant.busy ? qsTr("Answering… Esc stops") : qsTr("Ask the assistant…")
                            wrapMode: TextArea.Wrap
                            font.pointSize: LingmoUI.Units.fontBody
                            background: Item {}
                            enabled: assistant.engineInstalled
                            focus: true
                            Keys.onReturnPressed: (event) => {
                                if (event.modifiers & Qt.ShiftModifier)
                                    event.accepted = false
                                else
                                    rootWindow.submit()
                            }
                            Keys.onEnterPressed: rootWindow.submit()
                            Keys.onEscapePressed: if (assistant.busy) assistant.stop()
                        }
                    }

                    LingmoUI.IconButton {
                        visible: assistant.busy
                        iconName: "media-playback-stop"
                        tipText: qsTr("Stop")
                        Layout.alignment: Qt.AlignBottom
                        Layout.bottomMargin: LingmoUI.Units.smallSpacing
                        onClicked: assistant.stop()
                    }

                    LingmoUI.ActionButton {
                        id: sendButton
                        visible: !assistant.busy
                        primary: true
                        text: qsTr("Send")
                        enabled: input.text.trim() !== "" && assistant.engineInstalled
                        Layout.alignment: Qt.AlignBottom
                        Layout.bottomMargin: LingmoUI.Units.smallSpacing
                        onClicked: rootWindow.submit()
                    }
                }
            }

            // ------------------------------------------------ footer
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: LingmoUI.Units.largeSpacing * 2.5
                Layout.rightMargin: LingmoUI.Units.largeSpacing * 2.5
                Layout.topMargin: LingmoUI.Units.smallSpacing
                Layout.bottomMargin: LingmoUI.Units.largeSpacing
                spacing: LingmoUI.Units.largeSpacing

                Label {
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    color: LingmoUI.Theme.secondaryTextColor
                    font.pointSize: LingmoUI.Units.fontCaption
                    text: assistant.model === "" ? qsTr("No AI model chosen")
                          : !assistant.toolsSupported ? qsTr("%1 · this model can't use tools: chat only").arg(assistant.model)
                          : assistant.writeAllowed ? qsTr("%1 · every change asks for your permission").arg(assistant.model)
                          : qsTr("%1 · read only").arg(assistant.model)
                }

                Label {
                    text: qsTr("AI settings")
                    color: LingmoUI.Theme.linkColor
                    font.pointSize: LingmoUI.Units.fontCaption
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: assistant.openSettings() }
                }
            }
        }
    }
}
