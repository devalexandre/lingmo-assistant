/*
 * Copyright (C) 2026 LingmoOS Team.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * any later version.
 */

#include "assistant.h"

#include <QClipboard>
#include <QDateTime>
#include <QGuiApplication>
#include <QJsonObject>
#include <QLocale>
#include <QProcess>
#include <QUuid>

// ------------------------------------------------------------------ ConversationModel

int ConversationModel::rowCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : m_items.size();
}

QVariant ConversationModel::data(const QModelIndex &index, int role) const
{
    if (!index.isValid() || index.row() >= m_items.size())
        return {};
    const Item &i = m_items.at(index.row());
    switch (role) {
    case IdRole: return i.id;
    case TitleRole: return i.title;
    case UpdatedRole: return i.updated;
    }
    return {};
}

QHash<int, QByteArray> ConversationModel::roleNames() const
{
    return {{IdRole, "conversationId"}, {TitleRole, "title"}, {UpdatedRole, "updated"}};
}

void ConversationModel::setItems(const QList<Item> &items)
{
    beginResetModel();
    m_items = items;
    endResetModel();
    Q_EMIT countChanged();
}

void ConversationModel::upsert(const Item &item)
{
    const int row = indexOf(item.id);
    if (row >= 0)
        return;
    beginInsertRows({}, 0, 0);
    m_items.prepend(item);
    endInsertRows();
    Q_EMIT countChanged();
}

int ConversationModel::indexOf(const QString &id) const
{
    for (int i = 0; i < m_items.size(); ++i)
        if (m_items.at(i).id == id)
            return i;
    return -1;
}

// ------------------------------------------------------------------ Assistant

static QString newId()
{
    return QUuid::createUuid().toString(QUuid::WithoutBraces);
}

static bool validId(const QString &id)
{
    if (id.isEmpty() || id.size() > 100)
        return false;
    for (const QChar c : id)
        if (!(c.isLetterOrNumber() && c.unicode() < 128) && c != QLatin1Char('-') && c != QLatin1Char('_'))
            return false;
    return true;
}

Assistant::Assistant(QObject *parent)
    : QObject(parent)
{
    connect(&m_engine, &EngineClient::event, this, &Assistant::onEvent);
    connect(&m_engine, &EngineClient::failed, this, [this](const QString &message) {
        setBusy(false);
        setError(message);
    });
    m_conversationId = newId();
    if (EngineClient::isInstalled())
        m_engine.send(QJsonObject{{QStringLiteral("type"), QStringLiteral("list_conversations")}});
    connect(&m_flow, &FlowDocument::changed, this, [this] {
        if (m_flow.loaded() && m_flow.dirty())
            validateFlow();
    });
}

QString Assistant::title() const
{
    const int row = m_conversations.indexOf(m_conversationId);
    if (row < 0 || m_messages.count() == 0)
        return {};
    return m_conversations.index(row).data(ConversationModel::TitleRole).toString();
}

void Assistant::setBusy(bool busy)
{
    if (busy == m_busy)
        return;
    m_busy = busy;
    Q_EMIT busyChanged();
}

void Assistant::setError(const QString &error)
{
    if (error == m_error)
        return;
    m_error = error;
    Q_EMIT errorChanged();
}

void Assistant::newConversation()
{
    if (m_busy)
        stop();
    m_conversationId = newId();
    m_fresh = true;
    m_messages.clear();
    setError({});
    Q_EMIT conversationChanged();
}

void Assistant::openConversation(const QString &id)
{
    if (!validId(id))
        return;
    if (m_busy && id != m_conversationId)
        stop();
    m_conversationId = id;
    m_fresh = false;
    m_messages.clear();
    setError({});
    Q_EMIT conversationChanged();
    m_engine.send(QJsonObject{{QStringLiteral("type"), QStringLiteral("history")},
                              {QStringLiteral("conversation_id"), id}});
}

void Assistant::send(const QString &text)
{
    const QString question = text.trimmed();
    if (question.isEmpty() || m_busy)
        return;
    setError({});
    ChatModel::Item item;
    item.kind = QStringLiteral("user");
    item.text = question;
    m_messages.append(item);
    if (m_fresh) {
        m_fresh = false;
        QString title = question.simplified();
        if (title.size() > 60)
            title = title.left(57).trimmed() + QStringLiteral("…");
        m_conversations.upsert({m_conversationId, title, QDateTime::currentSecsSinceEpoch()});
        Q_EMIT conversationChanged();
    }
    setBusy(true);
    QJsonObject request{{QStringLiteral("type"), QStringLiteral("chat")},
                        {QStringLiteral("conversation_id"), m_conversationId},
                        {QStringLiteral("message"), question}};
    if (!m_chatAgent.isEmpty())
        request.insert(QStringLiteral("agent"), m_chatAgent);
    m_engine.send(request);
}

