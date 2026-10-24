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
#include <QJsonObject>
#include <QList>
#include <QPointF>
#include <QRectF>
#include <QVariantMap>

class FlowNodeModel;
class FlowEdgeModel;

// The workflow open in the editor: nodes and edges as list models for the
// canvas, the node catalogue from the engine, undo/redo (whole-document
// snapshots), auto-layout and the variables a node's fields can use.
// Serialises to the engine's versioned JSON format (backend/lingmo_assistant/flows/graph.py).
class FlowDocument : public QObject
{
    Q_OBJECT
    Q_PROPERTY(FlowNodeModel *nodes READ nodes CONSTANT)
    Q_PROPERTY(FlowEdgeModel *edges READ edges CONSTANT)
    Q_PROPERTY(QString flowId READ flowId NOTIFY changed)
    Q_PROPERTY(QString name READ name WRITE setName NOTIFY changed)
    Q_PROPERTY(QString description READ description WRITE setDescription NOTIFY changed)
    Q_PROPERTY(bool enabled READ enabled WRITE setEnabled NOTIFY changed)
    Q_PROPERTY(int revision READ revision NOTIFY changed)
    Q_PROPERTY(bool dirty READ dirty NOTIFY dirtyChanged)
    Q_PROPERTY(bool loaded READ loaded NOTIFY changed)
    Q_PROPERTY(bool canUndo READ canUndo NOTIFY historyChanged)
    Q_PROPERTY(bool canRedo READ canRedo NOTIFY historyChanged)
    Q_PROPERTY(QVariantMap catalogue READ catalogue WRITE setCatalogue NOTIFY catalogueChanged)
    Q_PROPERTY(QString triggerId READ triggerId NOTIFY changed)
    Q_PROPERTY(QRectF bounds READ bounds NOTIFY geometryChanged)

public:
    explicit FlowDocument(QObject *parent = nullptr);

    FlowNodeModel *nodes() const { return m_nodes; }
    FlowEdgeModel *edges() const { return m_edges; }
    QString flowId() const { return m_meta.value(QStringLiteral("id")).toString(); }
    QString name() const { return m_meta.value(QStringLiteral("name")).toString(); }
    void setName(const QString &name);
    QString description() const { return m_meta.value(QStringLiteral("description")).toString(); }
    void setDescription(const QString &text);
    bool enabled() const { return m_meta.value(QStringLiteral("enabled"), true).toBool(); }
    void setEnabled(bool on);
    int revision() const { return m_meta.value(QStringLiteral("revision")).toInt(); }
    bool dirty() const { return m_dirty; }
    bool loaded() const { return m_loaded; }
    bool canUndo() const { return !m_undo.isEmpty(); }
    bool canRedo() const { return !m_redo.isEmpty(); }
    QVariantMap catalogue() const { return m_catalogue; }
    void setCatalogue(const QVariantMap &catalogue);
    QString triggerId() const;
    QRectF bounds() const;

    // Loading and saving
    Q_INVOKABLE void load(const QVariantMap &flow);
    Q_INVOKABLE void clear();
    Q_INVOKABLE QVariantMap toVariant() const;
    Q_INVOKABLE QString toJson() const;
    Q_INVOKABLE bool loadJson(const QString &json);
    Q_INVOKABLE void markSaved(const QVariantMap &flow);

    // Editing (each one is an undo step)
    Q_INVOKABLE QString addNode(const QString &type, qreal x, qreal y);
    Q_INVOKABLE void removeNode(const QString &id);
    Q_INVOKABLE QString duplicateNode(const QString &id);
    Q_INVOKABLE bool connectPorts(const QString &from, const QString &port, const QString &to);
    Q_INVOKABLE void removeEdge(int row);
    Q_INVOKABLE void setParam(const QString &id, const QString &param, const QVariant &value);
    Q_INVOKABLE void setLabel(const QString &id, const QString &label);
    Q_INVOKABLE bool renameNode(const QString &id, const QString &newId);
    // Dragging: moveNode() while the pointer moves, endMove() once (the undo step)
    Q_INVOKABLE void moveNode(const QString &id, qreal x, qreal y);
    Q_INVOKABLE void endMove();
    Q_INVOKABLE void autoLayout();
    Q_INVOKABLE void undo();
    Q_INVOKABLE void redo();

