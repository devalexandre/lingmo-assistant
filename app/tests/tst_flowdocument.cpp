/*
 * Copyright (C) 2026 LingmoOS Team.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * any later version.
 */

// The workflow editor's model: editing, undo/redo, auto-layout, variables and
// the round trip through the engine's JSON format.

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSignalSpy>
#include <QTest>

#include "flowdocument.h"

static QVariantMap type(const QString &id, const QString &category, const QStringList &ports,
                        const QStringList &outputs, const QVariantList &params = {})
{
    return {{QStringLiteral("type"), id}, {QStringLiteral("category"), category}, {QStringLiteral("label"), id},
            {QStringLiteral("ports"), ports}, {QStringLiteral("outputs"), outputs}, {QStringLiteral("params"), params},
            {QStringLiteral("port_labels"), QVariantMap{{QStringLiteral("true"), QStringLiteral("Sim")},
                                                        {QStringLiteral("false"), QStringLiteral("Não")}}}};
}

static QVariantMap catalogue()
{
    const QVariantMap text{{QStringLiteral("name"), QStringLiteral("title")}, {QStringLiteral("kind"), QStringLiteral("text")},
                           {QStringLiteral("default"), QStringLiteral("Olá")}};
    const QVariantMap cases{{QStringLiteral("name"), QStringLiteral("cases")}, {QStringLiteral("kind"), QStringLiteral("list")},
                            {QStringLiteral("default"), QStringList{QStringLiteral("a"), QStringLiteral("b")}}};
    const QVariantMap fields{{QStringLiteral("name"), QStringLiteral("fields")}, {QStringLiteral("kind"), QStringLiteral("list")},
                             {QStringLiteral("default"), QStringList{QStringLiteral("data")}}};
    const QVariantMap schedule{{QStringLiteral("name"), QStringLiteral("schedule")}, {QStringLiteral("kind"), QStringLiteral("schedule")},
                               {QStringLiteral("default"), QVariantMap{{QStringLiteral("kind"), QStringLiteral("weekdays")},
                                                                       {QStringLiteral("time"), QStringLiteral("09:00")},
                                                                       {QStringLiteral("days"), QVariantList{0, 1, 2, 3, 4}}}}};
    QVariantList types{
        type(QStringLiteral("trigger.manual"), QStringLiteral("triggers"), {QStringLiteral("out")}, {QStringLiteral("output")}),
        type(QStringLiteral("trigger.schedule"), QStringLiteral("triggers"), {QStringLiteral("out")},
             {QStringLiteral("date"), QStringLiteral("output")}, {schedule}),
        type(QStringLiteral("action.system.notify"), QStringLiteral("actions"), {QStringLiteral("out")}, {QStringLiteral("output")}, {text}),
        type(QStringLiteral("logic.if"), QStringLiteral("logic"), {QStringLiteral("true"), QStringLiteral("false")}, {QStringLiteral("output")}),
        type(QStringLiteral("logic.switch"), QStringLiteral("logic"), {}, {QStringLiteral("output")}, {cases}),
        type(QStringLiteral("logic.loop"), QStringLiteral("logic"), {QStringLiteral("each"), QStringLiteral("done")}, {QStringLiteral("output")}),
        type(QStringLiteral("logic.set"), QStringLiteral("logic"), {QStringLiteral("out")}, {QStringLiteral("output")}),
        type(QStringLiteral("ai.extract"), QStringLiteral("ai"), {QStringLiteral("out")}, {QStringLiteral("output")}, {fields}),
    };
    return {{QStringLiteral("types"), types}};
}

class TestFlowDocument : public QObject
{
    Q_OBJECT

private Q_SLOTS:
    void editingAndIds()
    {
        FlowDocument doc;
        doc.setCatalogue(catalogue());
        doc.load({{QStringLiteral("id"), QStringLiteral("f1")}, {QStringLiteral("name"), QStringLiteral("Teste")}});
        QVERIFY(!doc.dirty());
        const QString t = doc.addNode(QStringLiteral("trigger.manual"), 0, 0);
        QCOMPARE(t, QStringLiteral("trigger"));
        const QString a = doc.addNode(QStringLiteral("action.system.notify"), 300, 0);
        const QString b = doc.addNode(QStringLiteral("action.system.notify"), 600, 0);
        QCOMPARE(a, QStringLiteral("aviso"));
        QCOMPARE(b, QStringLiteral("aviso_2"));
        QVERIFY(doc.dirty());
        QVERIFY(doc.addNode(QStringLiteral("unknown.type"), 0, 0).isEmpty());
        // a second trigger replaces the first instead of adding one
        QCOMPARE(doc.addNode(QStringLiteral("trigger.schedule"), 0, 0), QStringLiteral("trigger"));
        QCOMPARE(doc.nodes()->count(), 3);
        QCOMPARE(doc.summary(QStringLiteral("trigger")), FlowDocument::tr("Weekdays at %1").arg(QStringLiteral("09:00")));
        // defaults fill in params
        QCOMPARE(doc.params(a).value(QStringLiteral("title")).toString(), QStringLiteral("Olá"));
        QVERIFY(FlowDocument::uniqueId(QStringLiteral("loop"), {}) != QStringLiteral("loop"));
    }