void Assistant::stop()
{
    m_engine.send(QJsonObject{{QStringLiteral("type"), QStringLiteral("stop")}});
}

void Assistant::confirm(const QString &requestId, bool allow)
{
    m_messages.setConfirmState(requestId, allow ? QStringLiteral("allowed") : QStringLiteral("denied"));
    m_engine.send(QJsonObject{{QStringLiteral("type"), QStringLiteral("confirm")},
                              {QStringLiteral("request_id"), requestId},
                              {QStringLiteral("allow"), allow}});
}

void Assistant::deleteConversation(const QString &id)
{
    if (!validId(id))
        return;
    m_engine.send(QJsonObject{{QStringLiteral("type"), QStringLiteral("delete_conversation")},
                              {QStringLiteral("conversation_id"), id}});
}

void Assistant::refresh()
{
    if (!EngineClient::isInstalled())
        return;
    // Settings may have changed the model or the permissions
    m_engine.send(QJsonObject{{QStringLiteral("type"), QStringLiteral("reload_config")}});
    m_engine.send(QJsonObject{{QStringLiteral("type"), QStringLiteral("list_conversations")}});
}

void Assistant::openSettings() const
{
    QProcess::startDetached(QStringLiteral("lingmo-settings"), {QStringLiteral("-m"), QStringLiteral("ai")});
}

void Assistant::copy(const QString &text) const
{
    QGuiApplication::clipboard()->setText(text);
}

void Assistant::open(const QString &conversationId)
{
    // Reloads even the current one: a handed-over confirmation shows up
    if (!conversationId.isEmpty())
        openConversation(conversationId);
    Q_EMIT raiseRequested();
}

void Assistant::ask(const QString &text)
{
    newConversation();
    Q_EMIT raiseRequested();
    send(text);
}

QString Assistant::statsText(const QVariantMap &stats) const
{
    const QString seconds = QLocale().toString(stats.value(QStringLiteral("seconds")).toDouble(), 'f', 1);
    const double speed = stats.value(QStringLiteral("tokens_per_s")).toDouble();
    if (speed > 0)
        return tr("Answered in %1 s · %2 tokens/s").arg(seconds).arg(qRound(speed));
    return tr("Answered in %1 s").arg(seconds);
}

QString Assistant::toolLabel(const QString &function, const QString &args, bool running) const
{
    if (function == QLatin1String("run_command"))
        return running ? tr("Running %1…").arg(args) : tr("Ran: %1").arg(args);
    if (function == QLatin1String("system_info"))
        return running ? tr("Reading system information…") : tr("Read system information");
    if (function == QLatin1String("list_folder"))
        return running ? tr("Listing %1…").arg(args.isEmpty() ? tr("folders") : args)
                       : tr("Listed %1").arg(args.isEmpty() ? tr("the allowed folders") : args);
    if (function == QLatin1String("read_document"))
        return running ? tr("Reading %1…").arg(args) : tr("Read %1").arg(args);
    if (function == QLatin1String("summarize_documents"))
        return running ? tr("Summarizing %1…").arg(args) : tr("Summarized %1").arg(args);
    if (function == QLatin1String("search_files"))
        return running ? tr("Searching files for “%1”…").arg(args) : tr("Searched files for “%1”").arg(args);
    if (function == QLatin1String("list_notes"))
        return running ? tr("Looking at your notes…") : tr("Looked at your notes");
    if (function == QLatin1String("read_note"))
        return running ? tr("Reading a note…") : tr("Read a note");
    if (function == QLatin1String("calendar_agenda"))
        return running ? tr("Looking at the calendar…") : tr("Looked at the calendar");
    if (function == QLatin1String("web_search"))
        return running ? tr("Searching the web for “%1”…").arg(args) : tr("Searched the web for “%1”").arg(args);
    if (function == QLatin1String("read_web_page"))
        return running ? tr("Reading %1…").arg(args) : tr("Read %1").arg(args);
    if (function == QLatin1String("create_note"))
        return running ? tr("Creating note “%1”…").arg(args) : tr("Note “%1”").arg(args);
    if (function == QLatin1String("append_to_note"))
        return running ? tr("Adding to a note…") : tr("Added to a note");
    if (function == QLatin1String("create_event"))
        return running ? tr("Creating event “%1”…").arg(args) : tr("Event “%1”").arg(args);
    if (function == QLatin1String("create_reminder"))
        return running ? tr("Creating reminder “%1”…").arg(args) : tr("Reminder “%1”").arg(args);
    if (function == QLatin1String("create_task"))
        return running ? tr("Creating task “%1”…").arg(args) : tr("Task “%1”").arg(args);
    if (function == QLatin1String("write_file"))
        return running ? tr("Writing %1…").arg(args) : tr("File %1").arg(args);
    return running ? tr("Working…") : function;
}

