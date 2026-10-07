/*
 * Copyright (C) 2026 LingmoOS Team.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * any later version.
 */

#include "engineclient.h"

#include <QFileInfo>
#include <QJsonDocument>

// An event line never gets near this; protects against a misbehaving engine
static constexpr int MaxBuffer = 8 * 1024 * 1024;

EngineClient::EngineClient(QObject *parent)
    : QObject(parent)
{
    // Logs stay on our stderr; the protocol is on stdout only
    m_process.setProcessChannelMode(QProcess::ForwardedErrorChannel);
    connect(&m_process, &QProcess::readyReadStandardOutput, this, &EngineClient::readOutput);
    connect(&m_process, &QProcess::started, this, [this] {
        for (const QByteArray &line : std::as_const(m_queue))
            m_process.write(line);
        m_queue.clear();
    });
    connect(&m_process, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) {
            m_queue.clear();
            Q_EMIT failed(tr("The assistant engine couldn't start. Reinstall Lingmo Assistant."));
        }
    });
    connect(&m_process, &QProcess::finished, this, [this](int, QProcess::ExitStatus) {
        m_buffer.clear();
        if (!m_stopping)
            Q_EMIT failed(tr("The assistant engine stopped. It will restart with the next question."));
    });
}

EngineClient::~EngineClient()
{
    m_stopping = true;
    if (m_process.state() != QProcess::NotRunning) {
        m_process.closeWriteChannel();   // the engine exits on EOF
        if (!m_process.waitForFinished(1500))
            m_process.kill();
        m_process.waitForFinished(500);
    }
}

QString EngineClient::enginePath()
{
    const QString override = qEnvironmentVariable("LINGMO_ASSISTANT_ENGINE");
    return override.isEmpty() ? QStringLiteral(ENGINE_PATH) : override;
}

bool EngineClient::isInstalled()
{
    const QFileInfo info(enginePath());
    return info.isFile() && info.isExecutable();
}

bool EngineClient::isRunning() const
{
    return m_process.state() != QProcess::NotRunning;
}

void EngineClient::start()
{
    if (isRunning())
        return;
    m_buffer.clear();
    m_process.start(enginePath(), {});
}

void EngineClient::send(const QJsonObject &request)
{
    const QByteArray line = QJsonDocument(request).toJson(QJsonDocument::Compact) + '\n';
    if (m_process.state() == QProcess::Running) {
        m_process.write(line);
        return;
    }
    m_queue << line;
    start();
}

void EngineClient::readOutput()
{
    m_buffer += m_process.readAllStandardOutput();
    if (m_buffer.size() > MaxBuffer) {
        m_buffer.clear();
        return;
    }
    int newline;
    while ((newline = m_buffer.indexOf('\n')) >= 0) {
        const QByteArray line = m_buffer.left(newline).trimmed();
        m_buffer.remove(0, newline + 1);
        if (line.isEmpty())
            continue;
        const QJsonDocument doc = QJsonDocument::fromJson(line);
        if (doc.isObject())
            Q_EMIT event(doc.object().toVariantMap());
    }
}
