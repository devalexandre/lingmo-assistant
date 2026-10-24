/*
 * Copyright (C) 2026 LingmoOS Team.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * any later version.
 */

#include "flowdocument.h"

#include <QJsonArray>
#include <algorithm>
#include <QJSValue>
#include <QJsonDocument>
#include <QRectF>
#include <QRegularExpression>
#include <QSet>

#include <algorithm>

static constexpr int MaxUndo = 100;
static const QString TriggerPrefix = QStringLiteral("trigger.");

// ------------------------------------------------------------------ FlowNodeModel

int FlowNodeModel::rowCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : m_items.size();
}

QVariant FlowNodeModel::data(const QModelIndex &index, int role) const
{
    if (!index.isValid() || index.row() >= m_items.size())
        return {};
    const Node &n = m_items.at(index.row());
    switch (role) {
    case IdRole: return n.id;
    case TypeRole: return n.type;
    case LabelRole: return n.label;
    case XRole: return n.x;
    case YRole: return n.y;
    case ParamsRole: return n.params;
    case StatusRole: return n.status;
    case OutputRole: return n.output;
    case ErrorRole: return n.error;
    case IssueRole: return n.issue;
    case IssueLevelRole: return n.issueLevel;
    }
    return {};
}

QHash<int, QByteArray> FlowNodeModel::roleNames() const
{
    return {{IdRole, "nodeId"}, {TypeRole, "nodeType"}, {LabelRole, "label"}, {XRole, "posX"}, {YRole, "posY"},
            {ParamsRole, "params"}, {StatusRole, "status"}, {OutputRole, "output"}, {ErrorRole, "error"},
            {IssueRole, "issue"}, {IssueLevelRole, "issueLevel"}};
}

int FlowNodeModel::indexOf(const QString &id) const
{
    for (int i = 0; i < m_items.size(); ++i)
        if (m_items.at(i).id == id)
            return i;
    return -1;
}

void FlowNodeModel::setItems(const QList<Node> &items)
{
    beginResetModel();
    m_items = items;
    endResetModel();
    Q_EMIT countChanged();
}

void FlowNodeModel::append(const Node &node)
{
    beginInsertRows({}, m_items.size(), m_items.size());
    m_items.append(node);
    endInsertRows();
    Q_EMIT countChanged();
}

void FlowNodeModel::remove(int row)
{
    beginRemoveRows({}, row, row);
    m_items.removeAt(row);
    endRemoveRows();
    Q_EMIT countChanged();
}

void FlowNodeModel::touch(int row, const QList<int> &roles)
{
    const QModelIndex i = index(row);
    Q_EMIT dataChanged(i, i, roles);
}

// ------------------------------------------------------------------ FlowEdgeModel

int FlowEdgeModel::rowCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : m_items.size();
}

QVariant FlowEdgeModel::data(const QModelIndex &index, int role) const
{
    if (!index.isValid() || index.row() >= m_items.size())
        return {};
    const Edge &e = m_items.at(index.row());
    switch (role) {
    case FromRole: return e.from;
    case PortRole: return e.port;
    case ToRole: return e.to;
    case ActiveRole: return e.active;
    }
    return {};
}

QHash<int, QByteArray> FlowEdgeModel::roleNames() const
{
    return {{FromRole, "fromNode"}, {PortRole, "port"}, {ToRole, "toNode"}, {ActiveRole, "active"}};
}

void FlowEdgeModel::setItems(const QList<Edge> &items)
{
    beginResetModel();
    m_items = items;
    endResetModel();
    Q_EMIT countChanged();
}

void FlowEdgeModel::append(const Edge &edge)
{
    beginInsertRows({}, m_items.size(), m_items.size());
    m_items.append(edge);
    endInsertRows();
    Q_EMIT countChanged();
}

void FlowEdgeModel::remove(int row)
{
    beginRemoveRows({}, row, row);
    m_items.removeAt(row);
    endRemoveRows();
    Q_EMIT countChanged();
}

void FlowEdgeModel::setActiveInto(const QString &to)
{
    for (int i = 0; i < m_items.size(); ++i) {
        if (m_items.at(i).to == to && !m_items.at(i).active) {
            m_items[i].active = true;
            Q_EMIT dataChanged(index(i), index(i), {ActiveRole});
        }
    }
}

void FlowEdgeModel::clearActive()
{
    for (int i = 0; i < m_items.size(); ++i) {
        if (m_items.at(i).active) {
            m_items[i].active = false;
            Q_EMIT dataChanged(index(i), index(i), {ActiveRole});
        }
    }
}

// ------------------------------------------------------------------ FlowDocument

FlowDocument::FlowDocument(QObject *parent)
    : QObject(parent)
    , m_nodes(new FlowNodeModel(this))
    , m_edges(new FlowEdgeModel(this))
{
}

void FlowDocument::setCatalogue(const QVariantMap &catalogue)
{
    m_catalogue = catalogue;
    m_types.clear();
    for (const QVariant &v : catalogue.value(QStringLiteral("types")).toList()) {
        const QVariantMap t = v.toMap();
        m_types.insert(t.value(QStringLiteral("type")).toString(), t);
    }
    Q_EMIT catalogueChanged();
    Q_EMIT changed();
}

