pragma Singleton
import QtQuick
import LingmoUI.CompatibleModule 3.0 as LingmoUI

// Shared look and state of the Assistant's pages (registered as the "Ui" singleton)
QtObject {
    // Colour of each node category on the canvas, the palette and the lists
    function color(category) {
        switch (category) {
        case "triggers": return LingmoUI.Theme.orangeColor
        case "actions": return LingmoUI.Theme.blueColor
        case "ai": return LingmoUI.Theme.purpleColor
        case "logic": return LingmoUI.Theme.greenColor
        }
        return LingmoUI.Theme.greyColor
    }

    function triggerIcon(type) {
        switch (type) {
        case "trigger.schedule": return "chronometer"
        case "trigger.email": return "mail-unread"
        case "trigger.calendar": return "appointment-soon"
        case "trigger.file": return "folder-sync"
        case "trigger.shortcut": return "input-keyboard"
        case "trigger.voice": return "audio-input-microphone"
        case "trigger.system": return "computer"
        }
        return "media-playback-start"
    }

    readonly property var agentPalette: [LingmoUI.Theme.blueColor, LingmoUI.Theme.purpleColor,
                                          LingmoUI.Theme.pinkColor, LingmoUI.Theme.orangeColor,
                                          LingmoUI.Theme.greenColor, LingmoUI.Theme.redColor]
    function agentColor(id) {
        let h = 0
        for (let i = 0; i < (id || "").length; ++i)
            h = (h * 31 + id.charCodeAt(i)) % 9973
        return agentPalette[h % agentPalette.length]
    }

    function statusColor(status) {
        switch (status) {
        case "running": return LingmoUI.Theme.highlightColor
        case "waiting": return LingmoUI.Theme.orangeColor
        case "done": return LingmoUI.Theme.greenColor
        case "error": case "failed": case "refused": return LingmoUI.Theme.redColor
        case "declined": case "stopped": return LingmoUI.Theme.greyColor
        }
        return "transparent"
    }

    // A page asks the window to show the capability approval dialog
    signal approvalRequested(var info)

    // The agent open in the editor ("" = none, "new" = a new one)
    property string editingAgentId: ""
    property var editingAgent: null
    signal agentEditRequested(var agent)
    function editAgent(agent) {
        editingAgent = agent
        editingAgentId = agent && agent.id ? agent.id : "new"
        agentEditRequested(agent)
    }
    function closeAgentEditor() {
        editingAgent = null
        editingAgentId = ""
    }
}
