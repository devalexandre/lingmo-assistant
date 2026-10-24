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
#include <QUrl>
#include <QVariantMap>

#include "chatmodel.h"
#include "engineclient.h"
#include "flowdocument.h"

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

    // Sections of the window: chat, flows, agents, settings
    Q_PROPERTY(QString section READ section WRITE setSection NOTIFY sectionChanged)

    // Workflows ("Fluxos")
    Q_PROPERTY(FlowDocument *flow READ flow CONSTANT)
    Q_PROPERTY(QVariantList flows READ flows NOTIFY flowsChanged)
    Q_PROPERTY(QVariantList templates READ templates NOTIFY catalogueChanged)
    Q_PROPERTY(QVariantList categories READ categories NOTIFY catalogueChanged)
    Q_PROPERTY(QVariantList accounts READ accounts NOTIFY catalogueChanged)
    Q_PROPERTY(QVariantList agentChoices READ agentChoices NOTIFY catalogueChanged)
    Q_PROPERTY(QStringList allowedFolders READ allowedFolders NOTIFY catalogueChanged)
    Q_PROPERTY(QVariantMap flowInfo READ flowInfo NOTIFY flowInfoChanged)
    Q_PROPERTY(QString runId READ runId NOTIFY runChanged)
    Q_PROPERTY(QString runStatus READ runStatus NOTIFY runChanged)
    Q_PROPERTY(QString runError READ runError NOTIFY runChanged)
    Q_PROPERTY(QString runMode READ runMode NOTIFY runChanged)
    Q_PROPERTY(QVariantList flowAsks READ flowAsks NOTIFY flowAsksChanged)
    Q_PROPERTY(QVariantList flowRuns READ flowRuns NOTIFY flowRunsChanged)
    Q_PROPERTY(QVariantMap runLog READ runLog NOTIFY runLogChanged)

    // Custom agents
    Q_PROPERTY(QVariantList agents READ agents NOTIFY agentsChanged)
    Q_PROPERTY(QVariantList agentTools READ agentTools NOTIFY agentsChanged)
    Q_PROPERTY(QVariantList models READ models NOTIFY modelsChanged)
    Q_PROPERTY(QString chatAgent READ chatAgent WRITE setChatAgent NOTIFY chatAgentChanged)

    // Voice
    Q_PROPERTY(bool voiceVisible READ voiceVisible WRITE setVoiceVisible NOTIFY voiceChanged)
    Q_PROPERTY(QString voiceState READ voiceState NOTIFY voiceChanged)        // idle, listening, transcribing, thinking, answering, error
    Q_PROPERTY(qreal voiceLevel READ voiceLevel NOTIFY voiceLevelChanged)
    Q_PROPERTY(qreal voiceSeconds READ voiceSeconds NOTIFY voiceLevelChanged)
    Q_PROPERTY(QString voiceText READ voiceText NOTIFY voiceChanged)
    Q_PROPERTY(QString voiceAnswer READ voiceAnswer NOTIFY voiceChanged)
    Q_PROPERTY(QString voiceMessage READ voiceMessage NOTIFY voiceChanged)
    Q_PROPERTY(bool speaking READ speaking NOTIFY voiceChanged)
    Q_PROPERTY(QVariantMap voiceInfo READ voiceInfo NOTIFY voiceInfoChanged)
    Q_PROPERTY(bool voiceReplies READ voiceReplies WRITE setVoiceReplies NOTIFY voiceSettingsChanged)
    Q_PROPERTY(QString ttsVoice READ ttsVoice WRITE setTtsVoice NOTIFY voiceSettingsChanged)
    Q_PROPERTY(qreal ttsRate READ ttsRate WRITE setTtsRate NOTIFY voiceSettingsChanged)

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

    QString section() const { return m_section; }
    void setSection(const QString &section);

    // ---- workflows
    FlowDocument *flow() { return &m_flow; }
    QVariantList flows() const { return m_flows; }
    QVariantList templates() const { return m_catalogue.value(QStringLiteral("templates")).toList(); }
    QVariantList categories() const { return m_catalogue.value(QStringLiteral("categories")).toList(); }
    QVariantList accounts() const { return m_catalogue.value(QStringLiteral("accounts")).toList(); }
    QVariantList agentChoices() const { return m_catalogue.value(QStringLiteral("agents")).toList(); }
    QStringList allowedFolders() const { return m_catalogue.value(QStringLiteral("folders")).toStringList(); }
    QVariantMap flowInfo() const { return m_flowInfo; }
    // The run of the workflow open in the editor (other workflows may run meanwhile)
    QString runId() const { return m_runs.value(m_flow.flowId()); }
    QString runStatus() const { return m_runFlow == m_flow.flowId() ? m_runStatus : QString(); }
    QString runError() const { return m_runFlow == m_flow.flowId() ? m_runError : QString(); }
    QString runMode() const { return m_runFlow == m_flow.flowId() ? m_runMode : QString(); }
    QVariantList flowAsks() const { return m_flowAsks; }
    QVariantList flowRuns() const { return m_flowRuns; }
    QVariantMap runLog() const { return m_runLog; }

    Q_INVOKABLE void refreshFlows();
    Q_INVOKABLE void newFlow(const QString &templateId);
    Q_INVOKABLE void openFlow(const QString &id);
    Q_INVOKABLE void closeFlow();
    Q_INVOKABLE void saveFlow();
    Q_INVOKABLE void validateFlow();
    Q_INVOKABLE void approveFlow(bool dontAsk);
    Q_INVOKABLE void runFlow(bool test);
    Q_INVOKABLE void runFlowById(const QString &id);
    Q_INVOKABLE void stopRun();
    Q_INVOKABLE void answerAsk(const QString &requestId, bool allow, bool dontAsk, const QString &text);
    Q_INVOKABLE void removeFlow(const QString &id);
    Q_INVOKABLE void setFlowEnabled(const QString &id, bool enabled);
    Q_INVOKABLE void importFlow(const QUrl &file);
    Q_INVOKABLE void exportFlow(const QUrl &file);
    Q_INVOKABLE void loadRuns();
    Q_INVOKABLE void openRun(const QString &runId);

    // ---- agents
    QVariantList agents() const { return m_agents; }
    QVariantList agentTools() const { return m_agentTools; }
    QVariantList models() const { return m_models; }
    QString chatAgent() const { return m_chatAgent; }
    void setChatAgent(const QString &id);
    Q_INVOKABLE QVariantMap agent(const QString &id) const;
    Q_INVOKABLE void refreshAgents();
    Q_INVOKABLE void refreshModels();
    Q_INVOKABLE void saveAgent(const QVariantMap &agent);
    Q_INVOKABLE void removeAgent(const QString &id);
    Q_INVOKABLE void chatWithAgent(const QString &id);
    Q_INVOKABLE QString toolTitle(const QString &id) const;
    Q_INVOKABLE QString toolDescription(const QString &id) const;

    // ---- voice
    bool voiceVisible() const { return m_voiceVisible; }
    void setVoiceVisible(bool visible);
    QString voiceState() const { return m_voiceState; }
    qreal voiceLevel() const { return m_voiceLevel; }
    qreal voiceSeconds() const { return m_voiceSeconds; }
    QString voiceText() const { return m_voiceText; }
    QString voiceAnswer() const { return m_voiceAnswer; }
    QString voiceMessage() const { return m_voiceMessage; }
    bool speaking() const { return m_speaking; }
    QVariantMap voiceInfo() const { return m_voiceInfo; }
    bool voiceReplies() const;
    void setVoiceReplies(bool on);
    QString ttsVoice() const;
    void setTtsVoice(const QString &voice);
    qreal ttsRate() const;
    void setTtsRate(qreal rate);
    Q_INVOKABLE void startVoice();
    Q_INVOKABLE void stopVoice();
    Q_INVOKABLE void cancelVoice();
    Q_INVOKABLE void speak(const QString &text);
    Q_INVOKABLE void stopSpeaking();
    Q_INVOKABLE void testVoice();
    Q_INVOKABLE void refreshVoices();