QString FlowDocument::triggerId() const
{
    for (const auto &n : m_nodes->items())
        if (n.type.startsWith(TriggerPrefix))
            return n.id;
    return {};
}

QRectF FlowDocument::bounds() const
{
    if (m_nodes->items().isEmpty())
        return {0, 0, 800, 500};
    qreal x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const auto &n : m_nodes->items()) {
        x0 = std::min(x0, n.x);
        y0 = std::min(y0, n.y);
        x1 = std::max(x1, n.x + 200);
        y1 = std::max(y1, n.y + 110);
    }
    return {x0, y0, x1 - x0, y1 - y0};
}

void FlowDocument::setName(const QString &name)
{
    const QString clean = name.simplified().left(120);
    if (clean == this->name())
        return;
    snapshot();
    m_meta.insert(QStringLiteral("name"), clean);
    setDirty(true);
    Q_EMIT changed();
}

void FlowDocument::setDescription(const QString &text)
{
    if (text == description())
        return;
    snapshot();
    m_meta.insert(QStringLiteral("description"), text.left(2000));
    setDirty(true);
    Q_EMIT changed();
}

void FlowDocument::setEnabled(bool on)
{
    if (on == enabled())
        return;
    snapshot();
    m_meta.insert(QStringLiteral("enabled"), on);
    setDirty(true);
    Q_EMIT changed();
}

void FlowDocument::setDirty(bool dirty)
{
    if (dirty == m_dirty)
        return;
    m_dirty = dirty;
    Q_EMIT dirtyChanged();
}

// ------------------------------------------------------------------ load / save

void FlowDocument::load(const QVariantMap &flow)
{
    m_meta.clear();
    for (const QString &key : {QStringLiteral("format"), QStringLiteral("format_version"), QStringLiteral("id"),
                               QStringLiteral("name"), QStringLiteral("description"), QStringLiteral("revision"),
                               QStringLiteral("enabled"), QStringLiteral("created"), QStringLiteral("updated")})
        if (flow.contains(key))
            m_meta.insert(key, flow.value(key));
    if (!m_meta.contains(QStringLiteral("enabled")))
        m_meta.insert(QStringLiteral("enabled"), true);
    QList<FlowNodeModel::Node> nodes;
    for (const QVariant &v : flow.value(QStringLiteral("nodes")).toList()) {
        const QVariantMap m = v.toMap();
        FlowNodeModel::Node n;
        n.id = m.value(QStringLiteral("id")).toString();
        n.type = m.value(QStringLiteral("type")).toString();
        n.label = m.value(QStringLiteral("label")).toString();
        n.x = m.value(QStringLiteral("x")).toReal();
        n.y = m.value(QStringLiteral("y")).toReal();
        n.params = m.value(QStringLiteral("params")).toMap();
        nodes.append(n);
    }
    QList<FlowEdgeModel::Edge> edges;
    for (const QVariant &v : flow.value(QStringLiteral("edges")).toList()) {
        const QVariantMap m = v.toMap();
        edges.append({m.value(QStringLiteral("from")).toString(),
                      m.value(QStringLiteral("port"), QStringLiteral("out")).toString(),
                      m.value(QStringLiteral("to")).toString(), false});
    }
    m_nodes->setItems(nodes);
    m_edges->setItems(edges);
    m_undo.clear();
    m_redo.clear();
    m_loaded = true;
    setDirty(false);
    Q_EMIT historyChanged();
    Q_EMIT changed();
    Q_EMIT geometryChanged();
}

void FlowDocument::clear()
{
    m_meta.clear();
    m_nodes->setItems({});
    m_edges->setItems({});
    m_undo.clear();
    m_redo.clear();
    m_loaded = false;
    setDirty(false);
    Q_EMIT historyChanged();
    Q_EMIT changed();
}

QJsonObject FlowDocument::toJsonObject() const
{
    QJsonObject o = QJsonObject::fromVariantMap(m_meta);
    o.insert(QStringLiteral("format"), QStringLiteral("lingmo-assistant-flow"));
    o.insert(QStringLiteral("format_version"), 1);
    QJsonArray nodes;
    for (const auto &n : m_nodes->items()) {
        nodes.append(QJsonObject{{QStringLiteral("id"), n.id}, {QStringLiteral("type"), n.type},
                                 {QStringLiteral("label"), n.label}, {QStringLiteral("x"), qRound(n.x * 10) / 10.0},
                                 {QStringLiteral("y"), qRound(n.y * 10) / 10.0},
                                 {QStringLiteral("params"), QJsonObject::fromVariantMap(n.params)}});
    }
    QJsonArray edges;
    for (const auto &e : m_edges->items())
        edges.append(QJsonObject{{QStringLiteral("from"), e.from}, {QStringLiteral("port"), e.port},
                                 {QStringLiteral("to"), e.to}});
    o.insert(QStringLiteral("nodes"), nodes);
    o.insert(QStringLiteral("edges"), edges);
    return o;
}

QVariantMap FlowDocument::toVariant() const
{
    return toJsonObject().toVariantMap();
}

