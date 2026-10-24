/*
 * Copyright (C) 2026 LingmoOS Team.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * any later version.
 */

// Workflows, custom agents and voice (protocol 2, docs/protocol.md)

#include "assistant.h"

#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSaveFile>
#include <QSettings>
#include <QUuid>

static QJsonObject req(const QString &type)
{
    return QJsonObject{{QStringLiteral("type"), type}};
}

static QString key(const char *k)
{
    return QString::fromLatin1(k);
}

// ------------------------------------------------------------------ sections

void Assistant::setSection(const QString &section)
{
    static const QStringList known = {QStringLiteral("chat"), QStringLiteral("flows"), QStringLiteral("agents"),
                                      QStringLiteral("settings")};
    if (!known.contains(section) || section == m_section)
        return;
    m_section = section;
    Q_EMIT sectionChanged();
    if (!EngineClient::isInstalled())
        return;
    if (section == QLatin1String("flows")) {
        refreshFlows();
    } else if (section == QLatin1String("agents")) {
        refreshAgents();
        refreshModels();
    } else if (section == QLatin1String("settings")) {
        refreshVoices();
    }
}

void Assistant::showSection(const QString &section)
{
    setSection(section);
    Q_EMIT raiseRequested();
}

// ------------------------------------------------------------------ workflows

void Assistant::showFlow(const QString &id)
{
    setSection(QStringLiteral("flows"));
    openFlow(id);
    Q_EMIT raiseRequested();
}

void Assistant::runWorkflow(const QString &id)
{
    runFlowById(id);
}

void Assistant::refreshFlows()
{
    m_engine.send(req(key("flow_catalogue")));
    m_engine.send(req(key("flows")));
}

void Assistant::newFlow(const QString &templateId)
{
    QJsonObject r = req(key("flow_new"));
    if (!templateId.isEmpty())
        r.insert(key("template"), templateId);
    else
        r.insert(key("name"), tr("New workflow"));
    m_engine.send(r);
}

void Assistant::openFlow(const QString &id)
{
    m_engine.send(QJsonObject{{key("type"), key("flow_get")}, {key("id"), id}});
}

void Assistant::closeFlow()
{
    m_flow.clear();
    m_flowInfo.clear();
    m_flowAsks.clear();
    m_flowRuns.clear();
    m_runLog.clear();
    Q_EMIT flowInfoChanged();
    Q_EMIT flowAsksChanged();
    Q_EMIT flowRunsChanged();
    Q_EMIT runLogChanged();
    refreshFlows();
}

void Assistant::saveFlow()
{
    if (!m_flow.loaded())
        return;
    m_saveRequested = true;
    m_engine.send(QJsonObject{{key("type"), key("flow_save")},
                              {key("flow"), QJsonObject::fromVariantMap(m_flow.toVariant())}});
}

void Assistant::validateFlow()
{
    if (!m_flow.loaded())
        return;
    m_engine.send(QJsonObject{{key("type"), key("flow_validate")},
                              {key("flow"), QJsonObject::fromVariantMap(m_flow.toVariant())}});
}

void Assistant::approveFlow(bool dontAsk)
{
    m_engine.send(QJsonObject{{key("type"), key("flow_approve")}, {key("id"), m_flow.flowId()},
                              {key("cap_hash"), m_flowInfo.value(key("cap_hash")).toString()},
                              {key("dont_ask"), dontAsk}});
}

void Assistant::runFlow(bool test)
{
    if (!m_flow.loaded() || !runId().isEmpty())
        return;
    m_flow.clearRunState();
    m_engine.send(QJsonObject{{key("type"), key("flow_run")}, {key("flow_id"), m_flow.flowId()},
                              {key("mode"), test ? key("test") : key("run")}});
}

void Assistant::runFlowById(const QString &id)
{
    m_engine.send(QJsonObject{{key("type"), key("flow_run")}, {key("flow_id"), id}, {key("mode"), key("run")}});
}