public Q_SLOTS:
    // D-Bus: Spotlight hands a conversation (maybe waiting for a confirmation) over
    void open(const QString &conversationId);
    // D-Bus: start a new conversation with this question
    void ask(const QString &text);
    // D-Bus: "Ask about the screen" (lingmo-screenshot) hands its conversation
    // over with the picture of the area (PNG/JPEG bytes, kept in memory only),
    // the text read from it and the window it came from. Follow-up questions
    // of that conversation send the picture again (ask_image).
    void continueWithImage(const QString &conversationId, const QByteArray &image, const QString &ocrText,
                           const QString &window);
    // D-Bus: push-to-talk (the global shortcut); a second call stops listening
    void voice();
    // D-Bus: show a section (chat, flows, agents, settings)
    void showSection(const QString &section);
    // D-Bus: open a workflow in the editor
    void showFlow(const QString &id);
    // D-Bus: run a workflow now (its manual trigger), e.g. from Spotlight
    void runWorkflow(const QString &id);

Q_SIGNALS:
    void conversationChanged();
    void busyChanged();
    void configChanged();
    void errorChanged();
    // The window should come to the front
    void raiseRequested();
    void sectionChanged();
    void flowsChanged();
    void catalogueChanged();
    void flowInfoChanged();
    void runChanged();
    void flowAsksChanged();
    void flowRunsChanged();
    void runLogChanged();
    void agentsChanged();
    void modelsChanged();
    void chatAgentChanged();
    void voiceChanged();
    void voiceLevelChanged();
    void voiceInfoChanged();
    void voiceSettingsChanged();
    // The saved workflow can do new things: ask the user to approve them
    void approvalNeeded(const QVariantMap &info);
    // Short message for a toast
    void toast(const QString &message);
    void agentSaved(const QString &id);