QString FlowDocument::toJson() const
{
    return QString::fromUtf8(QJsonDocument(toJsonObject()).toJson(QJsonDocument::Indented));
}

bool FlowDocument::loadJson(const QString &json)
{
    QJsonParseError error;
    const QJsonDocument doc = QJsonDocument::fromJson(json.toUtf8(), &error);
    if (error.error != QJsonParseError::NoError || !doc.isObject())
        return false;
    const QJsonObject o = doc.object();
    if (o.value(QStringLiteral("format")).toString(QStringLiteral("lingmo-assistant-flow"))
        != QLatin1String("lingmo-assistant-flow"))
        return false;
    load(o.toVariantMap());
    return true;
}

void FlowDocument::markSaved(const QVariantMap &flow)
{
    // The engine's copy is the truth (id, revision); keep the undo history
    for (const QString &key : {QStringLiteral("id"), QStringLiteral("revision"), QStringLiteral("enabled"),
                               QStringLiteral("created"), QStringLiteral("updated")})
        if (flow.contains(key))
            m_meta.insert(key, flow.value(key));
    setDirty(false);
    Q_EMIT changed();
}

// ------------------------------------------------------------------ undo

void FlowDocument::snapshot()
{
    m_undo.append(toJsonObject());
    if (m_undo.size() > MaxUndo)
        m_undo.removeFirst();
    m_redo.clear();
    Q_EMIT historyChanged();
}

void FlowDocument::restore(const QJsonObject &state)
{
    const bool wasLoaded = m_loaded;
    const QList<QJsonObject> undo = m_undo, redo = m_redo;
    load(state.toVariantMap());
    m_undo = undo;
    m_redo = redo;
    m_loaded = wasLoaded || m_loaded;
    setDirty(true);
    Q_EMIT historyChanged();
}

void FlowDocument::undo()
{
    if (m_undo.isEmpty())
        return;
    m_redo.append(toJsonObject());
    const QJsonObject state = m_undo.takeLast();
    restore(state);
}

void FlowDocument::redo()
{
    if (m_redo.isEmpty())
        return;
    m_undo.append(toJsonObject());
    const QJsonObject state = m_redo.takeLast();
    restore(state);
}

// ------------------------------------------------------------------ editing

QString FlowDocument::uniqueId(const QString &base, const QStringList &taken)
{
    QString clean = base.toLower();
    clean.replace(QRegularExpression(QStringLiteral("[^a-z0-9_]")), QStringLiteral("_"));
    if (clean.isEmpty() || !clean.at(0).isLetter())
        clean.prepend(QLatin1Char('n'));
    clean = clean.left(32);
    static const QStringList reserved = {QStringLiteral("var"), QStringLiteral("loop"), QStringLiteral("now"),
                                         QStringLiteral("run"), QStringLiteral("trigger")};
    if (!taken.contains(clean) && !reserved.contains(clean))
        return clean;
    for (int i = 2;; ++i) {
        const QString candidate = clean + QLatin1Char('_') + QString::number(i);
        if (!taken.contains(candidate))
            return candidate;
    }
}

QString FlowDocument::idBase(const QString &type) const
{
    static const QHash<QString, QString> names = {
        {QStringLiteral("action.mail.send"), QStringLiteral("email")},
        {QStringLiteral("action.mail.reply"), QStringLiteral("resposta")},
        {QStringLiteral("action.mail.organize"), QStringLiteral("organizar")},
        {QStringLiteral("action.mail.attachments"), QStringLiteral("anexos")},
        {QStringLiteral("action.contacts.add"), QStringLiteral("contato")},
        {QStringLiteral("action.calendar.event"), QStringLiteral("evento")},
        {QStringLiteral("action.calendar.task"), QStringLiteral("tarefa")},
        {QStringLiteral("action.clock.alarm"), QStringLiteral("alarme")},
        {QStringLiteral("action.clock.timer"), QStringLiteral("timer")},
        {QStringLiteral("action.notes.write"), QStringLiteral("nota")},
        {QStringLiteral("action.files.read"), QStringLiteral("arquivo")},
        {QStringLiteral("action.files.write"), QStringLiteral("gravar")},
        {QStringLiteral("action.system.notify"), QStringLiteral("aviso")},
        {QStringLiteral("action.system.speak"), QStringLiteral("falar")},
        {QStringLiteral("action.system.open"), QStringLiteral("abrir")},
        {QStringLiteral("action.system.screenshot"), QStringLiteral("captura")},
        {QStringLiteral("action.system.command"), QStringLiteral("comando")},
        {QStringLiteral("ai.agent"), QStringLiteral("agente")},
        {QStringLiteral("ai.summarize"), QStringLiteral("resumo")},
        {QStringLiteral("ai.classify"), QStringLiteral("categoria")},
        {QStringLiteral("ai.extract"), QStringLiteral("dados")},
        {QStringLiteral("ai.translate"), QStringLiteral("traducao")},
        {QStringLiteral("logic.if"), QStringLiteral("condicao")},
        {QStringLiteral("logic.switch"), QStringLiteral("escolha")},
        {QStringLiteral("logic.loop"), QStringLiteral("repetir")},
        {QStringLiteral("logic.wait"), QStringLiteral("esperar")},
        {QStringLiteral("logic.ask"), QStringLiteral("pergunta")},
        {QStringLiteral("logic.set"), QStringLiteral("variavel")},
    };
    if (type.startsWith(TriggerPrefix))
        return QStringLiteral("trigger");
    return names.value(type, type.section(QLatin1Char('.'), -1));
}

