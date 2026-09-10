try { Invoke-WebRequest -Uri 'https://mutxri-terminal.onrender.com/api/health' -UseBasicParsing -TimeoutSec 30 | Out-Null } catch {}
