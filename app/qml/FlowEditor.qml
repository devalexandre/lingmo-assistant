import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Shapes
import LingmoUI.CompatibleModule 3.0 as LingmoUI
import Lingmo.Assistant

// The workflow flowEditor: palette, pan-and-zoom canvas with curved edges,
// inspector, minimap, undo/redo, auto-layout, live run highlighting.
Item {
    id: flowEditor

    readonly property var doc: assistant.flow
    property string selected: ""
    property real zoom: 1.0
    property real panX: 40
    property real panY: 30
    readonly property alias world: world
    readonly property real nodeWidth: 200
    // bumped whenever a block moves, so edges follow
    property int geometryTick: 0

    // connecting
    property bool connecting: false
    property string connectFrom: ""
    property string connectPort: ""
    property point connectPoint: Qt.point(0, 0)
    property string hoverTarget: ""

    function nodeHeight(ports) { return 78 + Math.max(0, ports - 1) * 24 }
    function portOffset(i) { return 40 + i * 24 }

    function outPoint(id, port) {
        const n = doc.node(id)
        if (!n.id)
            return Qt.point(0, 0)
        const i = Math.max(0, doc.ports(id).indexOf(port))
        return Qt.point(n.x + nodeWidth, n.y + portOffset(i))
    }
    function inPoint(id) {
        const n = doc.node(id)
        return n.id ? Qt.point(n.x, n.y + portOffset(0)) : Qt.point(0, 0)
    }

    function nodeAt(p) {
        const ids = doc.nodeIds()
        for (let i = 0; i < ids.length; ++i) {
            const id = ids[i]
            const n = doc.node(id)
            const h = nodeHeight(doc.ports(id).length)
            if (p.x >= n.x - 12 && p.x <= n.x + nodeWidth && p.y >= n.y - 6 && p.y <= n.y + h + 6)
                return id
        }
        return ""
    }

    function beginConnect(from, port) {
        connectFrom = from
        connectPort = port
        connectPoint = outPoint(from, port)
        connecting = true
    }
    function dragConnect(p) {
        connectPoint = p
        const t = nodeAt(p)
        hoverTarget = t !== connectFrom && doc.hasInput(t) && !doc.wouldCycle(connectFrom, t) ? t : ""
    }
    function endConnect() {
        if (hoverTarget !== "")
            doc.connectPorts(connectFrom, connectPort, hoverTarget)
        connecting = false
        hoverTarget = ""
    }

    function toWorld(item, x, y) {
        const p = item.mapToItem(canvas, x, y)
        return Qt.point((p.x - panX) / zoom, (p.y - panY) / zoom)
    }

    function setZoom(z, cx, cy) {
        z = Math.max(0.3, Math.min(2.0, z))
        // keep the point under the cursor still
        const wx = (cx - panX) / zoom, wy = (cy - panY) / zoom
        zoom = z
        panX = cx - wx * zoom
        panY = cy - wy * zoom
    }

    function fit() {
        const b = doc.bounds
        if (b.width <= 0 || canvas.width <= 0)
            return
        if (canvas.width < 200 || canvas.height < 200)
            return
        const z = Math.max(0.5, Math.min(1.0, Math.min((canvas.width - 120) / b.width, (canvas.height - 200) / b.height)))
        fitting = true
        zoom = z
        fitting = false
        panX = (canvas.width - b.width * z) / 2 - b.x * z
        panY = (canvas.height - b.height * z) / 2 - b.y * z
    }

    function addFromPalette(type, worldPoint) {
        const id = doc.addNode(type, Math.round(worldPoint.x / 10) * 10, Math.round(worldPoint.y / 10) * 10)
        if (id !== "") {
            // drop on top of the selected block's right side: connect it
            if (selected !== "" && selected !== id && doc.ports(selected).length === 1 && doc.hasInput(id)
                    && !doc.wouldCycle(selected, id) && autoConnect)
                doc.connectPorts(selected, doc.ports(selected)[0], id)
            selected = id
        }
    }
    property bool autoConnect: true
    // until the user pans or zooms, keep the whole workflow in view
    property bool userMoved: false
    onZoomChanged: if (!fitting) userMoved = true
    property bool fitting: false

    Connections {
        target: flowEditor.doc.nodes
        function onDataChanged() { flowEditor.geometryTick++ }
        function onModelReset() {
            flowEditor.geometryTick++
            if (flowEditor.doc.nodes.indexOf(flowEditor.selected) < 0)
                flowEditor.selected = ""
            flowEditor.userMoved = false
            Qt.callLater(flowEditor.fit)
        }
        function onRowsInserted() { flowEditor.geometryTick++ }
        function onRowsRemoved() { flowEditor.geometryTick++; if (flowEditor.doc.nodes.indexOf(flowEditor.selected) < 0) flowEditor.selected = "" }
    }

    Component.onCompleted: Qt.callLater(fit)

    Shortcut { sequences: [StandardKey.Undo]; onActivated: flowEditor.doc.undo() }
    Shortcut { sequences: [StandardKey.Redo, "Ctrl+Shift+Z"]; onActivated: flowEditor.doc.redo() }
    Shortcut { sequences: [StandardKey.Save]; onActivated: assistant.saveFlow() }
    Shortcut {
        sequences: [StandardKey.Delete]
        enabled: flowEditor.selected !== "" && !(activeFocusItem && activeFocusItem.hasOwnProperty("cursorPosition"))
        onActivated: { flowEditor.doc.removeNode(flowEditor.selected); flowEditor.selected = "" }
    }
    Shortcut { sequence: "Ctrl+D"; enabled: flowEditor.selected !== ""; onActivated: flowEditor.selected = flowEditor.doc.duplicateNode(flowEditor.selected) }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ------------------------------------------------------------ toolbar
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: LingmoUI.Units.windowHeaderHeight + LingmoUI.Units.smallSpacing
            Layout.leftMargin: LingmoUI.Units.largeSpacing
            Layout.rightMargin: LingmoUI.Units.largeSpacing * 4
            spacing: LingmoUI.Units.smallSpacing

            LingmoUI.IconButton {
                iconName: "go-previous"
                tipText: qsTr("All workflows")
                onClicked: assistant.closeFlow()
            }

            TextField {
                id: nameField
                Layout.fillWidth: true
                Layout.maximumWidth: 460
                Layout.minimumWidth: 160
                text: flowEditor.doc.name
                font.pointSize: LingmoUI.Units.fontSubheading
                font.bold: true
                background: Rectangle {
                    radius: LingmoUI.Theme.smallRadius
                    color: nameField.activeFocus || nameHover.hovered ? LingmoUI.Theme.alternateBackgroundColor : "transparent"
                }
                HoverHandler { id: nameHover }
                onEditingFinished: flowEditor.doc.name = text
            }

            LingmoUI.Badge {
                visible: flowEditor.doc.dirty || flowEditor.doc.revision === 0
                text: flowEditor.doc.revision === 0 ? qsTr("Not saved") : qsTr("Edited")
                tone: LingmoUI.Theme.orangeColor
                subtle: true
            }
            LingmoUI.Badge {
                visible: !flowEditor.doc.dirty && flowEditor.doc.revision > 0
                text: qsTr("Version %1").arg(flowEditor.doc.revision)
                subtle: true
            }

            Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }

            LingmoUI.IconButton { iconName: "edit-undo"; tipText: qsTr("Undo (Ctrl+Z)"); enabled: flowEditor.doc.canUndo; onClicked: flowEditor.doc.undo() }
            LingmoUI.IconButton { iconName: "edit-redo"; tipText: qsTr("Redo (Ctrl+Shift+Z)"); enabled: flowEditor.doc.canRedo; onClicked: flowEditor.doc.redo() }
            LingmoUI.IconButton { iconName: "distribute-graph-directed"; tipText: qsTr("Tidy up the blocks"); onClicked: { flowEditor.doc.autoLayout(); Qt.callLater(flowEditor.fit) } }
            LingmoUI.IconButton { iconName: "zoom-fit-best"; tipText: qsTr("Fit to window"); onClicked: flowEditor.fit() }
            LingmoUI.IconButton { iconName: "document-export"; tipText: qsTr("Export…"); onClicked: exportDialog.open() }

            Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 22; color: LingmoUI.Theme.dividerColor }

            LingmoUI.ActionButton {
                visible: assistant.runId === ""
                text: qsTr("Test")
                iconName: "debug-run"
                tipText: qsTr("Runs now, highlighting each block and asking before every change")
                enabled: flowEditor.doc.revision > 0 && !flowEditor.doc.dirty
                onClicked: assistant.runFlow(true)
            }
            LingmoUI.ActionButton {
                visible: assistant.runId === ""
                text: qsTr("Run")
                iconName: "media-playback-start"
                enabled: flowEditor.doc.revision > 0 && !flowEditor.doc.dirty
                onClicked: assistant.runFlow(false)
            }
            LingmoUI.ActionButton {
                visible: assistant.runId !== ""
                text: qsTr("Stop")
                iconName: "media-playback-stop"
                destructive: true
                onClicked: assistant.stopRun()
            }
            LingmoUI.ActionButton {
                primary: true
                text: qsTr("Save")
                iconName: "document-save"
                enabled: flowEditor.doc.dirty || flowEditor.doc.revision === 0
                onClicked: assistant.saveFlow()
            }
        }

        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: LingmoUI.Theme.dividerColor }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            FlowPalette {
                Layout.fillHeight: true
                Layout.preferredWidth: 220
                Layout.minimumWidth: 220
                Layout.maximumWidth: 220
                editor: flowEditor
            }

            Rectangle { Layout.fillHeight: true; Layout.preferredWidth: 1; color: LingmoUI.Theme.dividerColor }

            // ------------------------------------------------------------ canvas
            Item {
                id: canvas
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 200
                Layout.preferredWidth: 400
                clip: true
                onWidthChanged: if (!flowEditor.userMoved) Qt.callLater(flowEditor.fit)
                onHeightChanged: if (!flowEditor.userMoved) Qt.callLater(flowEditor.fit)

                Rectangle {
                    anchors.fill: parent
                    color: LingmoUI.Theme.darkMode ? Qt.rgba(0, 0, 0, 0.18) : Qt.rgba(0, 0, 0, 0.025)
                }

                // Background: drag to pan, click to deselect. A MouseArea (not a
                // pointer handler) so the press never reaches the frameless window's
                // move area; the blocks' own handlers take the grab over from it.
                MouseArea {
                    id: panArea
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton
                    property real startX
                    property real startY
                    property point pressAt
                    property bool moved: false
                    cursorShape: pressed && moved ? Qt.ClosedHandCursor : Qt.ArrowCursor
                    onPressed: (mouse) => {
                        startX = flowEditor.panX
                        startY = flowEditor.panY
                        pressAt = Qt.point(mouse.x, mouse.y)
                        moved = false
                    }
                    onPositionChanged: (mouse) => {
                        if (!pressed)
                            return
                        const dx = mouse.x - pressAt.x, dy = mouse.y - pressAt.y
                        if (!moved && Math.abs(dx) + Math.abs(dy) < 4)
                            return
                        moved = true
                        flowEditor.userMoved = true
                        flowEditor.panX = startX + dx
                        flowEditor.panY = startY + dy
                    }
                    onClicked: if (!moved) flowEditor.selected = ""
                }

                // dot grid that pans and zooms with the blocks
                Canvas {
                    id: grid
                    anchors.fill: parent
                    property real step: 24 * flowEditor.zoom
                    property color dot: LingmoUI.Theme.darkMode ? Qt.rgba(1, 1, 1, 0.10) : Qt.rgba(0, 0, 0, 0.12)
                    onStepChanged: requestPaint()
                    onDotChanged: requestPaint()
                    onWidthChanged: requestPaint()
                    onHeightChanged: requestPaint()
                    Connections {
                        target: flowEditor
                        function onPanXChanged() { grid.requestPaint() }
                        function onPanYChanged() { grid.requestPaint() }
                    }
                    onPaint: {
                        const ctx = getContext("2d")
                        ctx.clearRect(0, 0, width, height)
                        if (step < 8)
                            return
                        ctx.fillStyle = dot
                        const ox = ((flowEditor.panX % step) + step) % step
                        const oy = ((flowEditor.panY % step) + step) % step
                        const r = Math.max(1, 1.2 * flowEditor.zoom)
                        for (let x = ox; x < width; x += step)
                            for (let y = oy; y < height; y += step)
                                ctx.fillRect(x - r / 2, y - r / 2, r, r)
                    }
                }

                // zoom with the wheel (Ctrl or a mouse wheel), pan with a touchpad
                WheelHandler {
                    acceptedModifiers: Qt.ControlModifier
                    onWheel: (event) => flowEditor.setZoom(flowEditor.zoom * (event.angleDelta.y > 0 ? 1.1 : 1 / 1.1), point.position.x, point.position.y)
                }
                WheelHandler {
                    acceptedModifiers: Qt.NoModifier
                    onWheel: (event) => {
                        if (event.pixelDelta.y !== 0 || event.pixelDelta.x !== 0) {
                            flowEditor.panX += event.pixelDelta.x
                            flowEditor.panY += event.pixelDelta.y
                        } else {
                            flowEditor.setZoom(flowEditor.zoom * (event.angleDelta.y > 0 ? 1.1 : 1 / 1.1), point.position.x, point.position.y)
                        }
                    }
                }
                PinchHandler {
                    target: null
                    property real startZoom
                    onActiveChanged: if (active) startZoom = flowEditor.zoom
                    onActiveScaleChanged: flowEditor.setZoom(startZoom * activeScale, centroid.position.x, centroid.position.y)
                }

                Item {
                    id: world
                    x: flowEditor.panX
                    y: flowEditor.panY
                    width: 1
                    height: 1
                    scale: flowEditor.zoom
                    transformOrigin: Item.TopLeft

                    // edges
                    Repeater {
                        model: flowEditor.doc.edges
                        delegate: Shape {
                            id: edge
                            required property string fromNode
                            required property string port
                            required property string toNode
                            required property bool active
                            required property int index
                            readonly property point a: { flowEditor.geometryTick; return flowEditor.outPoint(fromNode, port) }
                            readonly property point b: { flowEditor.geometryTick; return flowEditor.inPoint(toNode) }
                            readonly property real dx: Math.max(50, Math.abs(b.x - a.x) / 2)
                            readonly property bool hot: edgeHover.hovered
                            z: 0
                            preferredRendererType: Shape.CurveRenderer
                            containsMode: Shape.FillContains

                            ShapePath {
                                strokeWidth: edge.hot ? 3.5 : edge.active ? 3 : 2
                                strokeColor: edge.hot ? LingmoUI.Theme.redColor
                                           : edge.active ? LingmoUI.Theme.highlightColor
                                           : (LingmoUI.Theme.darkMode ? Qt.rgba(1, 1, 1, 0.35) : Qt.rgba(0, 0, 0, 0.30))
                                fillColor: "transparent"
                                capStyle: ShapePath.RoundCap
                                startX: edge.a.x; startY: edge.a.y
                                PathCubic {
                                    x: edge.b.x; y: edge.b.y
                                    control1X: edge.a.x + edge.dx; control1Y: edge.a.y
                                    control2X: edge.b.x - edge.dx; control2Y: edge.b.y
                                }
                            }
                            // arrow head
                            ShapePath {
                                strokeWidth: 0
                                strokeColor: "transparent"
                                fillColor: edge.hot ? LingmoUI.Theme.redColor
                                         : edge.active ? LingmoUI.Theme.highlightColor
                                         : (LingmoUI.Theme.darkMode ? Qt.rgba(1, 1, 1, 0.45) : Qt.rgba(0, 0, 0, 0.40))
                                startX: edge.b.x - 9; startY: edge.b.y - 5
                                PathLine { x: edge.b.x - 1; y: edge.b.y }
                                PathLine { x: edge.b.x - 9; y: edge.b.y + 5 }
                            }

                            // hover on the middle of an edge to remove it
                            Item {
                                x: (edge.a.x + edge.b.x) / 2 - 14
                                y: (edge.a.y + edge.b.y) / 2 - 14
                                width: 28; height: 28
                                HoverHandler { id: edgeHover }
                                MouseArea { anchors.fill: parent; onClicked: flowEditor.doc.removeEdge(edge.index) }
                                Rectangle {
                                    anchors.centerIn: parent
                                    width: 20; height: 20; radius: 10
                                    visible: edgeHover.hovered
                                    color: LingmoUI.Theme.redColor
                                    LingmoUI.IconItem { anchors.centerIn: parent; width: 12; height: 12; source: "edit-delete-remove"; color: "white" }
                                }
                            }
                        }
                    }

                    // the edge being dragged
                    Shape {
                        id: pending
                        visible: flowEditor.connecting
                        preferredRendererType: Shape.CurveRenderer
                        readonly property point a: { flowEditor.geometryTick; return flowEditor.connecting ? flowEditor.outPoint(flowEditor.connectFrom, flowEditor.connectPort) : Qt.point(0, 0) }
                        readonly property point b: flowEditor.connectPoint
                        ShapePath {
                            strokeWidth: 2.5
                            strokeColor: LingmoUI.Theme.highlightColor
                            strokeStyle: flowEditor.hoverTarget === "" ? ShapePath.DashLine : ShapePath.SolidLine
                            dashPattern: [4, 3]
                            fillColor: "transparent"
                            startX: pending.a.x; startY: pending.a.y
                            PathCubic {
                                x: pending.b.x; y: pending.b.y
                                control1X: pending.a.x + 60; control1Y: pending.a.y
                                control2X: pending.b.x - 60; control2Y: pending.b.y
                            }
                        }
                    }

                    Repeater {
                        model: flowEditor.doc.nodes
                        delegate: FlowNode { editor: flowEditor }
                    }
                }

                // empty canvas hint
                LingmoUI.EmptyState {
                    anchors.centerIn: parent
                    width: Math.min(420, parent.width - 40)
                    visible: flowEditor.doc.nodes.count <= 1
                    iconName: "code-branch"
                    title: qsTr("Drag blocks from the left")
                    text: qsTr("Then connect the dot on the right of a block to the next one. Use {{ }} in text fields to reuse what earlier blocks produced.")
                }

                // ------------------------------------------------------------ run banner
                LingmoUI.Card {
                    id: runBanner
                    anchors.top: parent.top
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.topMargin: LingmoUI.Units.largeSpacing
                    width: Math.min(parent.width - 40, runRow.implicitWidth + LingmoUI.Units.largeSpacing * 3)
                    implicitHeight: runRow.implicitHeight + LingmoUI.Units.largeSpacing * 1.4
                    elevation: 2
                    visible: assistant.runId !== "" || (assistant.runStatus !== "" && !bannerClosed)
                    property bool bannerClosed: false
                    Connections {
                        target: assistant
                        function onRunChanged() { runBanner.bannerClosed = false }
                    }

                    RowLayout {
                        id: runRow
                        anchors.centerIn: parent
                        spacing: LingmoUI.Units.largeSpacing
                        LingmoUI.Spinner {
                            visible: assistant.runId !== ""
                            running: visible
                            size: LingmoUI.Units.iconSizes.small
                        }
                        LingmoUI.IconItem {
                            visible: assistant.runId === ""
                            Layout.preferredWidth: 18; Layout.preferredHeight: 18
                            source: assistant.runStatus === "done" ? "dialog-ok-apply" : assistant.runStatus === "stopped" ? "media-playback-stop" : "dialog-error"
                            color: Ui.statusColor(assistant.runStatus)
                        }
                        Label {
                            Layout.maximumWidth: 520
                            elide: Text.ElideRight
                            color: LingmoUI.Theme.textColor
                            text: assistant.runId !== ""
                                  ? (assistant.runMode === "test" ? qsTr("Testing… each change asks first") : qsTr("Running…"))
                                  : assistant.runStatus === "done" ? qsTr("Finished")
                                  : assistant.runStatus === "stopped" ? qsTr("Stopped")
                                  : assistant.runError
                        }
                        LingmoUI.IconButton {
                            visible: assistant.runId === ""
                            iconName: "window-close"
                            size: 22
                            onClicked: runBanner.bannerClosed = true
                        }
                    }
                }

                // ------------------------------------------------------------ questions of the run
                ColumnLayout {
                    anchors.bottom: parent.bottom
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottomMargin: LingmoUI.Units.largeSpacing * 1.5
                    width: Math.min(parent.width - 60, 520)
                    spacing: LingmoUI.Units.smallSpacing
                    z: 10
                    Repeater {
                        model: assistant.flowAsks.filter(a => a.flow_id === flowEditor.doc.flowId)
                        delegate: AskCard { Layout.fillWidth: true }
                    }
                }

                // ------------------------------------------------------------ zoom and minimap
                Row {
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    anchors.margins: LingmoUI.Units.largeSpacing
                    spacing: 2
                    LingmoUI.IconButton { iconName: "zoom-out"; tipText: qsTr("Zoom out"); onClicked: flowEditor.setZoom(flowEditor.zoom / 1.2, canvas.width / 2, canvas.height / 2) }
                    Label {
                        width: 46
                        height: 28
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        text: Math.round(flowEditor.zoom * 100) + "%"
                        color: LingmoUI.Theme.secondaryTextColor
                        font.pointSize: LingmoUI.Units.fontCaption
                        MouseArea { anchors.fill: parent; onClicked: flowEditor.setZoom(1, canvas.width / 2, canvas.height / 2) }
                    }
                    LingmoUI.IconButton { iconName: "zoom-in"; tipText: qsTr("Zoom in"); onClicked: flowEditor.setZoom(flowEditor.zoom * 1.2, canvas.width / 2, canvas.height / 2) }
                }

                Minimap {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.margins: LingmoUI.Units.largeSpacing
                    editor: flowEditor
                    viewport: canvas
                }
            }

            Rectangle { Layout.fillHeight: true; Layout.preferredWidth: 1; color: LingmoUI.Theme.dividerColor }

            // ------------------------------------------------------------ inspector
            Loader {
                Layout.fillHeight: true
                Layout.preferredWidth: 310
                Layout.minimumWidth: 310
                Layout.maximumWidth: 310
                sourceComponent: flowEditor.selected !== "" ? nodeInspector : flowInspector
            }
        }
    }

    Component {
        id: nodeInspector
        NodeInspector { editor: flowEditor; nodeId: flowEditor.selected }
    }
    Component {
        id: flowInspector
        FlowInspector { editor: flowEditor }
    }

    // palette drag: the ghost follows the pointer over everything
    Rectangle {
        id: ghost
        property string type: ""
        property var info: ({})
        visible: type !== ""
        width: 200; height: 48
        radius: LingmoUI.Theme.bigRadius
        color: LingmoUI.Theme.secondBackgroundColor
        border.color: LingmoUI.Theme.highlightColor
        border.width: 2
        opacity: 0.92
        z: 100
        RowLayout {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 8
            Rectangle {
                Layout.preferredWidth: 26; Layout.preferredHeight: 26
                radius: LingmoUI.Theme.smallRadius
                color: Ui.color(ghost.info.category || "")
                LingmoUI.IconItem { anchors.centerIn: parent; width: 16; height: 16; source: ghost.info.icon || ""; color: "white" }
            }
            Label { Layout.fillWidth: true; text: ghost.info.label || ""; elide: Text.ElideRight; color: LingmoUI.Theme.textColor; font.bold: true }
        }
    }

    function paletteDrag(type, info, item, pos, active) {
        if (active) {
            ghost.type = type
            ghost.info = info
            const p = item.mapToItem(flowEditor, pos.x, pos.y)
            ghost.x = p.x - 30
            ghost.y = p.y - 24
            return
        }
        // dropped
        const c = item.mapToItem(canvas, pos.x, pos.y)
        if (ghost.type !== "" && c.x >= 0 && c.y >= 0 && c.x <= canvas.width && c.y <= canvas.height)
            addFromPalette(ghost.type, Qt.point((c.x - panX) / zoom - 30, (c.y - panY) / zoom - 24))
        ghost.type = ""
    }

    function paletteAdd(type) {
        // click: next to the selected block, or in the middle of the view
        let p = Qt.point((canvas.width / 2 - panX) / zoom - nodeWidth / 2, (canvas.height / 2 - panY) / zoom - 40)
        if (selected !== "") {
            const n = doc.node(selected)
            p = Qt.point(n.x + nodeWidth + 70, n.y)
        }
        addFromPalette(type, p)
    }

    FileDialog {
        id: exportDialog
        title: qsTr("Export workflow")
        fileMode: FileDialog.SaveFile
        nameFilters: [qsTr("Workflows (*.json)")]
        defaultSuffix: "json"
        onAccepted: assistant.exportFlow(selectedFile)
    }
}