QString FlowDocument::addNode(const QString &type, qreal x, qreal y)
{
    if (!m_types.isEmpty() && !m_types.contains(type))
        return {};
    QStringList taken;
    for (const auto &n : m_nodes->items())
        taken << n.id;
    snapshot();
    // One trigger per workflow: a new trigger replaces the old one (edges kept)
    if (type.startsWith(TriggerPrefix)) {
        const QString old = triggerId();
        if (!old.isEmpty()) {
            const int row = m_nodes->indexOf(old);
            auto &n = m_nodes->at(row);
            n.type = type;
            n.params.clear();
            n.label.clear();
            // outgoing edges from a trigger always use "out"
            m_nodes->touch(row, {FlowNodeModel::TypeRole, FlowNodeModel::ParamsRole, FlowNodeModel::LabelRole});
            setDirty(true);
            Q_EMIT changed();
            return old;
        }
    }
    FlowNodeModel::Node n;
    n.type = type;
    n.id = type.startsWith(TriggerPrefix) && !taken.contains(QStringLiteral("trigger")) ? QStringLiteral("trigger")
                                                                                        : uniqueId(idBase(type), taken);
    n.x = x;
    n.y = y;
    m_nodes->append(n);
    setDirty(true);
    Q_EMIT changed();
    Q_EMIT geometryChanged();
    return n.id;
}

QString FlowDocument::duplicateNode(const QString &id)
{
    const int row = m_nodes->indexOf(id);
    if (row < 0 || m_nodes->items().at(row).type.startsWith(TriggerPrefix))
        return {};
    QStringList taken;
    for (const auto &n : m_nodes->items())
        taken << n.id;
    snapshot();
    FlowNodeModel::Node copy = m_nodes->items().at(row);
    copy.id = uniqueId(idBase(copy.type), taken);
    copy.x += 40;
    copy.y += 40;
    copy.status.clear();
    m_nodes->append(copy);
    setDirty(true);
    Q_EMIT changed();
    return copy.id;
}

void FlowDocument::removeNode(const QString &id)
{
    const int row = m_nodes->indexOf(id);
    if (row < 0)
        return;
    snapshot();
    for (int i = m_edges->items().size() - 1; i >= 0; --i) {
        const auto &e = m_edges->items().at(i);
        if (e.from == id || e.to == id)
            m_edges->remove(i);
    }
    m_nodes->remove(row);
    setDirty(true);
    Q_EMIT changed();
    Q_EMIT geometryChanged();
}

bool FlowDocument::wouldCycle(const QString &from, const QString &to) const
{
    // Is "from" reachable from "to"?
    QList<QString> todo{to};
    QSet<QString> seen;
    while (!todo.isEmpty()) {
        const QString x = todo.takeLast();
        if (x == from)
            return true;
        if (seen.contains(x))
            continue;
        seen.insert(x);
        for (const auto &e : m_edges->items())
            if (e.from == x)
                todo.append(e.to);
    }
    return false;
}

bool FlowDocument::connectPorts(const QString &from, const QString &port, const QString &to)
{
    if (from == to || m_nodes->indexOf(from) < 0 || m_nodes->indexOf(to) < 0)
        return false;
    if (!hasInput(to) || !ports(from).contains(port))
        return false;
    for (const auto &e : m_edges->items())
        if (e.from == from && e.port == port && e.to == to)
            return false;
    if (wouldCycle(from, to))
        return false;
    snapshot();
    m_edges->append({from, port, to, false});
    setDirty(true);
    Q_EMIT changed();
    return true;
}

void FlowDocument::removeEdge(int row)
{
    if (row < 0 || row >= m_edges->count())
        return;
    snapshot();
    m_edges->remove(row);
    setDirty(true);
    Q_EMIT changed();
}

void FlowDocument::setParam(const QString &id, const QString &param, const QVariant &value)
{
    const int row = m_nodes->indexOf(id);
    if (row < 0)
        return;
    QVariant v = value;
    if (v.canConvert<QJSValue>())
        v = v.value<QJSValue>().toVariant();
    if (m_nodes->items().at(row).params.value(param) == v)
        return;
    snapshot();
    m_nodes->at(row).params.insert(param, v);
    m_nodes->touch(row, {FlowNodeModel::ParamsRole});
    // a switch's ports follow its cases: drop edges from ports that no longer exist
    const QStringList valid = ports(id);
    for (int i = m_edges->items().size() - 1; i >= 0; --i) {
        const auto &e = m_edges->items().at(i);
        if (e.from == id && !valid.contains(e.port))
            m_edges->remove(i);
    }
    setDirty(true);
    Q_EMIT changed();
}

void FlowDocument::setLabel(const QString &id, const QString &label)
{
    const int row = m_nodes->indexOf(id);
    if (row < 0 || m_nodes->items().at(row).label == label)
        return;
    snapshot();
    m_nodes->at(row).label = label.left(120);
    m_nodes->touch(row, {FlowNodeModel::LabelRole});
    setDirty(true);
    Q_EMIT changed();
}

