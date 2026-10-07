// Parses Notes pages with Lingmo Notes' own markdown.cpp and prints JSON, so
// the Python port can be checked against the real parser.
//   harness parse <file.md>...   -> one JSON object per file
//   harness now                  -> serializePage of a page dated now
#include "markdown.h"

#include <QCoreApplication>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTextStream>

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    const QStringList args = app.arguments();
    QTextStream out(stdout);
    if (args.size() >= 2 && args.at(1) == QLatin1String("now")) {
        Notes::PageMeta meta;
        meta.id = QStringLiteral("00000000-0000-4000-8000-000000000000");
        meta.title = QStringLiteral("x");
        meta.created = meta.updated = QDateTime::currentDateTime();
        out << Notes::serializePage(meta, QString());
        return 0;
    }
    for (int i = 2; i < args.size(); ++i) {
        QFile f(args.at(i));
        if (!f.open(QIODevice::ReadOnly))
            return 2;
        const Notes::PageFile page = Notes::parsePage(QString::fromUtf8(f.readAll()));
        QJsonArray blocks;
        for (const Notes::Block &b : Notes::parseBlocks(page.body)) {
            blocks.append(QJsonObject{{"type", b.type}, {"text", b.text}, {"indent", b.indent},
                                      {"checked", b.checked}, {"collapsed", b.collapsed},
                                      {"emoji", b.emoji}, {"language", b.language}, {"ref", b.ref}});
        }
        QJsonObject o{{"hasFrontmatter", page.hasFrontmatter}, {"id", page.meta.id},
                      {"parent", page.meta.parent}, {"icon", page.meta.icon}, {"title", page.meta.title},
                      {"favorite", page.meta.favorite}, {"order", page.meta.order},
                      {"created", page.meta.created.toString(Qt::ISODate)},
                      {"updated", page.meta.updated.toString(Qt::ISODate)},
                      {"createdValid", page.meta.created.isValid()},
                      {"body", page.body}, {"blocks", blocks},
                      {"reserialized", Notes::serializeBlocks(Notes::parseBlocks(page.body))}};
        out << QJsonDocument(o).toJson(QJsonDocument::Compact) << "\n";
    }
    return 0;
}
