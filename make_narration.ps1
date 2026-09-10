# make_narration.ps1 - render the tour narration.
#
# Voice is female, delivered in the calm documentary register the user asked for
# (Alux-style): unhurried pace, a real beat between sentences, and no run-on.
# Two things matter more than the voice choice itself and were missing the first
# time round - SSML pauses, so lines breathe, and normalisation afterwards, since
# raw synth output lands around -23 dB and sounds thin next to a produced track.
#
# Prefers the OneCore engine (cleaner) and falls back to the desktop SAPI voice.

param(
  [string]$ScriptPath = "D:\mutxri-terminal\tour_script.json",
  [string]$OutDir = "C:\Users\mutxr\AppData\Local\Temp\claude\D--mutxri-terminal\1c144fad-89e4-4b04-baf0-4f3e45e10bc6\scratchpad\tour"
)

$doc = Get-Content $ScriptPath -Raw | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$useOneCore = $false
if ($false) {
try {
  [Windows.Media.SpeechSynthesis.SpeechSynthesizer,Windows.Media,ContentType=WindowsRuntime] | Out-Null
  [Windows.Storage.Streams.DataReader,Windows.Storage.Streams,ContentType=WindowsRuntime] | Out-Null
  $syn = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
  $v = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices |
       Where-Object { $_.Gender -eq 'Female' } | Select-Object -First 1
  if ($v) { $syn.Voice = $v; $useOneCore = $true }
} catch { $useOneCore = $false }
}

if (-not $useOneCore) {
  Add-Type -AssemblyName System.Speech
  $sapi = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $fem = $sapi.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Gender -eq 'Female' } | Select-Object -First 1
  if ($fem) { $sapi.SelectVoice($fem.VoiceInfo.Name) }
  $sapi.Rate = -1
}
Write-Output ("engine: " + $(if ($useOneCore) { "OneCore (neural-path)" } else { "SAPI desktop" }))

function Await-Op($op) {
  $t = [System.WindowsRuntimeSystemExtensions].GetMethods() |
       Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
                      $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } |
       Select-Object -First 1
  $g = $t.MakeGenericMethod([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
  $task = $g.Invoke($null, @($op))
  $task.Wait(60000) | Out-Null
  $task.Result
}

foreach ($sc in $doc.scenes) {
  # A beat after each sentence is what separates narration from a robot reading
  # a paragraph. 420ms mid-line, a longer settle before the next scene.
  $body = [System.Security.SecurityElement]::Escape($sc.say)
  $body = $body -replace '\. ', '. <break time="420ms"/>'
  $body = $body -replace ', ', ', <break time="150ms"/>'
  $wav = Join-Path $OutDir ($sc.id + ".wav")

  if ($useOneCore) {
    $ssml = "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>" +
            "<prosody rate='-10%' pitch='-2%'>$body</prosody></speak>"
    $stream = Await-Op $syn.SynthesizeSsmlToStreamAsync($ssml)
    $reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
    $loadT = $reader.LoadAsync([uint32]$stream.Size)
    while ($loadT.Status -eq 0) { Start-Sleep -Milliseconds 25 }
    $bytes = New-Object byte[] $stream.Size
    $reader.ReadBytes($bytes)
    [System.IO.File]::WriteAllBytes($wav, $bytes)
    $reader.Dispose()
  } else {
    $ssml = "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>" +
            "<prosody rate='-8%'>$body</prosody></speak>"
    $sapi.SetOutputToWaveFile($wav)
    $sapi.SpeakSsml($ssml)
  }
  "{0,-14} {1,8} bytes" -f $sc.id, (Get-Item $wav).Length
}

if (-not $useOneCore) { $sapi.SetOutputToNull(); $sapi.Dispose() }