bool FlowDocument::renameNode(const QString &id, const QString &newId)
{
    static const QRegularExpression valid(QStringLiteral("^[a-z][a-z0-9_]{0,39}$"));
    const int row = m_nodes->indexOf(id);
    if (row < 0 || id == newId || !valid.match(newId).hasMatch() || m_nodes->indexOf(newId) >= 0)
        return false;
    if (QStringList{QStringLiteral("var"), QStringLiteral("loop"), QStringLiteral("now"), QStringLiteral("run"),
                    QStringLiteral("trigger")}.contains(newId))
        return false;
    snapshot();
    m_nodes->at(row).id = newId;
    // references in templates follow the new name
    const QRegularExpression ref(QStringLiteral("\\{\\{\\s*%1([.\\s}])").arg(QRegularExpression::escape(id)));
    for (int i = 0; i < m_nodes->count(); ++i) {
        auto &n = m_nodes->at(i);
        bool touched = false;
        for (auto it = n.params.begin(); it != n.params.end(); ++it) {
            if (it.value().typeId() == QMetaType::QString) {
                QString s = it.value().toString();
                const QString before = s;
                s.replace(ref, QStringLiteral("{{%1\\1").arg(newId));
                if (s != before) {
                    it.value() = s;
                    touched = true;
                }
            }
        }
        if (touched || i == row)
            m_nodes->touch(i, {FlowNodeModel::IdRole, FlowNodeModel::ParamsRole});
    }
    QList<FlowEdgeModel::Edge> edges = m_edges->items();
    for (auto &e : edges) {
        if (e.from == id)
            e.from = newId;
        if (e.to == id)
            e.to = newId;
    }
    m_edges->setItems(edges);
    setDirty(true);
    Q_EMIT changed();
    return true;
}

void FlowDocument::moveNode(const QString &id, qreal x, qreal y)
{
    const int row = m_nodes->indexOf(id);
    if (row < 0)
        return;
    if (!m_moving) {
        m_moveStart = toJsonObject();
        m_moving = true;
    }
    auto &n = m_nodes->at(row);
    n.x = x;
    n.y = y;
    m_nodes->touch(row, {FlowNodeModel::XRole, FlowNodeModel::YRole});
}

void FlowDocument::endMove()
{
    if (!m_moving)
        return;
    m_moving = false;
    if (m_moveStart == toJsonObject())
        return;
    m_undo.append(m_moveStart);
    if (m_undo.size() > MaxUndo)
        m_undo.removeFirst();
    m_redo.clear();
    setDirty(true);
    Q_EMIT historyChanged();
    Q_EMIT geometryChanged();
}

void FlowDocument::autoLayout()
{
    const auto &items = m_nodes->items();
    if (items.isEmpty())
        return;
    // Longest-path layering from the roots, then order each layer by its parents' order
    QHash<QString, QStringList> preds, succs;
    for (const auto &e : m_edges->items()) {
        preds[e.to] << e.from;
        succs[e.from] << e.to;
    }
    QHash<QString, int> layer;
    QStringList order;
    for (const auto &n : items)
        order << n.id;
    // the trigger first, then the rest in file order
    std::stable_sort(order.begin(), order.end(), [&](const QString &a, const QString &b) {
        return a == triggerId() && b != triggerId();
    });
    bool changedLayer = true;
    for (const QString &id : order)
        layer[id] = 0;
    for (int guard = 0; changedLayer && guard < items.size() + 1; ++guard) {
        changedLayer = false;
        for (const auto &e : m_edges->items()) {
            if (layer.value(e.to) < layer.value(e.from) + 1) {
                layer[e.to] = layer.value(e.from) + 1;
                changedLayer = true;
            }
        }
    }
    int maxLayer = 0;
    for (int l : std::as_const(layer))
        maxLayer = std::max(maxLayer, l);
    QList<QStringList> layers(maxLayer + 1);
    for (const QString &id : order)
        layers[layer.value(id)] << id;
    QHash<QString, qreal> position;
    for (int l = 0; l <= maxLayer; ++l) {
        QStringList &ids = layers[l];
        if (l > 0) {
            std::stable_sort(ids.begin(), ids.end(), [&](const QString &a, const QString &b) {
                auto bary = [&](const QString &id) {
                    const QStringList p = preds.value(id);
                    if (p.isEmpty())
                        return 1e6;
                    qreal sum = 0;
                    for (const QString &x : p)
                        sum += position.value(x);
                    return sum / p.size();
                };
                return bary(a) < bary(b);
            });
        }
        for (int i = 0; i < ids.size(); ++i)
            position[ids.at(i)] = i;
    }
    int tallest = 0;
    for (const auto &ids : layers)
        tallest = std::max(tallest, int(ids.size()));
    snapshot();
    const qreal colWidth = 250, rowHeight = 140, x0 = 60, y0 = 60;
    for (int l = 0; l <= maxLayer; ++l) {
        const QStringList &ids = layers.at(l);
        const qreal offset = (tallest - ids.size()) * rowHeight / 2.0;
        for (int i = 0; i < ids.size(); ++i) {
            const int row = m_nodes->indexOf(ids.at(i));
            auto &n = m_nodes->at(row);
            n.x = x0 + l * colWidth;
            n.y = y0 + offset + i * rowHeight;
            m_nodes->touch(row, {FlowNodeModel::XRole, FlowNodeModel::YRole});
        }
    }
    setDirty(true);
    Q_EMIT changed();
    Q_EMIT geometryChanged();
}