    void connectingRules()
    {
        FlowDocument doc;
        doc.setCatalogue(catalogue());
        doc.load({{QStringLiteral("id"), QStringLiteral("f1")}});
        const QString t = doc.addNode(QStringLiteral("trigger.manual"), 0, 0);
        const QString a = doc.addNode(QStringLiteral("logic.if"), 300, 0);
        const QString b = doc.addNode(QStringLiteral("action.system.notify"), 600, 0);
        QVERIFY(doc.connectPorts(t, QStringLiteral("out"), a));
        QVERIFY(doc.connectPorts(a, QStringLiteral("true"), b));
        QVERIFY(!doc.connectPorts(a, QStringLiteral("true"), b));          // duplicate
        QVERIFY(!doc.connectPorts(a, QStringLiteral("maybe"), b));         // no such port
        QVERIFY(!doc.connectPorts(b, QStringLiteral("out"), t));           // a trigger has no input
        QVERIFY(!doc.connectPorts(b, QStringLiteral("out"), a));           // cycle
        QVERIFY(!doc.connectPorts(a, QStringLiteral("false"), a));         // itself
        QCOMPARE(doc.edges()->count(), 2);
        QCOMPARE(doc.portLabel(a, QStringLiteral("true")), QStringLiteral("Sim"));
        // removing a node removes its edges
        doc.removeNode(a);
        QCOMPARE(doc.edges()->count(), 0);
    }

    void switchPortsFollowCases()
    {
        FlowDocument doc;
        doc.setCatalogue(catalogue());
        doc.load({{QStringLiteral("id"), QStringLiteral("f1")}});
        const QString t = doc.addNode(QStringLiteral("trigger.manual"), 0, 0);
        const QString s = doc.addNode(QStringLiteral("logic.switch"), 300, 0);
        const QString x = doc.addNode(QStringLiteral("action.system.notify"), 600, 0);
        doc.connectPorts(t, QStringLiteral("out"), s);
        QCOMPARE(doc.ports(s), (QStringList{QStringLiteral("case_0"), QStringLiteral("case_1"), QStringLiteral("default")}));
        QCOMPARE(doc.portLabel(s, QStringLiteral("case_1")), QStringLiteral("b"));
        QVERIFY(doc.connectPorts(s, QStringLiteral("case_1"), x));
        doc.setParam(s, QStringLiteral("cases"), QStringList{QStringLiteral("só um")});
        QCOMPARE(doc.ports(s).size(), 2);
        QCOMPARE(doc.edges()->count(), 1);    // the edge from case_1 went away
    }

    void undoRedoAndMoves()
    {
        FlowDocument doc;
        doc.setCatalogue(catalogue());
        doc.load({{QStringLiteral("id"), QStringLiteral("f1")}, {QStringLiteral("name"), QStringLiteral("A")}});
        const QString t = doc.addNode(QStringLiteral("trigger.manual"), 0, 0);
        const QString a = doc.addNode(QStringLiteral("action.system.notify"), 300, 0);
        doc.setParam(a, QStringLiteral("title"), QStringLiteral("Novo"));
        doc.setName(QStringLiteral("B"));
        QVERIFY(doc.canUndo());
        doc.undo();
        QCOMPARE(doc.name(), QStringLiteral("A"));
        doc.undo();
        QCOMPARE(doc.params(a).value(QStringLiteral("title")).toString(), QStringLiteral("Olá"));
        QVERIFY(doc.canRedo());
        doc.redo();
        QCOMPARE(doc.params(a).value(QStringLiteral("title")).toString(), QStringLiteral("Novo"));
        // a drag is one undo step, however many moves
        for (int i = 1; i <= 20; ++i)
            doc.moveNode(a, 300 + i * 10, i * 5);
        doc.endMove();
        QCOMPARE(doc.node(a).value(QStringLiteral("x")).toReal(), 500.0);
        doc.undo();
        QCOMPARE(doc.node(a).value(QStringLiteral("x")).toReal(), 300.0);
        doc.redo();
        QCOMPARE(doc.node(a).value(QStringLiteral("y")).toReal(), 100.0);
        // a new edit clears the redo stack
        doc.undo();
        doc.setLabel(t, QStringLiteral("Início"));
        QVERIFY(!doc.canRedo());
    }