private:
    void onEvent(const QVariantMap &event);
    bool onExtraEvent(const QString &type, const QVariantMap &event);
    void setVoiceState(const QString &state, const QString &message = {});
    void writeAiSetting(const QString &key, const QVariant &value);
    QVariant aiSetting(const QString &key, const QVariant &fallback) const;
    void loadHistory(const QVariantMap &event);
    struct ScreenContext {
        QByteArray image;    // as received (PNG or JPEG)
        QSize size;
        QString ocrText;
        QString window;
        int serial = 0;
    };
    QHash<QString, ScreenContext> m_screens;   // conversation -> picture of the screen
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

    QString m_section = QStringLiteral("chat");
    FlowDocument m_flow;
    QVariantMap m_catalogue;
    QVariantList m_flows;
    QVariantMap m_flowInfo;
    bool m_saveRequested = false;
    QHash<QString, QString> m_runs;   // flow id -> run id, for runs of this app's engine
    QString m_runFlow;                // the flow the status below belongs to
    QString m_runStatus;
    QString m_runError;
    QString m_runMode;
    QVariantList m_flowAsks;
    QVariantList m_flowRuns;
    QVariantMap m_runLog;
    QVariantList m_agents;
    QVariantList m_agentTools;
    QVariantList m_models;
    QString m_chatAgent;
    bool m_voiceVisible = false;
    QString m_voiceState = QStringLiteral("idle");
    qreal m_voiceLevel = 0;
    qreal m_voiceSeconds = 0;
    QString m_voiceText;
    QString m_voiceAnswer;
    QString m_chatAnswer;   // the answer being streamed, read aloud when voice replies are on
    QString m_voiceMessage;
    QString m_voiceConversation;
    bool m_speaking = false;
    QVariantMap m_voiceInfo;
};
