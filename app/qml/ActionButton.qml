import QtQuick
import QtQuick.Controls
import LingmoUI.CompatibleModule 3.0 as LingmoUI

// Rounded push button, same as lingmo-winrun's: `primary` uses the accent
// colour, `destructive` the red one. Everything else comes from the theme.
Button {
    id: control

    property bool primary: false
    property bool destructive: false

    implicitHeight: 34
    leftPadding: LingmoUI.Units.largeSpacing * 1.5
    rightPadding: LingmoUI.Units.largeSpacing * 1.5
    opacity: enabled ? 1.0 : 0.5

    contentItem: Label {
        text: control.text
        font.pointSize: LingmoUI.Theme.fontSize
        font.bold: control.font.bold
        color: control.primary ? LingmoUI.Theme.highlightedTextColor
                               : control.destructive ? LingmoUI.Theme.redColor : LingmoUI.Theme.textColor
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: Rectangle {
        radius: LingmoUI.Theme.smallRadius
        color: {
            const base = control.primary ? LingmoUI.Theme.highlightColor
                       : control.destructive ? Qt.rgba(LingmoUI.Theme.redColor.r, LingmoUI.Theme.redColor.g,
                                                       LingmoUI.Theme.redColor.b, LingmoUI.Theme.darkMode ? 0.22 : 0.12)
                       : LingmoUI.Theme.alternateBackgroundColor
            if (control.pressed)
                return Qt.darker(base, 1.15)
            if (control.hovered)
                return control.primary ? Qt.lighter(base, 1.1) : Qt.darker(base, LingmoUI.Theme.darkMode ? 0.85 : 1.05)
            return base
        }
        border.width: control.primary ? 0 : 1
        border.color: LingmoUI.Theme.darkMode ? Qt.rgba(1, 1, 1, 0.08) : Qt.rgba(0, 0, 0, 0.08)

        Behavior on color { ColorAnimation { duration: 120 } }
    }
}