    void autoLayoutLayers()
    {
        FlowDocument doc;
        doc.setCatalogue(catalogue());
        doc.load({{QStringLiteral("id"), QStringLiteral("f1")}});
        const QString t = doc.addNode(QStringLiteral("trigger.manual"), 900, 900);
        const QString c = doc.addNode(QStringLiteral("logic.if"), 10, 10);
        const QString y = doc.addNode(QStringLiteral("action.system.notify"), 10, 10);
        const QString n = doc.addNode(QStringLiteral("action.system.notify"), 10, 10);
        const QString end = doc.addNode(QStringLiteral("logic.set"), 10, 10);
        doc.connectPorts(t, QStringLiteral("out"), c);
        doc.connectPorts(c, QStringLiteral("true"), y);
        doc.connectPorts(c, QStringLiteral("false"), n);
        doc.connectPorts(y, QStringLiteral("out"), end);
        doc.connectPorts(n, QStringLiteral("out"), end);
        doc.autoLayout();
        auto x = [&](const QString &id) { return doc.node(id).value(QStringLiteral("x")).toReal(); };
        auto yy = [&](const QString &id) { return doc.node(id).value(QStringLiteral("y")).toReal(); };
        QVERIFY(x(t) < x(c));
        QVERIFY(x(c) < x(y));
        QCOMPARE(x(y), x(n));
        QVERIFY(yy(y) != yy(n));
        QVERIFY(x(end) > x(y));
        doc.undo();
        QCOMPARE(x(t), 900.0);
    }

    void variablesForAutocomplete()
    {
        FlowDocument doc;
        doc.setCatalogue(catalogue());
        doc.load({{QStringLiteral("id"), QStringLiteral("f1")}});
        const QString t = doc.addNode(QStringLiteral("trigger.schedule"), 0, 0);
        const QString x = doc.addNode(QStringLiteral("ai.extract"), 300, 0);
        doc.setParam(x, QStringLiteral("fields"), QStringList{QStringLiteral("data"), QStringLiteral("hora")});
        const QString loop = doc.addNode(QStringLiteral("logic.loop"), 600, 0);
        const QString inside = doc.addNode(QStringLiteral("action.system.notify"), 900, 0);
        const QString after = doc.addNode(QStringLiteral("action.system.notify"), 900, 200);
        const QString lonely = doc.addNode(QStringLiteral("action.system.notify"), 900, 400);
        doc.connectPorts(t, QStringLiteral("out"), x);
        doc.connectPorts(x, QStringLiteral("out"), loop);
        doc.connectPorts(loop, QStringLiteral("each"), inside);
        doc.connectPorts(loop, QStringLiteral("done"), after);
        auto texts = [&](const QString &id) {
            QStringList out;
            for (const QVariant &v : doc.variablesFor(id))
                out << v.toMap().value(QStringLiteral("text")).toString();
            return out;
        };
        const QStringList in = texts(inside);
        QVERIFY(in.contains(QStringLiteral("{{trigger.date}}")));
        QVERIFY(in.contains(QStringLiteral("{{%1.hora}}").arg(x)));
        QVERIFY(in.contains(QStringLiteral("{{loop.item}}")));
        QVERIFY(!texts(after).contains(QStringLiteral("{{loop.item}}")));
        QVERIFY(!texts(lonely).contains(QStringLiteral("{{trigger.date}}")));
    }

    void renameKeepsReferences()
    {
        FlowDocument doc;
        doc.setCatalogue(catalogue());
        doc.load({{QStringLiteral("id"), QStringLiteral("f1")}});
        const QString t = doc.addNode(QStringLiteral("trigger.manual"), 0, 0);
        const QString a = doc.addNode(QStringLiteral("logic.set"), 300, 0);
        const QString b = doc.addNode(QStringLiteral("action.system.notify"), 600, 0);
        doc.connectPorts(t, QStringLiteral("out"), a);
        doc.connectPorts(a, QStringLiteral("out"), b);
        doc.setParam(b, QStringLiteral("title"), QStringLiteral("Valor: {{%1.output}} e {{%1}}").arg(a));
        QVERIFY(!doc.renameNode(a, QStringLiteral("Bad Name")));
        QVERIFY(!doc.renameNode(a, QStringLiteral("loop")));
        QVERIFY(doc.renameNode(a, QStringLiteral("resumo")));
        QCOMPARE(doc.params(b).value(QStringLiteral("title")).toString(), QStringLiteral("Valor: {{resumo.output}} e {{resumo}}"));
        QCOMPARE(doc.edges()->items().at(1).from, QStringLiteral("resumo"));
    }

