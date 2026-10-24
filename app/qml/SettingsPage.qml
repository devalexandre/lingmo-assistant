import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI

// The Assistant's own settings: voice replies, the voice, its speed, and what
// the speech recognition uses. Permissions live in Settings › AI.
Flickable {
    id: page
    contentHeight: column.implicitHeight + LingmoUI.Units.largeSpacing * 4
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar {}

    readonly property var info: assistant.voiceInfo
    readonly property var voices: info.voices || []

    ColumnLayout {
        id: column
        width: Math.min(page.width - LingmoUI.Units.largeSpacing * 6, 720)
        x: (page.width - width) / 2
        spacing: LingmoUI.Units.largeSpacing

        LingmoUI.PageHeader {
            Layout.fillWidth: true
            Layout.preferredHeight: LingmoUI.Units.windowHeaderHeight
            large: false
            title: qsTr("Voice and settings")
        }

        LingmoUI.Card {
            Layout.fillWidth: true
            implicitHeight: speech.implicitHeight + LingmoUI.Units.largeSpacing * 3
            ColumnLayout {
                id: speech
                anchors.fill: parent
                anchors.margins: LingmoUI.Units.largeSpacing * 1.5
                spacing: LingmoUI.Units.largeSpacing

                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Label { text: qsTr("Answer out loud"); font.bold: true; color: LingmoUI.Theme.textColor }
                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            text: qsTr("When you ask by voice, the answer is also spoken.")
                            font.pointSize: LingmoUI.Units.fontCaption
                            color: LingmoUI.Theme.secondaryTextColor
                        }
                    }
                    Switch {
                        checked: assistant.voiceReplies
                        onToggled: assistant.voiceReplies = checked
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Label { text: qsTr("Voice"); color: LingmoUI.Theme.textColor; Layout.preferredWidth: 120 }
                    ComboBox {
                        id: voiceBox
                        Layout.fillWidth: true
                        readonly property var choices: [{ id: "", name: qsTr("Automatic (best for your language)") }].concat(page.voices)
                        model: choices
                        textRole: "name"
                        valueRole: "id"
                        currentIndex: Math.max(0, choices.findIndex(v => v.id === assistant.ttsVoice))
                        onActivated: assistant.ttsVoice = currentValue
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Label { text: qsTr("Speed"); color: LingmoUI.Theme.textColor; Layout.preferredWidth: 120 }
                    Slider {
                        id: rateSlider
                        Layout.fillWidth: true
                        from: 0.5; to: 2.0; stepSize: 0.05
                        value: assistant.ttsRate
                        onPressedChanged: if (!pressed) assistant.ttsRate = value
                    }
                    Label { text: Math.round(rateSlider.value * 100) + "%"; color: LingmoUI.Theme.secondaryTextColor; Layout.preferredWidth: 48 }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    LingmoUI.ActionButton {
                        text: assistant.speaking ? qsTr("Stop") : qsTr("Test the voice")
                        iconName: assistant.speaking ? "media-playback-stop" : "audio-speakers"
                        enabled: page.voices.length > 0
                        onClicked: assistant.speaking ? assistant.stopSpeaking() : assistant.testVoice()
                    }
                }

                LingmoUI.Banner {
                    Layout.fillWidth: true
                    visible: page.info.piper === false && page.info.espeak === false
                    type: LingmoUI.Banner.Warning
                    closable: false
                    text: qsTr("No voice is installed. Install “piper-tts” with a voice for your language (natural) or “espeak-ng” (robotic).")
                }
            }
        }

        LingmoUI.Card {
            Layout.fillWidth: true
            implicitHeight: listen.implicitHeight + LingmoUI.Units.largeSpacing * 3
            ColumnLayout {
                id: listen
                anchors.fill: parent
                anchors.margins: LingmoUI.Units.largeSpacing * 1.5
                spacing: LingmoUI.Units.smallSpacing
                Label { text: qsTr("Asking by voice"); font.bold: true; color: LingmoUI.Theme.textColor }
                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: qsTr("Press Meta+Shift+I anywhere (or the microphone in the chat), speak, and pause: the assistant stops listening by itself. Press again to stop sooner. Everything is processed on this computer.")
                    color: LingmoUI.Theme.textColor
                }
                GridLayout {
                    columns: 2
                    columnSpacing: LingmoUI.Units.largeSpacing
                    rowSpacing: 4
                    Layout.topMargin: LingmoUI.Units.smallSpacing
                    Label { text: qsTr("Speech recognition"); color: LingmoUI.Theme.secondaryTextColor }
                    Label {
                        text: page.info.whisper ? qsTr("whisper.cpp, on this computer") : qsTr("whisper.cpp isn't installed")
                        color: page.info.whisper ? LingmoUI.Theme.textColor : LingmoUI.Theme.orangeColor
                    }
                    Label { text: qsTr("Downloaded models"); color: LingmoUI.Theme.secondaryTextColor }
                    Label {
                        text: (page.info.whisper_models || []).length > 0 ? page.info.whisper_models.join(", ") : qsTr("none — download one in Settings › AI")
                        color: LingmoUI.Theme.textColor
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Label { text: qsTr("Language"); color: LingmoUI.Theme.secondaryTextColor }
                    Label { text: page.info.language === "auto" || !page.info.language ? qsTr("Detected automatically") : page.info.language; color: LingmoUI.Theme.textColor }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: LingmoUI.Units.smallSpacing
                    Item { Layout.fillWidth: true }
                    LingmoUI.ActionButton {
                        text: qsTr("Try it")
                        iconName: "audio-input-microphone"
                        onClicked: assistant.voice()
                    }
                    LingmoUI.ActionButton {
                        text: qsTr("Settings › AI")
                        onClicked: assistant.openSettings()
                    }
                }
            }
        }
    }
}
