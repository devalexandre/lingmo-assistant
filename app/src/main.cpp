/*
 * Copyright (C) 2026 LingmoOS Team.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * any later version.
 */

#include <QCommandLineParser>
#include <QDBusConnection>
#include <QDBusInterface>
#include <QGuiApplication>
#include <QIcon>
#include <QLocale>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>
#include <QSettings>
#include <QStandardPaths>
#include <QTranslator>

#include "assistant.h"

static const QString DBusService = QStringLiteral("com.lingmo.Assistant");
static const QString DBusPath = QStringLiteral("/Assistant");

// Same as Spotlight: the platform theme doesn't always hand the icon theme to
// QGuiApplication processes, so use the one set in Lingmo Settings.
static void applyIconTheme()
{
    const QString current = QIcon::themeName();
    if (!current.isEmpty() && current != QLatin1String("hicolor"))
        return;
    QSettings theme(QStringLiteral("lingmoos"), QStringLiteral("theme"));
    const bool dark = theme.value(QStringLiteral("DarkMode"), false).toBool();
    const QStringList candidates = {
        theme.value(dark ? QStringLiteral("DarkIconTheme") : QStringLiteral("IconTheme")).toString(),
        dark ? QStringLiteral("Crule-dark") : QStringLiteral("Crule"),
        QStringLiteral("breeze"),
    };
    for (const QString &name : candidates) {
        if (!name.isEmpty()
            && !QStandardPaths::locate(QStandardPaths::GenericDataLocation,
                                       QStringLiteral("icons/%1/index.theme").arg(name)).isEmpty()) {
            QIcon::setThemeName(name);
            break;
        }
    }
    QIcon::setFallbackThemeName(QStringLiteral("hicolor"));
}

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    app.setOrganizationName(QStringLiteral("lingmoos"));
    app.setApplicationName(QStringLiteral("lingmo-assistant"));
    app.setDesktopFileName(QStringLiteral("lingmo-assistant"));

    QCommandLineParser parser;
    parser.addHelpOption();
    QCommandLineOption openOption(QStringLiteral("open"), QStringLiteral("Open a conversation"), QStringLiteral("id"));
    QCommandLineOption askOption(QStringLiteral("ask"), QStringLiteral("Ask a question in a new conversation"),
                                 QStringLiteral("text"));
    parser.addOption(openOption);
    parser.addOption(askOption);
    parser.process(app);

    QTranslator translator;
    const QString translations = qEnvironmentVariable("LINGMO_ASSISTANT_TRANSLATIONS", QStringLiteral(TRANSLATIONS_DIR));
    if (translator.load(QLocale(), QStringLiteral("lingmo-assistant"), QStringLiteral("_"), translations))
        app.installTranslator(&translator);

    // One instance: a second launch hands its request over and exits
    QDBusConnection bus = QDBusConnection::sessionBus();
    if (bus.isConnected() && !bus.registerService(DBusService)) {
        QDBusInterface iface(DBusService, DBusPath, DBusService, bus);
        if (parser.isSet(openOption))
            iface.call(QStringLiteral("open"), parser.value(openOption));
        else if (parser.isSet(askOption))
            iface.call(QStringLiteral("ask"), parser.value(askOption));
        else
            iface.call(QStringLiteral("open"), QString());
        return 0;
    }
    applyIconTheme();
    app.setWindowIcon(QIcon::fromTheme(QStringLiteral("internet-chat")));

    Assistant assistant;
    bus.registerObject(DBusPath, &assistant, QDBusConnection::ExportAllSlots);

    QQmlApplicationEngine qml;
    qml.rootContext()->setContextProperty(QStringLiteral("assistant"), &assistant);
    qml.load(QUrl(QStringLiteral("qrc:/qml/Main.qml")));
    if (qml.rootObjects().isEmpty())
        return 1;

    auto *window = qobject_cast<QQuickWindow *>(qml.rootObjects().first());
    QObject::connect(&assistant, &Assistant::raiseRequested, window, [window] {
        window->show();
        window->raise();
        window->requestActivate();
    });

    if (parser.isSet(openOption))
        assistant.open(parser.value(openOption));
    else if (parser.isSet(askOption))
        assistant.ask(parser.value(askOption));

    return app.exec();
}