void Assistant::stopRun()
{
    if (!runId().isEmpty())
        m_engine.send(QJsonObject{{key("type"), key("flow_stop")}, {key("run_id"), runId()}});
}

void Assistant::answerAsk(const QString &requestId, bool allow, bool dontAsk, const QString &text)
{
    QJsonObject r{{key("type"), key("flow_answer")}, {key("request_id"), requestId}, {key("allow"), allow},
                  {key("dont_ask"), dontAsk}};
    for (const QVariant &v : std::as_const(m_flowAsks))
        if (v.toMap().value(key("request_id")).toString() == requestId
            && v.toMap().value(key("kind")).toString() == QLatin1String("input"))
            r.insert(key("text"), text);
    m_engine.send(r);
}

void Assistant::removeFlow(const QString &id)
{
    m_engine.send(QJsonObject{{key("type"), key("flow_remove")}, {key("id"), id}});
    if (id == m_flow.flowId())
        closeFlow();
}

void Assistant::setFlowEnabled(const QString &id, bool enabled)
{
    m_engine.send(QJsonObject{{key("type"), key("flow_set_enabled")}, {key("id"), id}, {key("enabled"), enabled}});
}

void Assistant::importFlow(const QUrl &file)
{
    QFile f(file.toLocalFile());
    if (!f.open(QIODevice::ReadOnly) || f.size() > 2 * 1024 * 1024) {
        Q_EMIT toast(tr("The file couldn't be read."));
        return;
    }
    m_engine.send(QJsonObject{{key("type"), key("flow_import")}, {key("text"), QString::fromUtf8(f.readAll())}});
}

void Assistant::exportFlow(const QUrl &file)
{
    QString path = file.toLocalFile();
    if (path.isEmpty() || !m_flow.loaded())
        return;
    if (!path.endsWith(QLatin1String(".json")))
        path += QStringLiteral(".json");
    QSaveFile out(path);
    // Never exported: the approval (it stays on this computer)
    if (!out.open(QIODevice::WriteOnly) || out.write(m_flow.toJson().toUtf8()) < 0 || !out.commit()) {
        Q_EMIT toast(tr("The file couldn't be saved."));
        return;
    }
    Q_EMIT toast(tr("Workflow exported."));
}

void Assistant::loadRuns()
{
    if (m_flow.loaded())
        m_engine.send(QJsonObject{{key("type"), key("flow_runs")}, {key("flow_id"), m_flow.flowId()}});
}

void Assistant::openRun(const QString &runId)
{
    m_engine.send(QJsonObject{{key("type"), key("flow_run_log")}, {key("flow_id"), m_flow.flowId()},
                              {key("run_id"), runId}});
}

// ------------------------------------------------------------------ agents

void Assistant::refreshAgents()
{
    m_engine.send(req(key("agents")));
}

void Assistant::refreshModels()
{
    m_engine.send(req(key("models")));
}

QVariantMap Assistant::agent(const QString &id) const
{
    for (const QVariant &v : m_agents)
        if (v.toMap().value(key("id")).toString() == id)
            return v.toMap();
    return {};
}

void Assistant::saveAgent(const QVariantMap &agent)
{
    m_engine.send(QJsonObject{{key("type"), key("agent_save")}, {key("agent"), QJsonObject::fromVariantMap(agent)}});
}

void Assistant::removeAgent(const QString &id)
{
    m_engine.send(QJsonObject{{key("type"), key("agent_remove")}, {key("id"), id}});
    if (id == m_chatAgent)
        setChatAgent({});
}

void Assistant::setChatAgent(const QString &id)
{
    if (id == m_chatAgent)
        return;
    // An agent belongs to a conversation: switching starts a new one
    if (m_messages.count() > 0)
        newConversation();
    m_chatAgent = id;
    Q_EMIT chatAgentChanged();
}