    // Queries for QML
    Q_INVOKABLE QVariantMap nodeType(const QString &type) const;
    Q_INVOKABLE QVariantMap node(const QString &id) const;
    Q_INVOKABLE QVariantMap params(const QString &id) const;   // with the type's defaults
    Q_INVOKABLE QStringList ports(const QString &id) const;
    Q_INVOKABLE QString portLabel(const QString &id, const QString &port) const;
    Q_INVOKABLE bool hasInput(const QString &id) const;
    Q_INVOKABLE QStringList outputs(const QString &id) const;
    Q_INVOKABLE QVariantList variablesFor(const QString &id) const;
    Q_INVOKABLE QString summary(const QString &id) const;      // one line for the node card
    Q_INVOKABLE QString category(const QString &id) const;
    Q_INVOKABLE QVariantList palette(const QString &filter) const;
    Q_INVOKABLE bool wouldCycle(const QString &from, const QString &to) const;
    Q_INVOKABLE QStringList nodeIds() const;
    Q_INVOKABLE QVariantMap issue(const QString &id) const;   // {message, level} from validation

    // Live run state shown on the canvas
    Q_INVOKABLE void setNodeStatus(const QString &id, const QString &status, const QString &output = {},
                                   const QString &error = {});
    Q_INVOKABLE void clearRunState();
    Q_INVOKABLE void setIssues(const QVariantList &issues);

    // Serialisation helpers (also used by the unit tests)
    QJsonObject toJsonObject() const;
    static QString uniqueId(const QString &base, const QStringList &taken);

Q_SIGNALS:
    void changed();
    void dirtyChanged();
    void historyChanged();
    void catalogueChanged();
    void geometryChanged();

private:
    void snapshot();
    void restore(const QJsonObject &state);
    void setDirty(bool dirty);
    QString idBase(const QString &type) const;

    FlowNodeModel *m_nodes;
    FlowEdgeModel *m_edges;
    QVariantMap m_meta;
    QVariantMap m_catalogue;
    QHash<QString, QVariantMap> m_types;
    QList<QJsonObject> m_undo;
    QList<QJsonObject> m_redo;
    QJsonObject m_moveStart;
    bool m_moving = false;
    bool m_dirty = false;
    bool m_loaded = false;
};

class FlowNodeModel : public QAbstractListModel
{
    Q_OBJECT
    Q_PROPERTY(int count READ count NOTIFY countChanged)

public:
    enum Roles {
        IdRole = Qt::UserRole + 1, TypeRole, LabelRole, XRole, YRole, ParamsRole, StatusRole, OutputRole,
        ErrorRole, IssueRole, IssueLevelRole,
    };
    struct Node {
        QString id;
        QString type;
        QString label;
        qreal x = 0;
        qreal y = 0;
        QVariantMap params;
        QString status;      // run: running, waiting, done, error, declined
        QString output;
        QString error;
        QString issue;       // validation message
        QString issueLevel;
    };

    using QAbstractListModel::QAbstractListModel;
    int rowCount(const QModelIndex &parent = {}) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;
    int count() const { return m_items.size(); }
    Q_INVOKABLE int indexOf(const QString &id) const;

    const QList<Node> &items() const { return m_items; }
    void setItems(const QList<Node> &items);
    void append(const Node &node);
    void remove(int row);
    Node &at(int row) { return m_items[row]; }
    void touch(int row, const QList<int> &roles);

Q_SIGNALS:
    void countChanged();

private:
    QList<Node> m_items;
};

class FlowEdgeModel : public QAbstractListModel
{
    Q_OBJECT
    Q_PROPERTY(int count READ count NOTIFY countChanged)

public:
    enum Roles { FromRole = Qt::UserRole + 1, PortRole, ToRole, ActiveRole };
    struct Edge {
        QString from;
        QString port;
        QString to;
        bool active = false;   // the run went through it
    };

    using QAbstractListModel::QAbstractListModel;
    int rowCount(const QModelIndex &parent = {}) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;
    int count() const { return m_items.size(); }

    const QList<Edge> &items() const { return m_items; }
    void setItems(const QList<Edge> &items);
    void append(const Edge &edge);
    void remove(int row);
    void setActiveInto(const QString &to);
    void clearActive();

Q_SIGNALS:
    void countChanged();

private:
    QList<Edge> m_items;
};