void Assistant::onEvent(const QVariantMap &event)
{
    const QString type = event.value(QStringLiteral("type")).toString();
    const QString conv = event.value(QStringLiteral("conversation_id")).toString();
    const bool current = conv.isEmpty() || conv == m_conversationId;

    if (onExtraEvent(type, event))
        return;

    if (type == QLatin1String("ready") || type == QLatin1String("config")) {
        m_model = event.value(QStringLiteral("model")).toString();
        const QVariant supported = event.value(QStringLiteral("tools_supported"));
        m_toolsSupported = !supported.isValid() || supported.isNull() || supported.toBool();
        m_write = event.value(QStringLiteral("write")).toBool();
        Q_EMIT configChanged();
        return;
    }
    if (type == QLatin1String("conversations")) {
        QList<ConversationModel::Item> items;
        for (const QVariant &v : event.value(QStringLiteral("items")).toList()) {
            const QVariantMap m = v.toMap();
            items.append({m.value(QStringLiteral("id")).toString(), m.value(QStringLiteral("title")).toString(),
                          m.value(QStringLiteral("updated")).toLongLong()});
        }
        // Keep a conversation that was just started but isn't stored yet
        if (!m_fresh && m_messages.count() > 0) {
            bool listed = false;
            for (const auto &i : items)
                listed = listed || i.id == m_conversationId;
            if (!listed && m_conversations.indexOf(m_conversationId) >= 0) {
                const QModelIndex idx = m_conversations.index(m_conversations.indexOf(m_conversationId));
                items.prepend({m_conversationId, idx.data(ConversationModel::TitleRole).toString(),
                               QDateTime::currentSecsSinceEpoch()});
            }
        }
        m_conversations.setItems(items);
        Q_EMIT conversationChanged();
        return;
    }
    if (type == QLatin1String("deleted")) {
        if (conv == m_conversationId)
            newConversation();
        m_engine.send(QJsonObject{{QStringLiteral("type"), QStringLiteral("list_conversations")}});
        return;
    }
    if (type == QLatin1String("history")) {
        if (current) {
            const QString agentId = event.value(QStringLiteral("agent")).toString();
            if (agentId != m_chatAgent) {
                m_chatAgent = agentId;
                Q_EMIT chatAgentChanged();
            }
            loadHistory(event);
            Q_EMIT conversationChanged();
        }
        return;
    }
    if (!current) {
        if (type == QLatin1String("done"))
            m_engine.send(QJsonObject{{QStringLiteral("type"), QStringLiteral("list_conversations")}});
        return;
    }

    if (type == QLatin1String("started")) {
        m_chatAnswer.clear();
        setBusy(true);
    } else if (type == QLatin1String("token")) {
        m_messages.appendToken(event.value(QStringLiteral("text")).toString());
        m_chatAnswer += event.value(QStringLiteral("text")).toString();
        if (m_voiceVisible && conv == m_voiceConversation) {
            m_voiceAnswer += event.value(QStringLiteral("text")).toString();
            if (m_voiceState != QLatin1String("answering"))
                m_voiceState = QStringLiteral("answering");
            Q_EMIT voiceChanged();
        }
    } else if (type == QLatin1String("thinking")) {
        m_messages.setThinking();
    } else if (type == QLatin1String("tool_start")) {
        m_messages.toolStarted(event.value(QStringLiteral("function")).toString(),
                               event.value(QStringLiteral("tool")).toString(),
                               event.value(QStringLiteral("args_summary")).toString());
    } else if (type == QLatin1String("tool_end")) {
        m_messages.toolEnded(event.value(QStringLiteral("function")).toString(),
                             event.value(QStringLiteral("ok")).toBool(),
                             event.value(QStringLiteral("summary")).toString(),
                             event.value(QStringLiteral("output")).toString());
    } else if (type == QLatin1String("confirmation_required")) {
        if (m_voiceVisible && conv == m_voiceConversation)
            setVoiceState(QStringLiteral("answering"), tr("The assistant asks for permission in the window."));
        ChatModel::Item item;
        item.kind = QStringLiteral("confirm");
        item.requestId = event.value(QStringLiteral("request_id")).toString();
        item.function = event.value(QStringLiteral("function")).toString();
        item.tool = event.value(QStringLiteral("tool")).toString();
        item.title = event.value(QStringLiteral("title")).toString();
        item.details = event.value(QStringLiteral("details")).toString();
        item.state = QStringLiteral("pending");
        m_messages.append(item);
        Q_EMIT raiseRequested();
    } else if (type == QLatin1String("confirmation_resolved")) {
        m_messages.setConfirmState(event.value(QStringLiteral("request_id")).toString(),
                                   event.value(QStringLiteral("allow")).toBool() ? QStringLiteral("allowed")
                                                                                 : QStringLiteral("denied"));
    } else if (type == QLatin1String("notice")) {
        ChatModel::Item item;
        item.kind = QStringLiteral("notice");
        item.text = event.value(QStringLiteral("message")).toString();
        m_messages.append(item);
    } else if (type == QLatin1String("error")) {
        m_messages.finishAnswer({});
        setError(event.value(QStringLiteral("message")).toString());
        setBusy(false);
        if (m_voiceVisible && conv == m_voiceConversation)
            setVoiceState(QStringLiteral("error"), event.value(QStringLiteral("message")).toString());
    } else if (type == QLatin1String("done")) {
        const QVariantMap stats = event.value(QStringLiteral("stats")).toMap();
        m_messages.finishAnswer(statsText(stats));
        setBusy(false);
        if (conv == m_voiceConversation && !m_voiceConversation.isEmpty()) {
            m_voiceConversation.clear();
            if (voiceReplies() && !m_voiceAnswer.trimmed().isEmpty())
                speak(m_voiceAnswer);
            setVoiceState(QStringLiteral("idle"));
        } else if (voiceReplies() && !m_chatAnswer.trimmed().isEmpty()) {
            // "Responder em voz alta" also reads answers to typed questions
            speak(m_chatAnswer);
        }
        m_chatAnswer.clear();
        m_engine.send(QJsonObject{{QStringLiteral("type"), QStringLiteral("list_conversations")}});
    }
}

