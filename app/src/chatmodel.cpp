/*
 * Copyright (C) 2026 LingmoOS Team.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * any later version.
 */

#include "chatmodel.h"

ChatModel::ChatModel(QObject *parent)
    : QAbstractListModel(parent)
{
}

int ChatModel::rowCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : m_items.size();
}

QVariant ChatModel::data(const QModelIndex &index, int role) const
{
    if (!index.isValid() || index.row() >= m_items.size())
        return {};
    const Item &i = m_items.at(index.row());
    switch (role) {
    case KindRole: return i.kind;
    case TextRole: return i.text;
    case ThinkingRole: return i.thinking;
    case StatsRole: return i.stats;
    case FunctionRole: return i.function;
    case ToolRole: return i.tool;
    case ArgsRole: return i.args;
    case OkRole: return i.ok;
    case RunningRole: return i.running;
    case OutputRole: return i.output;
    case RequestIdRole: return i.requestId;
    case TitleRole: return i.title;
    case DetailsRole: return i.details;
    case StateRole: return i.state;
    }
    return {};
}

QHash<int, QByteArray> ChatModel::roleNames() const
{
    return {{KindRole, "kind"}, {TextRole, "text"}, {ThinkingRole, "thinking"}, {StatsRole, "stats"},
            {FunctionRole, "functionName"}, {ToolRole, "tool"}, {ArgsRole, "args"}, {OkRole, "ok"},
            {RunningRole, "running"}, {OutputRole, "output"}, {RequestIdRole, "requestId"},
            {TitleRole, "title"}, {DetailsRole, "details"}, {StateRole, "confirmState"}};
}

void ChatModel::clear()
{
    beginResetModel();
    m_items.clear();
    endResetModel();
    Q_EMIT countChanged();
}

void ChatModel::append(const Item &item)
{
    beginInsertRows({}, m_items.size(), m_items.size());
    m_items << item;
    endInsertRows();
    Q_EMIT countChanged();
}

void ChatModel::changed(int row, const QList<int> &roles)
{
    const QModelIndex i = index(row);
    Q_EMIT dataChanged(i, i, roles);
}

int ChatModel::openAnswer()
{
    // Text after a tool card goes into a new bubble below it, in order
    if (!m_items.isEmpty() && m_items.last().kind == QLatin1String("assistant") && m_items.last().stats.isEmpty())
        return m_items.size() - 1;
    Item answer;
    answer.kind = QStringLiteral("assistant");
    append(answer);
    return m_items.size() - 1;
}

void ChatModel::appendToken(const QString &text)
{
    if (text.isEmpty())
        return;
    // Don't open a bubble for the whitespace models send between tool calls
    if (text.trimmed().isEmpty()
        && (m_items.isEmpty() || m_items.last().kind != QLatin1String("assistant")))
        return;
    const int row = openAnswer();
    Item &a = m_items[row];
    a.text += text;
    QList<int> roles{TextRole};
    if (a.thinking) {
        a.thinking = false;
        roles << ThinkingRole;
    }
    changed(row, roles);
}

void ChatModel::setThinking()
{
    const int row = openAnswer();
    if (m_items[row].text.isEmpty() && !m_items[row].thinking) {
        m_items[row].thinking = true;
        changed(row, {ThinkingRole});
    }
}

void ChatModel::finishAnswer(const QString &stats)
{
    // Drop an empty bubble (e.g. stopped before any text)
    if (!m_items.isEmpty() && m_items.last().kind == QLatin1String("assistant")
        && m_items.last().text.trimmed().isEmpty()) {
        beginRemoveRows({}, m_items.size() - 1, m_items.size() - 1);
        m_items.removeLast();
        endRemoveRows();
        Q_EMIT countChanged();
    }
    for (int row = m_items.size() - 1; row >= 0; --row) {
        Item &i = m_items[row];
        if (i.kind == QLatin1String("user"))
            break;
        if (i.kind == QLatin1String("tool") && i.running) {
            i.running = false;
            changed(row, {RunningRole});
        }
    }
    for (int row = m_items.size() - 1; row >= 0; --row) {
        if (m_items.at(row).kind == QLatin1String("user"))
            break;
        if (m_items.at(row).kind == QLatin1String("assistant")) {
            m_items[row].stats = stats;
            changed(row, {StatsRole});
            return;
        }
    }
}

void ChatModel::toolStarted(const QString &function, const QString &tool, const QString &args)
{
    // A confirmed write reports its start after the confirmation card: reuse no card
    Item i;
    i.kind = QStringLiteral("tool");
    i.function = function;
    i.tool = tool;
    i.args = args;
    i.running = true;
    append(i);
}

void ChatModel::toolEnded(const QString &function, bool ok, const QString &summary, const QString &output)
{
    for (int row = m_items.size() - 1; row >= 0; --row) {
        Item &i = m_items[row];
        if (i.kind == QLatin1String("tool") && i.function == function && i.running) {
            i.running = false;
            i.ok = ok;
            i.output = output.isEmpty() && !ok ? summary : output;
            changed(row, {RunningRole, OkRole, OutputRole});
            return;
        }
    }
    // Refused before running (invalid write): a finished card
    Item i;
    i.kind = QStringLiteral("tool");
    i.function = function;
    i.ok = ok;
    i.output = output.isEmpty() ? summary : output;
    append(i);
}

void ChatModel::setConfirmState(const QString &requestId, const QString &state)
{
    for (int row = m_items.size() - 1; row >= 0; --row) {
        if (m_items.at(row).kind == QLatin1String("confirm") && m_items.at(row).requestId == requestId) {
            m_items[row].state = state;
            changed(row, {StateRole});
            return;
        }
    }
}

bool ChatModel::hasPendingConfirmation() const
{
    for (const Item &i : m_items)
        if (i.kind == QLatin1String("confirm") && i.state == QLatin1String("pending"))
            return true;
    return false;
}

QString ChatModel::text(int row) const
{
    return row >= 0 && row < m_items.size() ? m_items.at(row).text : QString();
}
