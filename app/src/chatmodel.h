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
#include <QList>
#include <QVariantMap>

// The items of one conversation: questions, answers, tool cards,
// confirmation cards and notices
class ChatModel : public QAbstractListModel
{
    Q_OBJECT
    Q_PROPERTY(int count READ count NOTIFY countChanged)

public:
    enum Roles {
        KindRole = Qt::UserRole + 1,  // user, assistant, tool, confirm, notice, error
        TextRole,
        ThinkingRole,                 // assistant: reasoning, no text yet
        StatsRole,
        FunctionRole,
        ToolRole,
        ArgsRole,
        OkRole,
        RunningRole,                  // tool: started, not finished
        OutputRole,
        RequestIdRole,
        TitleRole,
        DetailsRole,
        StateRole,                    // confirm: pending, allowed, denied, expired
    };

    struct Item {
        QString kind;
        QString text;
        bool thinking = false;
        QString stats;
        QString function;
        QString tool;
        QString args;
        bool ok = true;
        bool running = false;
        QString output;
        QString requestId;
        QString title;
        QString details;
        QString state;
    };

    explicit ChatModel(QObject *parent = nullptr);

    int rowCount(const QModelIndex &parent = {}) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;
    int count() const { return m_items.size(); }

    void clear();
    void append(const Item &item);
    // The answer being written: the last assistant item after the last user one
    void appendToken(const QString &text);
    void setThinking();
    void finishAnswer(const QString &stats);
    void toolStarted(const QString &function, const QString &tool, const QString &args);
    void toolEnded(const QString &function, bool ok, const QString &summary, const QString &output);
    void setConfirmState(const QString &requestId, const QString &state);
    bool hasPendingConfirmation() const;
    QString text(int row) const;

Q_SIGNALS:
    void countChanged();

private:
    int openAnswer();
    void changed(int row, const QList<int> &roles);

    QList<Item> m_items;
};
