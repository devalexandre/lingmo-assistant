import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import LingmoUI.CompatibleModule 3.0 as LingmoUI

// The floating voice pill: listening (with the microphone level and a red
// "mic on" dot), transcribing, thinking, then the answer.
Window {
    id: pill
    transientParent: null
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
    color: "transparent"
    visible: assistant.voiceVisible
    width: 560
    height: body.implicitHeight + 44
    x: Screen.virtualX + (Screen.width - width) / 2
    y: Screen.virtualY + Math.round(Screen.height * 0.12)
    title: qsTr("Assistant voice")

    readonly property string state_: assistant.voiceState
    readonly property bool listening: state_ === "listening"

    onVisibleChanged: if (visible) { requestActivate(); closeTimer.stop() }

    // Close a while after the answer, unless the pointer is on it
    Timer {
        id: closeTimer
        interval: 9000
        running: pill.visible && (pill.state_ === "idle" || pill.state_ === "error") && !assistant.speaking && !hover.hovered
        onTriggered: assistant.voiceVisible = false
    }

    Rectangle {
        id: frame
        anchors.fill: parent
        anchors.margins: 12
        radius: Math.min(height / 2, 30)
        color: LingmoUI.Theme.darkMode ? Qt.rgba(0.13, 0.13, 0.15, 0.96) : Qt.rgba(1, 1, 1, 0.97)
        border.color: LingmoUI.Theme.darkMode ? Qt.rgba(1, 1, 1, 0.15) : Qt.rgba(0, 0, 0, 0.12)
        Behavior on radius { NumberAnimation { duration: LingmoUI.Units.shortDuration } }

        HoverHandler { id: hover }
        Keys.onEscapePressed: assistant.voiceVisible = false
        focus: true

        ColumnLayout {
            id: body
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 18
            anchors.rightMargin: 12
            anchors.topMargin: 10
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 40
                spacing: 12

                // mic tile; red while the microphone is recording
                Rectangle {
                    Layout.preferredWidth: 36
                    Layout.preferredHeight: 36
                    radius: 18
                    color: pill.listening ? LingmoUI.Theme.redColor : LingmoUI.Theme.highlightColor
                    Behavior on color { ColorAnimation { duration: LingmoUI.Units.shortDuration } }
                    Rectangle {
                        anchors.centerIn: parent
                        width: 36 + assistant.voiceLevel * 22
                        height: width
                        radius: width / 2
                        color: "transparent"
                        border.width: 2
                        border.color: LingmoUI.Theme.redColor
                        opacity: pill.listening ? 0.5 : 0
                        Behavior on width { NumberAnimation { duration: 90 } }
                    }
                    LingmoUI.IconItem {
                        anchors.centerIn: parent
                        width: 20; height: 20
                        source: pill.state_ === "error" ? "dialog-warning" : "audio-input-microphone"
                        color: "white"
                    }
                }

                // level bars while listening, a status line otherwise
                Row {
                    visible: pill.listening
                    Layout.preferredHeight: 32
                    spacing: 4
                    Repeater {
                        model: 12
                        delegate: Rectangle {
                            required property int index
                            readonly property real wave: 0.35 + 0.65 * Math.abs(Math.sin(index * 0.9 + assistant.voiceSeconds * 7))
                            anchors.verticalCenter: parent.verticalCenter
                            width: 4
                            height: Math.max(4, 30 * Math.min(1, assistant.voiceLevel * 1.3) * wave)
                            radius: 2
                            color: LingmoUI.Theme.highlightColor
                            Behavior on height { NumberAnimation { duration: 80 } }
                        }
                    }
                }

                LingmoUI.Spinner {
                    visible: pill.state_ === "transcribing" || pill.state_ === "thinking"
                    running: visible
                    size: LingmoUI.Units.iconSizes.small
                }

                Label {
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    color: LingmoUI.Theme.textColor
                    font.pointSize: LingmoUI.Units.fontBody
                    text: pill.listening ? qsTr("Listening… pause or press again to send")
                        : pill.state_ === "transcribing" ? qsTr("Understanding…")
                        : pill.state_ === "thinking" ? (assistant.voiceMessage !== "" ? assistant.voiceMessage : qsTr("Thinking…"))
                        : pill.state_ === "answering" ? (assistant.speaking ? qsTr("Speaking…") : qsTr("Answer"))
                        : pill.state_ === "error" ? assistant.voiceMessage
                        : assistant.voiceMessage !== "" ? assistant.voiceMessage
                        : assistant.speaking ? qsTr("Speaking…") : qsTr("Done")
                }

                Rectangle {
                    visible: pill.listening
                    width: 8; height: 8; radius: 4
                    color: LingmoUI.Theme.redColor
                    SequentialAnimation on opacity {
                        running: pill.listening
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.2; duration: 600 }
                        NumberAnimation { to: 1; duration: 600 }
                    }
                }
                Label {
                    visible: pill.listening
                    text: qsTr("mic on")
                    font.pointSize: LingmoUI.Units.fontCaption
                    color: LingmoUI.Theme.redColor
                }

                LingmoUI.IconButton {
                    visible: pill.listening
                    iconName: "media-playback-stop"
                    tipText: qsTr("Send now")
                    onClicked: assistant.stopVoice()
                }
                LingmoUI.IconButton {
                    visible: assistant.speaking
                    iconName: "audio-volume-muted"
                    tipText: qsTr("Stop speaking")
                    onClicked: assistant.stopSpeaking()
                }
                LingmoUI.IconButton {
                    iconName: "window-close"
                    tipText: qsTr("Close (Esc)")
                    onClicked: assistant.voiceVisible = false
                }
            }

            Label {
                Layout.fillWidth: true
                visible: assistant.voiceText !== ""
                text: "“" + assistant.voiceText + "”"
                wrapMode: Text.Wrap
                color: LingmoUI.Theme.secondaryTextColor
                font.italic: true
                font.pointSize: LingmoUI.Units.fontCaption
            }

            Flickable {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(answer.implicitHeight, 180)
                Layout.bottomMargin: assistant.voiceAnswer !== "" ? 8 : 0
                visible: assistant.voiceAnswer !== ""
                contentHeight: answer.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                TextEdit {
                    id: answer
                    width: parent.width
                    readOnly: true
                    wrapMode: TextEdit.Wrap
                    textFormat: TextEdit.MarkdownText
                    text: assistant.voiceAnswer
                    color: LingmoUI.Theme.textColor
                    font.pointSize: LingmoUI.Units.fontBody
                }
            }

            LingmoUI.ActionButton {
                Layout.alignment: Qt.AlignRight
                Layout.bottomMargin: 4
                visible: assistant.voiceAnswer !== "" && !pill.listening
                subtle: true
                text: qsTr("Open in the Assistant")
                onClicked: {
                    assistant.section = "chat"
                    assistant.open("")
                    assistant.voiceVisible = false
                }
            }
        }
    }
}