    void jsonRoundTrip()
    {
        FlowDocument doc;
        doc.setCatalogue(catalogue());
        doc.load({{QStringLiteral("id"), QStringLiteral("abc")}, {QStringLiteral("name"), QStringLiteral("Ida e volta")},
                  {QStringLiteral("revision"), 4}, {QStringLiteral("enabled"), false}});
        const QString t = doc.addNode(QStringLiteral("trigger.schedule"), 10.04, 20);
        const QString a = doc.addNode(QStringLiteral("action.system.notify"), 300, 0);
        doc.connectPorts(t, QStringLiteral("out"), a);
        doc.setParam(a, QStringLiteral("title"), QStringLiteral("Bom dia {{trigger.date}}"));
        const QJsonObject o = doc.toJsonObject();
        QCOMPARE(o.value(QStringLiteral("format")).toString(), QStringLiteral("lingmo-assistant-flow"));
        QCOMPARE(o.value(QStringLiteral("format_version")).toInt(), 1);
        QCOMPARE(o.value(QStringLiteral("revision")).toInt(), 4);
        QCOMPARE(o.value(QStringLiteral("enabled")).toBool(), false);
        QCOMPARE(o.value(QStringLiteral("nodes")).toArray().size(), 2);
        QCOMPARE(o.value(QStringLiteral("edges")).toArray().first().toObject().value(QStringLiteral("port")).toString(),
                 QStringLiteral("out"));

        FlowDocument copy;
        copy.setCatalogue(catalogue());
        QVERIFY(copy.loadJson(doc.toJson()));
        QCOMPARE(copy.toJsonObject(), o);
        QVERIFY(!copy.dirty());
        QVERIFY(!copy.loadJson(QStringLiteral("{\"format\":\"other\"}")));
        QVERIFY(!copy.loadJson(QStringLiteral("not json")));

        // saving keeps the edit history; the engine's revision wins
        copy.setName(QStringLiteral("Outro"));
        QVERIFY(copy.dirty());
        copy.markSaved({{QStringLiteral("id"), QStringLiteral("abc")}, {QStringLiteral("revision"), 5}});
        QVERIFY(!copy.dirty());
        QCOMPARE(copy.revision(), 5);
        QVERIFY(copy.canUndo());
    }

    void runStateAndIssues()
    {
        FlowDocument doc;
        doc.setCatalogue(catalogue());
        doc.load({{QStringLiteral("id"), QStringLiteral("f1")}});
        const QString t = doc.addNode(QStringLiteral("trigger.manual"), 0, 0);
        const QString a = doc.addNode(QStringLiteral("action.system.notify"), 300, 0);
        doc.connectPorts(t, QStringLiteral("out"), a);
        QSignalSpy spy(doc.nodes(), &QAbstractItemModel::dataChanged);
        doc.setNodeStatus(a, QStringLiteral("running"));
        QVERIFY(doc.edges()->items().first().active);
        doc.setNodeStatus(a, QStringLiteral("done"), QStringLiteral("ok"));
        const int row = doc.nodes()->indexOf(a);
        QCOMPARE(doc.nodes()->index(row).data(FlowNodeModel::OutputRole).toString(), QStringLiteral("ok"));
        doc.setIssues({QVariantMap{{QStringLiteral("node"), a}, {QStringLiteral("level"), QStringLiteral("warning")},
                                   {QStringLiteral("message"), QStringLiteral("w")}},
                       QVariantMap{{QStringLiteral("node"), a}, {QStringLiteral("level"), QStringLiteral("error")},
                                   {QStringLiteral("message"), QStringLiteral("e")}}});
        QCOMPARE(doc.nodes()->index(row).data(FlowNodeModel::IssueLevelRole).toString(), QStringLiteral("error"));
        doc.clearRunState();
        QVERIFY(doc.nodes()->index(row).data(FlowNodeModel::StatusRole).toString().isEmpty());
        QVERIFY(!doc.edges()->items().first().active);
        QVERIFY(spy.count() >= 3);
        // run state never makes the document dirty or adds undo steps
        doc.markSaved({});
        QVERIFY(!doc.dirty());
    }
};

QTEST_GUILESS_MAIN(TestFlowDocument)
#include "tst_flowdocument.moc"
