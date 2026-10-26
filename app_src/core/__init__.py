"""Platform glue.

Everything in here talks to Android (or to the absence of Android). The rest
of the app goes through these helpers so that it stays importable on the
desktop, where there is no JVM and no ``jnius``.
"""