// ------------------------------------------------------------------ queries

QVariantMap FlowDocument::nodeType(const QString &type) const
{
    return m_types.value(type);
}

QVariantMap FlowDocument::node(const QString &id) const
{
    const int row = m_nodes->indexOf(id);
    if (row < 0)
        return {};
    const auto &n = m_nodes->items().at(row);
    return {{QStringLiteral("id"), n.id}, {QStringLiteral("type"), n.type}, {QStringLiteral("label"), n.label},
            {QStringLiteral("x"), n.x}, {QStringLiteral("y"), n.y}, {QStringLiteral("params"), params(id)}};
}

QVariantMap FlowDocument::params(const QString &id) const
{
    const int row = m_nodes->indexOf(id);
    if (row < 0)
        return {};
    const auto &n = m_nodes->items().at(row);
    QVariantMap out = n.params;
    for (const QVariant &p : m_types.value(n.type).value(QStringLiteral("params")).toList()) {
        const QVariantMap pm = p.toMap();
        const QString name = pm.value(QStringLiteral("name")).toString();
        if (!out.contains(name))
            out.insert(name, pm.value(QStringLiteral("default")));
    }
    return out;
}

QStringList FlowDocument::ports(const QString &id) const
{
    const int row = m_nodes->indexOf(id);
    if (row < 0)
        return {};
    const auto &n = m_nodes->items().at(row);
    if (n.type == QLatin1String("logic.switch")) {
        QStringList out;
        const QVariantList cases = params(id).value(QStringLiteral("cases")).toList();
        for (int i = 0; i < cases.size(); ++i)
            out << QStringLiteral("case_%1").arg(i);
        out << QStringLiteral("default");
        return out;
    }
    if (n.type == QLatin1String("logic.ask") && params(id).value(QStringLiteral("mode")).toString() == QLatin1String("input"))
        return {QStringLiteral("yes")};
    const QStringList p = m_types.value(n.type).value(QStringLiteral("ports")).toStringList();
    return p.isEmpty() ? QStringList{QStringLiteral("out")} : p;
}

QString FlowDocument::portLabel(const QString &id, const QString &port) const
{
    const int row = m_nodes->indexOf(id);
    if (row < 0)
        return {};
    const auto &n = m_nodes->items().at(row);
    if (port.startsWith(QLatin1String("case_"))) {
        const QVariantList cases = params(id).value(QStringLiteral("cases")).toList();
        const int i = port.mid(5).toInt();
        return i < cases.size() ? cases.at(i).toString() : port;
    }
    if (n.type == QLatin1String("logic.ask") && port == QLatin1String("yes") && ports(id).size() == 1)
        return {};
    return m_types.value(n.type).value(QStringLiteral("port_labels")).toMap().value(port).toString();
}

bool FlowDocument::hasInput(const QString &id) const
{
    const int row = m_nodes->indexOf(id);
    return row >= 0 && !m_nodes->items().at(row).type.startsWith(TriggerPrefix);
}

QStringList FlowDocument::outputs(const QString &id) const
{
    const int row = m_nodes->indexOf(id);
    if (row < 0)
        return {};
    const auto &n = m_nodes->items().at(row);
    QStringList out = m_types.value(n.type).value(QStringLiteral("outputs")).toStringList();
    if (n.type == QLatin1String("ai.extract"))
        for (const QVariant &f : params(id).value(QStringLiteral("fields")).toList())
            if (!f.toString().trimmed().isEmpty())
                out << f.toString().trimmed();
    return out;
}

