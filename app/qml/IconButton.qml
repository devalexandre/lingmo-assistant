import QtQuick
import QtQuick.Controls
import LingmoUI.CompatibleModule 3.0 as LingmoUI

// Small icon-only button (theme icon) with an animated hover background
AbstractButton {
    id: control

    property string iconName
    property string tipText

    implicitWidth: LingmoUI.Units.iconSizes.medium
    implicitHeight: LingmoUI.Units.iconSizes.medium
    hoverEnabled: true
    opacity: enabled ? 1.0 : 0.5

    background: Rectangle {
        radius: LingmoUI.Theme.smallRadius
        color: control.pressed ? Qt.rgba(LingmoUI.Theme.textColor.r, LingmoUI.Theme.textColor.g,
                                         LingmoUI.Theme.textColor.b, 0.15)
             : control.hovered ? Qt.rgba(LingmoUI.Theme.textColor.r, LingmoUI.Theme.textColor.g,
                                         LingmoUI.Theme.textColor.b, 0.08)
             : "transparent"

        Behavior on color { ColorAnimation { duration: 120 } }
    }

    contentItem: Item {
        LingmoUI.IconItem {
            anchors.centerIn: parent
            width: LingmoUI.Units.iconSizes.small
            height: width
            source: control.iconName
            smooth: true
        }
    }

    ToolTip.visible: hovered && tipText.length > 0
    ToolTip.text: tipText
    ToolTip.delay: 500
}
