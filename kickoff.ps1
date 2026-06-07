#!/usr/bin/env pwsh
#
# kickoff.ps1 — KickoffAI's one-button launcher for Windows (PowerShell 7+).
#
#   .\kickoff.ps1
#
# Sets up a virtualenv (first run only), checks Ollama, starts the audio
# tracker in the background, and launches the Streamlit dashboard. Ctrl+C
# (or closing the window) cleanly stops everything.

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$VenvDir     = '.venv'
$VenvPython  = Join-Path $VenvDir 'Scripts\python.exe'
$DataFile    = if ($env:KICKOFF_DATA_FILE) { $env:KICKOFF_DATA_FILE } else { 'match_data.json' }
$OllamaUrl   = if ($env:OLLAMA_URL)   { $env:OLLAMA_URL }   else { 'http://localhost:11434' }
$OllamaModel = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { 'llama3.2' }

function Write-Green ($m)  { Write-Host $m -ForegroundColor Green }
function Write-Yellow ($m) { Write-Host $m -ForegroundColor Yellow }
function Write-Red ($m)    { Write-Host $m -ForegroundColor Red }

# Locate the ollama executable (PATH first, then the default install location).
function Get-OllamaExe {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $local = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path $local) { return $local }
    return $null
}

function Test-OllamaUp {
    try { Invoke-RestMethod "$OllamaUrl/api/version" -TimeoutSec 3 | Out-Null; return $true }
    catch { return $false }
}

Write-Host '================================================================'
Write-Green '  KickoffAI - starting up'
Write-Host '================================================================'

# --------------------------------------------------------------------------- #
# 1. Python virtualenv + dependencies
# --------------------------------------------------------------------------- #
if (-not (Test-Path $VenvPython)) {
    Write-Yellow 'First run: creating virtualenv and installing dependencies...'
    # Prefer the py launcher pinned to 3.11; fall back to whatever python is on PATH.
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3.11 -m venv $VenvDir }
    else { python -m venv $VenvDir }
    & $VenvPython -m pip install --upgrade pip | Out-Null
    & $VenvPython -m pip install -r requirements.txt
}
Write-Green "OK Python environment ready ($(& $VenvPython --version))"

# --------------------------------------------------------------------------- #
# 2. Check Ollama
# --------------------------------------------------------------------------- #
$ollamaExe = Get-OllamaExe

if (Test-OllamaUp) {
    Write-Green "OK Ollama is running at $OllamaUrl"
} else {
    Write-Red "! Ollama is NOT reachable at $OllamaUrl."
    if ($ollamaExe) {
        Write-Yellow '  Attempting to start it...'
        Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden
        for ($i = 0; $i -lt 10 -and -not (Test-OllamaUp); $i++) { Start-Sleep -Seconds 1 }
        if (Test-OllamaUp) { Write-Green 'OK Ollama is now running' }
        else { Write-Red '  Still not reachable. Start the Ollama app manually.'
               Write-Yellow '  Continuing anyway - speech will be transcribed but not parsed.' }
    } else {
        Write-Red '  Ollama is not installed. Install with: winget install Ollama.Ollama'
        Write-Yellow '  Continuing anyway - speech will be transcribed but not parsed.'
    }
}

# Ensure the model is present.
if ((Test-OllamaUp) -and $ollamaExe) {
    $tags = try { Invoke-RestMethod "$OllamaUrl/api/tags" -TimeoutSec 5 } catch { $null }
    $haveModel = $tags -and ($tags.models.name -match [regex]::Escape($OllamaModel))
    if ($haveModel) {
        Write-Green "OK Model '$OllamaModel' is available"
    } else {
        Write-Yellow "! Model '$OllamaModel' not found. Pulling it now..."
        & $ollamaExe pull $OllamaModel
        if ($LASTEXITCODE -ne 0) { Write-Red "  Could not pull '$OllamaModel'. Parsing may fail." }
    }
}

# --------------------------------------------------------------------------- #
# 3. Start the audio tracker (background) + dashboard (foreground)
# --------------------------------------------------------------------------- #
$audioProc     = $null
$streamlitProc = $null

function Stop-Kickoff {
    Write-Host ''
    Write-Yellow 'Shutting down KickoffAI...'
    foreach ($p in @($streamlitProc, $audioProc)) {
        if ($p -and -not $p.HasExited) {
            try { $p.Kill($true) } catch {}
        }
    }
    Write-Green "Done. Match data saved to $DataFile"
}

try {
    $env:KICKOFF_DATA_FILE = $DataFile

    Write-Green 'Starting the audio tracker (The Ear + The Brain)...'
    $audioProc = Start-Process -FilePath $VenvPython -ArgumentList 'audio_tracker.py' `
        -NoNewWindow -PassThru
    Start-Sleep -Seconds 1
    if ($audioProc.HasExited) {
        Write-Red 'Audio tracker failed to start. Check the output above.'
        Write-Red 'Tip: make sure a microphone is connected and Windows mic'
        Write-Red 'privacy access is enabled (Settings > Privacy & security > Microphone).'
        return
    }
    Write-Green "OK Audio tracker running (PID $($audioProc.Id))"

    Write-Green 'Launching the dashboard in your browser...'
    Write-Host '----------------------------------------------------------------'
    Write-Yellow '  Speak your play-by-play into the mic.'
    Write-Yellow '  Press Ctrl+C here to stop everything.'
    Write-Host '----------------------------------------------------------------'

    $streamlit = Join-Path $VenvDir 'Scripts\streamlit.exe'
    $streamlitProc = Start-Process -FilePath $streamlit `
        -ArgumentList 'run', 'dashboard.py', '--server.headless', 'false', `
                      '--browser.gatherUsageStats', 'false' `
        -NoNewWindow -PassThru

    # Wait on streamlit; if it exits on its own (or Ctrl+C), fall through to cleanup.
    $streamlitProc.WaitForExit()
}
finally {
    Stop-Kickoff
}