QVariantList FlowDocument::variablesFor(const QString &id) const
{
    // Every node that can run before this one
    QSet<QString> ancestors;
    QList<QString> todo{id};
    while (!todo.isEmpty()) {
        const QString x = todo.takeLast();
        for (const auto &e : m_edges->items()) {
            if (e.to == x && !ancestors.contains(e.from)) {
                ancestors.insert(e.from);
                todo << e.from;
            }
        }
    }
    // Inside a loop's "Para cada" branch?
    bool inLoop = false;
    for (const auto &n : m_nodes->items()) {
        if (n.type != QLatin1String("logic.loop") || !ancestors.contains(n.id))
            continue;
        QList<QString> walk;
        for (const auto &e : m_edges->items())
            if (e.from == n.id && e.port == QLatin1String("each"))
                walk << e.to;
        QSet<QString> seen;
        while (!walk.isEmpty() && !inLoop) {
            const QString x = walk.takeLast();
            if (x == id)
                inLoop = true;
            if (seen.contains(x))
                continue;
            seen.insert(x);
            for (const auto &e : m_edges->items())
                if (e.from == x)
                    walk << e.to;
        }
    }
    QVariantList out;
    const QString trig = triggerId();
    for (const auto &n : m_nodes->items()) {
        if (!ancestors.contains(n.id))
            continue;
        const QString label = n.label.isEmpty() ? m_types.value(n.type).value(QStringLiteral("label")).toString() : n.label;
        const bool isTrigger = n.id == trig;
        for (const QString &o : outputs(n.id)) {
            out << QVariantMap{{QStringLiteral("text"), QStringLiteral("{{%1.%2}}").arg(isTrigger ? QStringLiteral("trigger") : n.id, o)},
                               {QStringLiteral("label"), QStringLiteral("%1 › %2").arg(label, o)},
                               {QStringLiteral("node"), n.id}};
        }
        if (n.type == QLatin1String("logic.set")) {
            const QString name = n.params.value(QStringLiteral("name")).toString();
            if (!name.isEmpty())
                out << QVariantMap{{QStringLiteral("text"), QStringLiteral("{{var.%1}}").arg(name)},
                                   {QStringLiteral("label"), tr("Variable › %1").arg(name)},
                                   {QStringLiteral("node"), n.id}};
        }
    }
    if (inLoop) {
        out << QVariantMap{{QStringLiteral("text"), QStringLiteral("{{loop.item}}")},
                           {QStringLiteral("label"), tr("Loop › current item")}, {QStringLiteral("node"), QString()}};
        out << QVariantMap{{QStringLiteral("text"), QStringLiteral("{{loop.number}}")},
                           {QStringLiteral("label"), tr("Loop › item number")}, {QStringLiteral("node"), QString()}};
    }
    out << QVariantMap{{QStringLiteral("text"), QStringLiteral("{{now.date}}")},
                       {QStringLiteral("label"), tr("Today's date")}, {QStringLiteral("node"), QString()}};
    out << QVariantMap{{QStringLiteral("text"), QStringLiteral("{{now.time}}")},
                       {QStringLiteral("label"), tr("Current time")}, {QStringLiteral("node"), QString()}};
    return out;
}

static QString scheduleText(const QVariantMap &s)
{
    const QString kind = s.value(QStringLiteral("kind")).toString();
    const QString time = s.value(QStringLiteral("time")).toString();
    if (kind == QLatin1String("daily"))
        return FlowDocument::tr("Every day at %1").arg(time);
    if (kind == QLatin1String("weekdays")) {
        const QVariantList days = s.value(QStringLiteral("days")).toList();
        if (days.size() == 5 && days.first().toInt() == 0 && days.last().toInt() == 4)
            return FlowDocument::tr("Weekdays at %1").arg(time);
        const QStringList names = {FlowDocument::tr("Mon"), FlowDocument::tr("Tue"), FlowDocument::tr("Wed"),
                                   FlowDocument::tr("Thu"), FlowDocument::tr("Fri"), FlowDocument::tr("Sat"),
                                   FlowDocument::tr("Sun")};
        QStringList chosen;
        for (const QVariant &d : days)
            if (d.toInt() >= 0 && d.toInt() < 7)
                chosen << names.at(d.toInt());
        return FlowDocument::tr("%1 at %2").arg(chosen.join(QStringLiteral(", ")), time);
    }
    if (kind == QLatin1String("interval"))
        return FlowDocument::tr("Every %1 min").arg(s.value(QStringLiteral("minutes")).toInt());
    if (kind == QLatin1String("monthly"))
        return FlowDocument::tr("Day %1 of each month at %2").arg(s.value(QStringLiteral("day")).toInt()).arg(time);
    if (kind == QLatin1String("once"))
        return FlowDocument::tr("Once on %1").arg(s.value(QStringLiteral("datetime")).toString().replace(QLatin1Char('T'), QLatin1Char(' ')));
    if (kind == QLatin1String("cron"))
        return QStringLiteral("cron %1").arg(s.value(QStringLiteral("cron")).toString());
    return {};
}

QString FlowDocument::summary(const QString &id) const
{
    const int row = m_nodes->indexOf(id);
    if (row < 0)
        return {};
    const auto &n = m_nodes->items().at(row);
    const QVariantMap p = params(id);
    if (n.type == QLatin1String("trigger.schedule"))
        return scheduleText(p.value(QStringLiteral("schedule")).toMap());
    if (n.type == QLatin1String("trigger.voice")) {
        const QVariantList phrases = p.value(QStringLiteral("phrases")).toList();
        return phrases.isEmpty() ? QString() : QStringLiteral("“%1”").arg(phrases.first().toString());
    }
    if (n.type == QLatin1String("logic.if"))
        return QStringLiteral("%1 %2 %3").arg(p.value(QStringLiteral("value")).toString(),
                                               p.value(QStringLiteral("op")).toString(),
                                               p.value(QStringLiteral("compare")).toString()).simplified();
    // the first filled text field
    for (const QVariant &pv : m_types.value(n.type).value(QStringLiteral("params")).toList()) {
        const QVariantMap pm = pv.toMap();
        const QString kind = pm.value(QStringLiteral("kind")).toString();
        if (kind == QLatin1String("bool") || kind == QLatin1String("select") || kind == QLatin1String("account"))
            continue;
        const QVariant v = p.value(pm.value(QStringLiteral("name")).toString());
        QString text = v.typeId() == QMetaType::QVariantList ? v.toStringList().join(QStringLiteral(", ")) : v.toString();
        text = text.simplified();
        if (!text.isEmpty())
            return text.size() > 60 ? text.left(57) + QStringLiteral("…") : text;
    }
    return {};
}