void Assistant::loadHistory(const QVariantMap &event)
{
    m_messages.clear();
    for (const QVariant &v : event.value(QStringLiteral("messages")).toList()) {
        const QVariantMap m = v.toMap();
        const QString role = m.value(QStringLiteral("role")).toString();
        if (role == QLatin1String("user")) {
            ChatModel::Item item;
            item.kind = QStringLiteral("user");
            item.text = m.value(QStringLiteral("text")).toString();
            m_messages.append(item);
            continue;
        }
        for (const QVariant &t : m.value(QStringLiteral("tools")).toList()) {
            const QVariantMap tm = t.toMap();
            ChatModel::Item item;
            item.kind = QStringLiteral("tool");
            item.function = tm.value(QStringLiteral("function")).toString();
            item.tool = tm.value(QStringLiteral("tool")).toString();
            item.args = tm.value(QStringLiteral("args_summary")).toString();
            item.ok = tm.value(QStringLiteral("ok")).toBool();
            item.output = tm.value(QStringLiteral("output")).toString();
            if (item.output.isEmpty())
                item.output = tm.value(QStringLiteral("summary")).toString();
            m_messages.append(item);
        }
        const QString text = m.value(QStringLiteral("text")).toString();
        if (!text.trimmed().isEmpty()) {
            ChatModel::Item item;
            item.kind = QStringLiteral("assistant");
            item.text = text;
            item.stats = QStringLiteral(" ");   // closed bubble; no timing for old answers
            m_messages.append(item);
        }
    }
    for (const QVariant &v : event.value(QStringLiteral("pending")).toList()) {
        const QVariantMap p = v.toMap();
        ChatModel::Item item;
        item.kind = QStringLiteral("confirm");
        item.requestId = p.value(QStringLiteral("request_id")).toString();
        item.function = p.value(QStringLiteral("function")).toString();
        item.tool = p.value(QStringLiteral("tool")).toString();
        item.title = p.value(QStringLiteral("title")).toString();
        item.details = p.value(QStringLiteral("details")).toString();
        item.state = p.value(QStringLiteral("invalid")).toBool() ? QStringLiteral("expired") : QStringLiteral("pending");
        m_messages.append(item);
    }
}
