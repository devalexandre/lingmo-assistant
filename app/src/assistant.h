/*
 * Copyright (C) 2026 LingmoOS Team.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * any later version.
 */

#pragma once

#include <QAbstractListModel>
#include <QObject>
#include <QVariantMap>

#include "chatmodel.h"
#include "engineclient.h"

// Conversation history shown in the sidebar
class ConversationModel : public QAbstractListModel
{
    Q_OBJECT
    Q_PROPERTY(int count READ count NOTIFY countChanged)

public:
    enum Roles { IdRole = Qt::UserRole + 1, TitleRole, UpdatedRole };
    struct Item {
        QString id;
        QString title;
        qint64 updated = 0;
    };

    using QAbstractListModel::QAbstractListModel;
    int rowCount(const QModelIndex &parent = {}) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;
    int count() const { return m_items.size(); }
    void setItems(const QList<Item> &items);
    void upsert(const Item &item);   // a new conversation shows up before the engine lists it
    Q_INVOKABLE int indexOf(const QString &id) const;

Q_SIGNALS:
    void countChanged();

private:
    QList<Item> m_items;
};

// The app's controller, exposed to QML as "assistant" and on D-Bus as
// com.lingmo.Assistant /Assistant (open(conversationId), ask(text))
class Assistant : public QObject
{
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "com.lingmo.Assistant")
    Q_PROPERTY(ChatModel *messages READ messages CONSTANT)
    Q_PROPERTY(ConversationModel *conversations READ conversations CONSTANT)
    Q_PROPERTY(QString conversationId READ conversationId NOTIFY conversationChanged)
    Q_PROPERTY(QString title READ title NOTIFY conversationChanged)
    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(QString model READ model NOTIFY configChanged)
    Q_PROPERTY(bool toolsSupported READ toolsSupported NOTIFY configChanged)
    Q_PROPERTY(bool writeAllowed READ writeAllowed NOTIFY configChanged)
    Q_PROPERTY(QString error READ error NOTIFY errorChanged)
    Q_PROPERTY(bool engineInstalled READ engineInstalled CONSTANT)

public:
    explicit Assistant(QObject *parent = nullptr);

    ChatModel *messages() { return &m_messages; }
    ConversationModel *conversations() { return &m_conversations; }
    QString conversationId() const { return m_conversationId; }
    QString title() const;
    bool busy() const { return m_busy; }
    QString model() const { return m_model; }
    bool toolsSupported() const { return m_toolsSupported; }
    bool writeAllowed() const { return m_write; }
    QString error() const { return m_error; }
    bool engineInstalled() const { return EngineClient::isInstalled(); }

    Q_INVOKABLE void newConversation();
    Q_INVOKABLE void openConversation(const QString &id);
    Q_INVOKABLE void send(const QString &text);
    Q_INVOKABLE void stop();
    Q_INVOKABLE void confirm(const QString &requestId, bool allow);
    Q_INVOKABLE void deleteConversation(const QString &id);
    Q_INVOKABLE void refresh();
    Q_INVOKABLE void openSettings() const;
    Q_INVOKABLE void copy(const QString &text) const;
    // "Ran: lscpu", "Reading ~/a.pdf…" for a tool card
    Q_INVOKABLE QString toolLabel(const QString &function, const QString &args, bool running) const;

public Q_SLOTS:
    // D-Bus: Spotlight hands a conversation (maybe waiting for a confirmation) over
    void open(const QString &conversationId);
    // D-Bus: start a new conversation with this question
    void ask(const QString &text);

Q_SIGNALS:
    void conversationChanged();
    void busyChanged();
    void configChanged();
    void errorChanged();
    // The window should come to the front
    void raiseRequested();

private:
    void onEvent(const QVariantMap &event);
    void loadHistory(const QVariantMap &event);
    void setBusy(bool busy);
    void setError(const QString &error);
    QString statsText(const QVariantMap &stats) const;

    EngineClient m_engine;
    ChatModel m_messages;
    ConversationModel m_conversations;
    QString m_conversationId;
    QString m_pendingAsk;
    bool m_busy = false;
    bool m_fresh = true;   // the current conversation has no messages in the engine yet
    QString m_model;
    bool m_toolsSupported = true;
    bool m_write = false;
    QString m_error;
};
