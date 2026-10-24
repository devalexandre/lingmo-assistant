/*
 * Copyright (C) 2026 LingmoOS Team.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * any later version.
 */

#include "screenimages.h"

QMutex ScreenImages::s_mutex;
QHash<QString, QImage> ScreenImages::s_images;

ScreenImages::ScreenImages()
    : QQuickImageProvider(QQuickImageProvider::Image)
{
}

void ScreenImages::set(const QString &conversationId, const QImage &image)
{
    QMutexLocker lock(&s_mutex);
    if (image.isNull())
        s_images.remove(conversationId);
    else
        s_images.insert(conversationId, image);
}

bool ScreenImages::contains(const QString &conversationId)
{
    QMutexLocker lock(&s_mutex);
    return s_images.contains(conversationId);
}

QImage ScreenImages::requestImage(const QString &id, QSize *size, const QSize &requestedSize)
{
    // "<conversation>?<serial>": the serial only makes QML reload
    const QString key = id.section(QLatin1Char('?'), 0, 0);
    QImage image;
    {
        QMutexLocker lock(&s_mutex);
        image = s_images.value(key);
    }
    if (size)
        *size = image.size();
    if (!image.isNull() && requestedSize.isValid() && !requestedSize.isEmpty()
        && (image.width() > requestedSize.width() || image.height() > requestedSize.height()))
        image = image.scaled(requestedSize, Qt::KeepAspectRatio, Qt::SmoothTransformation);
    return image;
}
