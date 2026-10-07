/*
 * Copyright (C) 2026 LingmoOS Team.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * any later version.
 */

#pragma once

#include <QByteArray>
#include <QJsonObject>
#include <QList>
#include <QObject>
#include <QProcess>
#include <QVariantMap>

// Runs lingmo-assistant-engine with QProcess (argv, no shell) and speaks its
// NDJSON protocol (docs/protocol.md): requests go out as one JSON object per
// line, every stdout line becomes an event() signal.
class EngineClient : public QObject
{
    Q_OBJECT

public:
    explicit EngineClient(QObject *parent = nullptr);
    ~EngineClient() override;

    // Installed launcher, or $LINGMO_ASSISTANT_ENGINE for development
    static QString enginePath();
    static bool isInstalled();

    bool isRunning() const;
    void start();
    void send(const QJsonObject &request);

Q_SIGNALS:
    void event(const QVariantMap &event);
    // The engine exited or couldn't start; message is user-facing
    void failed(const QString &message);

private:
    void readOutput();

    QProcess m_process;
    QByteArray m_buffer;
    QList<QByteArray> m_queue;   // requests written before the process started
    bool m_stopping = false;
};
