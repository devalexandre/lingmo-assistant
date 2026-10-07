import QtQuick
import LingmoUI.CompatibleModule 3.0 as LingmoUI

// Card in the style of Lingmo Settings' RoundedItem: second background colour,
// medium radius, a hairline border and an animated hover tint
LingmoUI.RoundedRect {
    id: card

    property bool hoverEnabled: false
    readonly property bool hovered: hoverHandler.hovered

    radius: LingmoUI.Theme.mediumRadius
    color: hoverEnabled && hovered ? LingmoUI.Theme.alternateBackgroundColor
                                   : LingmoUI.Theme.secondBackgroundColor

    HoverHandler {
        id: hoverHandler
        enabled: card.hoverEnabled
    }
}