void Assistant::chatWithAgent(const QString &id)
{
    newConversation();
    m_chatAgent = id;
    Q_EMIT chatAgentChanged();
    setSection(QStringLiteral("chat"));
}

QString Assistant::toolTitle(const QString &id) const
{
    static const QHash<QString, const char *> titles = {
        {QStringLiteral("system_info"), QT_TR_NOOP("System information")},
        {QStringLiteral("shell_read"), QT_TR_NOOP("Read-only commands")},
        {QStringLiteral("read_files"), QT_TR_NOOP("Read files")},
        {QStringLiteral("search_files"), QT_TR_NOOP("Search files")},
        {QStringLiteral("notes_read"), QT_TR_NOOP("Read notes")},
        {QStringLiteral("calendar_read"), QT_TR_NOOP("Read the calendar")},
        {QStringLiteral("web"), QT_TR_NOOP("Web search")},
        {QStringLiteral("mail_read"), QT_TR_NOOP("Read e-mail")},
        {QStringLiteral("notes_write"), QT_TR_NOOP("Write notes")},
        {QStringLiteral("calendar_write"), QT_TR_NOOP("Create events and tasks")},
        {QStringLiteral("files_write"), QT_TR_NOOP("Write files")},
        {QStringLiteral("mail_write"), QT_TR_NOOP("Send e-mail")},
        {QStringLiteral("alarms_write"), QT_TR_NOOP("Alarms and timers")},
        {QStringLiteral("desktop_actions"), QT_TR_NOOP("Open apps and sites")},
    };
    const char *t = titles.value(id);
    return t ? tr(t) : id;
}

QString Assistant::toolDescription(const QString &id) const
{
    static const QHash<QString, const char *> texts = {
        {QStringLiteral("system_info"), QT_TR_NOOP("Hardware, disks, battery and the system")},
        {QStringLiteral("shell_read"), QT_TR_NOOP("A fixed list of commands that only read, in a sandbox")},
        {QStringLiteral("read_files"), QT_TR_NOOP("Documents in the allowed folders")},
        {QStringLiteral("search_files"), QT_TR_NOOP("Find files by name and content")},
        {QStringLiteral("notes_read"), QT_TR_NOOP("Pages of Lingmo Notes")},
        {QStringLiteral("calendar_read"), QT_TR_NOOP("Events and tasks of Lingmo Mail")},
        {QStringLiteral("web"), QT_TR_NOOP("Searches and pages on the internet")},
        {QStringLiteral("mail_read"), QT_TR_NOOP("Messages of your Lingmo Mail accounts")},
        {QStringLiteral("notes_write"), QT_TR_NOOP("Create pages and add text")},
        {QStringLiteral("calendar_write"), QT_TR_NOOP("Events, reminders and tasks")},
        {QStringLiteral("files_write"), QT_TR_NOOP("Text files in the allowed folders, never deleting")},
        {QStringLiteral("mail_write"), QT_TR_NOOP("Send and reply as you, after you confirm")},
        {QStringLiteral("alarms_write"), QT_TR_NOOP("Alarms and timers of Lingmo Clock")},
        {QStringLiteral("desktop_actions"), QT_TR_NOOP("Open installed apps and https addresses")},
    };
    const char *t = texts.value(id);
    return t ? tr(t) : QString();
}

// ------------------------------------------------------------------ voice

QVariant Assistant::aiSetting(const QString &k, const QVariant &fallback) const
{
    QSettings settings(QStringLiteral("lingmoos"), QStringLiteral("ai"));
    return settings.value(k, fallback);
}

void Assistant::writeAiSetting(const QString &k, const QVariant &value)
{
    QSettings settings(QStringLiteral("lingmoos"), QStringLiteral("ai"));
    settings.setValue(k, value);
    settings.sync();
    Q_EMIT voiceSettingsChanged();
}

bool Assistant::voiceReplies() const
{
    return aiSetting(QStringLiteral("assistant_voice_replies"), false).toBool();
}