QString FlowDocument::category(const QString &id) const
{
    const int row = m_nodes->indexOf(id);
    if (row < 0)
        return {};
    return m_types.value(m_nodes->items().at(row).type).value(QStringLiteral("category")).toString();
}

QVariantList FlowDocument::palette(const QString &filter) const
{
    // Hidden types (kept only for old workflows) are left out; "Ações" is
    // grouped by app (Mail, Relógio, Notas… with the apps' Lingmo Intents), so
    // every row gets a "section": the category, or "actions|<app>"
    const QString f = filter.trimmed().toLower();
    QStringList order;
    for (const QVariant &c : m_catalogue.value(QStringLiteral("categories")).toList())
        order << c.toMap().value(QStringLiteral("id")).toString();
    QList<QVariantMap> rows;
    for (const QVariant &v : m_catalogue.value(QStringLiteral("types")).toList()) {
        QVariantMap t = v.toMap();
        if (t.value(QStringLiteral("hidden")).toBool())
            continue;
        if (!f.isEmpty() && !t.value(QStringLiteral("label")).toString().toLower().contains(f)
            && !t.value(QStringLiteral("description")).toString().toLower().contains(f)
            && !t.value(QStringLiteral("group")).toString().toLower().contains(f))
            continue;
        const QString category = t.value(QStringLiteral("category")).toString();
        const QString group = t.value(QStringLiteral("group")).toString();
        t.insert(QStringLiteral("section"), category == QLatin1String("actions") && !group.isEmpty()
                                                ? category + QLatin1Char('|') + group : category);
        rows << t;
    }
    std::stable_sort(rows.begin(), rows.end(), [&order](const QVariantMap &a, const QVariantMap &b) {
        const int ca = order.indexOf(a.value(QStringLiteral("category")).toString());
        const int cb = order.indexOf(b.value(QStringLiteral("category")).toString());
        if (ca != cb)
            return ca < cb;
        if (a.value(QStringLiteral("category")).toString() != QLatin1String("actions"))
            return false;
        return a.value(QStringLiteral("group")).toString().localeAwareCompare(b.value(QStringLiteral("group")).toString()) < 0;
    });
    QVariantList out;
    for (const QVariantMap &r : rows)
        out << r;
    return out;
}

QStringList FlowDocument::nodeIds() const
{
    QStringList out;
    for (const auto &n : m_nodes->items())
        out << n.id;
    return out;
}

QVariantMap FlowDocument::issue(const QString &id) const
{
    const int row = m_nodes->indexOf(id);
    if (row < 0)
        return {};
    const auto &n = m_nodes->items().at(row);
    return {{QStringLiteral("message"), n.issue}, {QStringLiteral("level"), n.issueLevel}};
}

// ------------------------------------------------------------------ run state

void FlowDocument::setNodeStatus(const QString &id, const QString &status, const QString &output, const QString &error)
{
    const int row = m_nodes->indexOf(id);
    if (row < 0)
        return;
    auto &n = m_nodes->at(row);
    n.status = status;
    if (!output.isEmpty() || status == QLatin1String("running"))
        n.output = output;
    n.error = error;
    m_nodes->touch(row, {FlowNodeModel::StatusRole, FlowNodeModel::OutputRole, FlowNodeModel::ErrorRole});
    if (status == QLatin1String("running"))
        m_edges->setActiveInto(id);
}

void FlowDocument::clearRunState()
{
    for (int i = 0; i < m_nodes->count(); ++i) {
        auto &n = m_nodes->at(i);
        if (n.status.isEmpty() && n.output.isEmpty() && n.error.isEmpty())
            continue;
        n.status.clear();
        n.output.clear();
        n.error.clear();
        m_nodes->touch(i, {FlowNodeModel::StatusRole, FlowNodeModel::OutputRole, FlowNodeModel::ErrorRole});
    }
    m_edges->clearActive();
}

void FlowDocument::setIssues(const QVariantList &issues)
{
    QHash<QString, QPair<QString, QString>> byNode;
    for (const QVariant &v : issues) {
        const QVariantMap m = v.toMap();
        const QString node = m.value(QStringLiteral("node")).toString();
        const QString level = m.value(QStringLiteral("level")).toString();
        if (node.isEmpty())
            continue;
        // errors win over warnings
        if (!byNode.contains(node) || (level == QLatin1String("error") && byNode[node].second != level))
            byNode[node] = {m.value(QStringLiteral("message")).toString(), level};
    }
    for (int i = 0; i < m_nodes->count(); ++i) {
        auto &n = m_nodes->at(i);
        const auto issue = byNode.value(n.id);
        if (n.issue == issue.first && n.issueLevel == issue.second)
            continue;
        n.issue = issue.first;
        n.issueLevel = issue.second;
        m_nodes->touch(i, {FlowNodeModel::IssueRole, FlowNodeModel::IssueLevelRole});
    }
}
