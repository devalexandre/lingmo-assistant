/*
 * Copyright (C) 2026 LingmoOS Team.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * any later version.
 */

#pragma once

#include <QHash>
#include <QImage>
#include <QMutex>
#include <QQuickImageProvider>

// Pictures of the screen handed over by "Ask about the screen"
// (lingmo-screenshot), shown in the chat as image://screen/<conversation>.
// Memory only: never written to disk, gone when the app quits.
class ScreenImages : public QQuickImageProvider
{
public:
    ScreenImages();

    static void set(const QString &conversationId, const QImage &image);
    static bool contains(const QString &conversationId);

    QImage requestImage(const QString &id, QSize *size, const QSize &requestedSize) override;

private:
    static QMutex s_mutex;
    static QHash<QString, QImage> s_images;
};
