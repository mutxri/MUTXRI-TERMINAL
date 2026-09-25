REM Hidden launcher for the IndexNow submit.
REM
REM IndexNow notifies Bing, Yandex, Seznam and Naver (Bing also feeds Yahoo)
REM that the indexable URLs changed. It does not move Google - Search Console
REM does that - but it costs nothing and the earlier manual submit was the only
REM one ever run, because this was never registered as a task.
CreateObject("Wscript.Shell").Run "cmd /c cd /d D:\mutxri-terminal && python speed_index.py submit >> D:\mutxri-terminal\_indexnow_log.txt 2>&1", 0, False
