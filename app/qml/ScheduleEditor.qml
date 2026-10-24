import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import LingmoUI.CompatibleModule 3.0 as LingmoUI

// Friendly schedule picker: every day, chosen weekdays, every N minutes,
// a day of the month, or cron for advanced users.
ColumnLayout {
    id: sched
    property var value: ({})
    signal edited(var value)
    spacing: LingmoUI.Units.smallSpacing

    readonly property var kinds: ["daily", "weekdays", "interval", "monthly", "cron"]
    readonly property string kind: value.kind || "daily"

    function emit(changes) {
        let v = Object.assign({}, value, changes)
        if (v.kind === "weekdays" && !Array.isArray(v.days))
            v.days = [0, 1, 2, 3, 4]
        if ((v.kind === "daily" || v.kind === "weekdays" || v.kind === "monthly") && !v.time)
            v.time = "09:00"
        if (v.kind === "interval" && !v.minutes)
            v.minutes = 60
        if (v.kind === "monthly" && !v.day)
            v.day = 1
        if (v.kind === "cron" && !v.cron)
            v.cron = "0 9 * * 1-5"
        edited(v)
    }

    ComboBox {
        Layout.fillWidth: true
        model: [qsTr("Every day"), qsTr("On some weekdays"), qsTr("Every few minutes"), qsTr("Once a month"),
                qsTr("Advanced (cron)")]
        currentIndex: Math.max(0, sched.kinds.indexOf(sched.kind))
        onActivated: (i) => sched.emit({ kind: sched.kinds[i] })
    }

    // weekday chips
    Flow {
        Layout.fillWidth: true
        visible: sched.kind === "weekdays"
        spacing: 4
        Repeater {
            model: [qsTr("Mon"), qsTr("Tue"), qsTr("Wed"), qsTr("Thu"), qsTr("Fri"), qsTr("Sat"), qsTr("Sun")]
            delegate: Rectangle {
                required property string modelData
                required property int index
                readonly property bool on: (sched.value.days || []).indexOf(index) >= 0
                width: 38; height: 30
                radius: 15
                color: on ? LingmoUI.Theme.highlightColor : LingmoUI.Theme.alternateBackgroundColor
                Behavior on color { ColorAnimation { duration: LingmoUI.Units.shortDuration } }
                Label {
                    anchors.centerIn: parent
                    text: modelData
                    font.pointSize: LingmoUI.Units.fontCaption
                    color: parent.on ? LingmoUI.Theme.highlightedTextColor : LingmoUI.Theme.textColor
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        let days = (sched.value.days || []).slice()
                        const i = days.indexOf(index)
                        if (i >= 0) days.splice(i, 1); else days.push(index)
                        days.sort()
                        if (days.length > 0)
                            sched.emit({ days: days })
                    }
                }
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        visible: sched.kind === "monthly"
        Label { text: qsTr("Day"); color: LingmoUI.Theme.textColor }
        SpinBox {
            from: 1; to: 31
            value: sched.value.day || 1
            onValueModified: sched.emit({ day: value })
        }
    }

    RowLayout {
        Layout.fillWidth: true
        visible: sched.kind === "daily" || sched.kind === "weekdays" || sched.kind === "monthly"
        Label { text: qsTr("At"); color: LingmoUI.Theme.textColor }
        TextField {
            Layout.preferredWidth: 90
            inputMask: "99:99"
            text: sched.value.time || "09:00"
            onEditingFinished: if (/^\d\d:\d\d$/.test(text)) sched.emit({ time: text })
        }
    }

    RowLayout {
        Layout.fillWidth: true
        visible: sched.kind === "interval"
        Label { text: qsTr("Every"); color: LingmoUI.Theme.textColor }
        SpinBox {
            from: 1; to: 1440
            value: sched.value.minutes || 60
            editable: true
            onValueModified: sched.emit({ minutes: value })
        }
        Label { text: qsTr("minutes"); color: LingmoUI.Theme.textColor }
    }

    ColumnLayout {
        Layout.fillWidth: true
        visible: sched.kind === "cron"
        spacing: 2
        TextField {
            Layout.fillWidth: true
            font.family: "monospace"
            text: sched.value.cron || ""
            placeholderText: "0 9 * * 1-5"
            onEditingFinished: sched.emit({ cron: text })
        }
        Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: qsTr("minute hour day month weekday — e.g. “*/30 8-18 * * 1-5” is every 30 minutes, 8h to 18h, Monday to Friday.")
            font.pointSize: LingmoUI.Units.fontCaption
            color: LingmoUI.Theme.secondaryTextColor
        }
    }
}