void Assistant::setVoiceReplies(bool on)
{
    if (on != voiceReplies())
        writeAiSetting(QStringLiteral("assistant_voice_replies"), on);
}

QString Assistant::ttsVoice() const
{
    return aiSetting(QStringLiteral("assistant_tts_voice"), QString()).toString();
}

void Assistant::setTtsVoice(const QString &voice)
{
    if (voice != ttsVoice())
        writeAiSetting(QStringLiteral("assistant_tts_voice"), voice);
}

qreal Assistant::ttsRate() const
{
    return qBound(0.5, aiSetting(QStringLiteral("assistant_tts_rate"), 1.0).toDouble(), 2.0);
}

void Assistant::setTtsRate(qreal rate)
{
    rate = qBound(0.5, qRound(rate * 20) / 20.0, 2.0);
    if (!qFuzzyCompare(rate, ttsRate()))
        writeAiSetting(QStringLiteral("assistant_tts_rate"), rate);
}

void Assistant::setVoiceVisible(bool visible)
{
    if (visible == m_voiceVisible)
        return;
    m_voiceVisible = visible;
    if (!visible) {
        cancelVoice();
        m_voiceConversation.clear();
    }
    Q_EMIT voiceChanged();
}

void Assistant::setVoiceState(const QString &state, const QString &message)
{
    m_voiceState = state;
    m_voiceMessage = message;
    if (state != QLatin1String("listening")) {
        m_voiceLevel = 0;
        Q_EMIT voiceLevelChanged();
    }
    Q_EMIT voiceChanged();
}

void Assistant::voice()
{
    // The global shortcut: open the pill and listen; a second press while
    // listening ends the recording
    if (m_voiceVisible && m_voiceState == QLatin1String("listening")) {
        stopVoice();
        return;
    }
    startVoice();
}

void Assistant::startVoice()
{
    if (!EngineClient::isInstalled())
        return;
    stopSpeaking();
    m_voiceText.clear();
    m_voiceAnswer.clear();
    m_voiceVisible = true;
    setVoiceState(QStringLiteral("listening"));
    m_engine.send(req(key("voice_start")));
}

void Assistant::stopVoice()
{
    m_engine.send(req(key("voice_stop")));
}

void Assistant::cancelVoice()
{
    if (m_voiceState == QLatin1String("listening"))
        m_engine.send(req(key("voice_cancel")));
    stopSpeaking();
}

void Assistant::speak(const QString &text)
{
    if (!text.trimmed().isEmpty())
        m_engine.send(QJsonObject{{key("type"), key("speak")}, {key("text"), text}});
}

void Assistant::stopSpeaking()
{
    if (m_speaking)
        m_engine.send(req(key("speak_stop")));
}

void Assistant::testVoice()
{
    speak(tr("Hello! This is how I will answer when voice replies are on."));
}

void Assistant::refreshVoices()
{
    m_engine.send(req(key("voice_status")));
}

// ------------------------------------------------------------------ events

static QVariantList withoutRequest(const QVariantList &list, const QString &requestId)
{
    QVariantList out;
    for (const QVariant &v : list)
        if (v.toMap().value(QStringLiteral("request_id")).toString() != requestId)
            out << v;
    return out;
}

