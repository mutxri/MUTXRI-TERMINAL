REM Hidden launcher for the late refresh.
REM
REM NGX publishes its official end-of-day price list in the evening, after the
REM 21:00 refresh has already run, so that run finds 0 days for Lagos and NGX
REM stays a day behind until the midnight run. This pass runs at 22:00 (19:00
REM Lagos) and the chain's own eod due-check collects the missing session.
REM Non-history mode on purpose: it runs the collectors only when a published
REM session is actually missing, instead of re-fetching everything every day.
CreateObject("Wscript.Shell").Run "cmd /c cd /d D:\mutxri-terminal && python refresh_all.py >> D:\mutxri-terminal\_refresh_log.txt 2>&1", 0, False