bool Assistant::onExtraEvent(const QString &type, const QVariantMap &event)
{
    if (type == QLatin1String("flow_catalogue")) {
        m_catalogue = event;
        m_flow.setCatalogue(event);
        Q_EMIT catalogueChanged();
        return true;
    }
    if (type == QLatin1String("flows")) {
        m_flows = event.value(key("items")).toList();
        Q_EMIT flowsChanged();
        return true;
    }
    if (type == QLatin1String("flow")) {
        m_flow.load(event.value(key("flow")).toMap());
        m_flowInfo = event.value(key("info")).toMap();
        m_flow.setIssues(m_flowInfo.value(key("issues")).toList());
        m_flowRuns.clear();
        m_runLog.clear();
        Q_EMIT flowInfoChanged();
        Q_EMIT flowAsksChanged();
        Q_EMIT flowRunsChanged();
        Q_EMIT runLogChanged();
        Q_EMIT runChanged();
        setSection(QStringLiteral("flows"));
        loadRuns();
        return true;
    }
    if (type == QLatin1String("flow_issues")) {
        if (event.value(key("id")).toString() == m_flow.flowId()) {
            m_flowInfo.insert(key("issues"), event.value(key("issues")));
            m_flowInfo.insert(key("summary"), event.value(key("summary")));
            m_flowInfo.insert(key("capabilities"), event.value(key("capabilities")));
            m_flow.setIssues(event.value(key("issues")).toList());
            Q_EMIT flowInfoChanged();
        }
        return true;
    }
    if (type == QLatin1String("flow_saved")) {
        const QVariantMap flow = event.value(key("flow")).toMap();
        const QVariantMap info = event.value(key("info")).toMap();
        if (flow.value(key("id")).toString() == m_flow.flowId() || m_saveRequested) {
            m_flow.markSaved(flow);
            m_flowInfo = info;
            m_flow.setIssues(info.value(key("issues")).toList());
            Q_EMIT flowInfoChanged();
            if (m_saveRequested) {
                m_saveRequested = false;
                if (!info.value(key("approved")).toBool())
                    Q_EMIT approvalNeeded(info);
                else
                    Q_EMIT toast(tr("Workflow saved."));
            }
        } else if (!m_flow.loaded()) {
            // imported: open it so the user reviews and approves it
            m_flow.load(flow);
            m_flowInfo = info;
            Q_EMIT flowInfoChanged();
            Q_EMIT toast(tr("Workflow imported. Review it and save to approve what it can do."));
        }
        return true;
    }
    if (type == QLatin1String("flow_export"))
        return true;
    if (type == QLatin1String("flow_run_started")) {
        const QString flowId = event.value(key("flow_id")).toString();
        m_runs.insert(flowId, event.value(key("run_id")).toString());
        if (flowId == m_flow.flowId()) {
            m_runFlow = flowId;
            m_runStatus = QStringLiteral("running");
            m_runError.clear();
            m_runMode = event.value(key("mode")).toString();
            m_flow.clearRunState();
        } else {
            Q_EMIT toast(tr("Running “%1”…").arg(event.value(key("flow_name")).toString()));
        }
        Q_EMIT runChanged();
        return true;
    }
    if (type == QLatin1String("flow_node")) {
        if (event.value(key("run_id")).toString() == runId())
            m_flow.setNodeStatus(event.value(key("node")).toString(), event.value(key("status")).toString(),
                                 event.value(key("output")).toString(), event.value(key("error")).toString());
        return true;
    }
    if (type == QLatin1String("flow_ask")) {
        m_flowAsks << event;
        Q_EMIT flowAsksChanged();
        if (event.value(key("flow_id")).toString() != m_flow.flowId() || m_section != QLatin1String("flows")) {
            // a voice- or app-started run elsewhere: bring the window and the workflow up
            openFlow(event.value(key("flow_id")).toString());
        }
        Q_EMIT raiseRequested();
        return true;
    }
    if (type == QLatin1String("flow_ask_resolved")) {
        m_flowAsks = withoutRequest(m_flowAsks, event.value(key("request_id")).toString());
        Q_EMIT flowAsksChanged();
        return true;
    }
    if (type == QLatin1String("flow_run_done")) {
        const QString status = event.value(key("status")).toString();
        const QString error = event.value(key("error")).toString();
        const QString flowId = event.value(key("flow_id")).toString();
        m_runs.remove(flowId);
        if (flowId == m_flow.flowId()) {
            m_runFlow = flowId;
            m_runStatus = status;
            m_runError = error;
            loadRuns();
        } else if (status != QLatin1String("done")) {
            Q_EMIT toast(error.isEmpty() ? tr("The workflow didn't finish.") : error);
        }
        Q_EMIT runChanged();
        if (m_voiceVisible && m_voiceState == QLatin1String("thinking")) {
            setVoiceState(QStringLiteral("idle"), status == QLatin1String("done") ? tr("Done.") : error);
        }
        return true;
    }
    if (type == QLatin1String("flow_runs")) {
        m_flowRuns = event.value(key("items")).toList();
        Q_EMIT flowRunsChanged();
        return true;
    }
    if (type == QLatin1String("flow_run_log")) {
        m_runLog = event.value(key("run")).toMap();
        Q_EMIT runLogChanged();
        // show the logged statuses on the canvas
        m_flow.clearRunState();
        for (const QVariant &v : m_runLog.value(key("steps")).toList()) {
            const QVariantMap s = v.toMap();
            m_flow.setNodeStatus(s.value(key("node")).toString(), s.value(key("status")).toString(),
                                 s.value(key("outputs")).toMap().value(key("output")).toString(),
                                 s.value(key("error")).toString());
        }
        return true;
    }
    if (type == QLatin1String("agents")) {
        m_agents = event.value(key("items")).toList();
        m_agentTools = event.value(key("tools")).toList();
        Q_EMIT agentsChanged();
        return true;
    }
    if (type == QLatin1String("agent_saved")) {
        Q_EMIT agentSaved(event.value(key("agent")).toMap().value(key("id")).toString());
        Q_EMIT toast(tr("Agent saved."));
        return true;
    }
    if (type == QLatin1String("models")) {
        m_models = event.value(key("items")).toList();
        Q_EMIT modelsChanged();
        return true;
    }
    if (type == QLatin1String("voice_status")) {
        m_voiceInfo = event;
        Q_EMIT voiceInfoChanged();
        return true;
    }
    if (type == QLatin1String("voice_level")) {
        m_voiceLevel = event.value(key("level")).toDouble();
        m_voiceSeconds = event.value(key("seconds")).toDouble();
        Q_EMIT voiceLevelChanged();
        return true;
    }
    if (type == QLatin1String("voice_state")) {
        const QString state = event.value(key("state")).toString();
        if (state == QLatin1String("idle") && (m_voiceState == QLatin1String("thinking")
                                               || m_voiceState == QLatin1String("answering")))
            return true;   // the engine is done listening; the answer is still coming
        setVoiceState(state, event.value(key("message")).toString());
        return true;
    }
    if (type == QLatin1String("voice_text")) {
        m_voiceText = event.value(key("text")).toString();
        const QString flowId = event.value(key("flow_id")).toString();
        if (!flowId.isEmpty()) {
            setVoiceState(QStringLiteral("thinking"), tr("Running the workflow “%1”…")
                                                         .arg(event.value(key("flow_name")).toString()));
        } else if (!m_voiceText.trimmed().isEmpty() && m_voiceVisible) {
            m_voiceAnswer.clear();
            newConversation();
            m_voiceConversation = m_conversationId;
            setVoiceState(QStringLiteral("thinking"));
            send(m_voiceText);
        } else {
            setVoiceState(QStringLiteral("idle"), tr("I didn't hear anything."));
        }
        return true;
    }
    if (type == QLatin1String("speak_state")) {
        m_speaking = event.value(key("speaking")).toBool();
        Q_EMIT voiceChanged();
        return true;
    }
    if (type == QLatin1String("speak_file"))
        return true;
    if (type == QLatin1String("error") && event.contains(key("request"))) {
        const QString request = event.value(key("request")).toString();
        if (request.startsWith(QLatin1String("flow_")) || request.startsWith(QLatin1String("agent"))
            || request == QLatin1String("speak")) {
            m_saveRequested = false;
            Q_EMIT toast(event.value(key("message")).toString());
            return true;
        }
    }
    return false;
}
