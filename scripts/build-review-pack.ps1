param(
  [string]$AppUrl,
  [switch]$StartApp,
  [switch]$SkipVideo
)

$ErrorActionPreference = 'Stop'

if ($StartApp -and $PSBoundParameters.ContainsKey('AppUrl')) {
  throw 'Use either -StartApp or -AppUrl, not both.'
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$AppVenvDir = Join-Path $RepoRoot '.venv'
$ReviewVenvDir = Join-Path $RepoRoot '.review-pack-venv'
$AppRequirementsFile = Join-Path $RepoRoot 'requirements.txt'
$ReviewRequirementsFile = Join-Path $RepoRoot 'requirements-review-pack.txt'
$AppRequirementsHashFile = Join-Path $AppVenvDir '.requirements.sha256'
$ReviewRequirementsHashFile = Join-Path $ReviewVenvDir '.requirements.sha256'
$DefaultAppUrl = 'http://localhost:8000'
$IsolatedAppUrl = 'http://127.0.0.1:8010'

function Get-PythonCandidate {
  $candidates = @(
    @{ command = 'py'; args = @('-3.12') },
    @{ command = 'py'; args = @('-3') },
    @{ command = 'python3.12'; args = @() },
    @{ command = 'python3'; args = @() },
    @{ command = 'python'; args = @() }
  )

  foreach ($candidate in $candidates) {
    try {
      & $candidate.command @($candidate.args + '--version') *> $null
      if ($LASTEXITCODE -eq 0) {
        return $candidate
      }
    } catch {
    }
  }

  throw 'Python 3.12 or a compatible Python interpreter was not found on PATH.'
}

function Ensure-Venv {
  param(
    [hashtable]$PythonCandidate,
    [string]$VenvDir
  )

  if (Test-Path $VenvDir) {
    return
  }

  Write-Host "Creating virtual environment in $VenvDir"
  & $PythonCandidate.command @($PythonCandidate.args + @('-m', 'venv', $VenvDir))
}

function Resolve-VenvPython {
  param([string]$VenvDir)

  $candidates = @(
    (Join-Path $VenvDir 'Scripts\python.exe'),
    (Join-Path $VenvDir 'bin/python')
  )

  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }

  throw "Virtual environment python executable was not found in $VenvDir"
}

function Get-RequirementsHash {
  param([string[]]$RequirementFiles)

  $hashLines = foreach ($file in $RequirementFiles) {
    (Get-FileHash -Algorithm SHA256 -Path $file).Hash
  }
  $combined = [System.Text.Encoding]::UTF8.GetBytes(($hashLines -join "`n"))
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    return ([System.BitConverter]::ToString($sha.ComputeHash($combined))).Replace('-', '')
  } finally {
    $sha.Dispose()
  }
}

function Ensure-Requirements {
  param(
    [string]$VenvPython,
    [string[]]$RequirementFiles,
    [string]$RequirementsHashFile,
    [string]$Label
  )

  $currentHash = Get-RequirementsHash -RequirementFiles $RequirementFiles
  $storedHash = if (Test-Path $RequirementsHashFile) { (Get-Content $RequirementsHashFile -Raw).Trim() } else { '' }

  if ($currentHash -eq $storedHash) {
    return
  }

  Write-Host "Installing $Label Python dependencies"
  $arguments = @('-m', 'pip', 'install')
  foreach ($file in $RequirementFiles) {
    $arguments += @('-r', $file)
  }
  & $VenvPython @arguments
  Set-Content -Path $RequirementsHashFile -Value $currentHash
}

function Wait-ForHealth {
  param(
    [string]$HealthUrl,
    [int]$TimeoutSeconds = 40,
    [System.Diagnostics.Process]$Process = $null
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if ($Process -and $Process.HasExited) {
      $stderr = $Process.StandardError.ReadToEnd()
      if ([string]::IsNullOrWhiteSpace($stderr)) {
        throw "The temporary TaskBuddy app exited before becoming healthy."
      }
      throw "The temporary TaskBuddy app exited before becoming healthy. $stderr"
    }

    try {
      $response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2
      if ($response.StatusCode -eq 200) {
        return
      }
    } catch {
    }

    Start-Sleep -Seconds 1
  }

  throw "TaskBuddy did not become ready at $HealthUrl within the timeout window."
}

function Start-IsolatedReviewApp {
  param([string]$AppPython)

  $reviewDbPath = Join-Path $RepoRoot 'docs\review-pack\taskbuddy-runtime.db'
  if (Test-Path $reviewDbPath) {
    Remove-Item $reviewDbPath -Force
  }

  $startInfo = New-Object System.Diagnostics.ProcessStartInfo
  $startInfo.FileName = $AppPython
  $startInfo.Arguments = 'app.py'
  $startInfo.WorkingDirectory = $RepoRoot
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true
  $startInfo.Environment['TASKBUDDY_DEMO_PACING'] = '0'
  $startInfo.Environment['TASKBUDDY_STREAM_STEP_DELAY_MS'] = '0'
  $startInfo.Environment['TASKBUDDY_RETRY_BACKOFF_MS'] = '0'
  $startInfo.Environment['TASKBUDDY_DATABASE_PATH'] = $reviewDbPath
  $startInfo.Environment['TASKBUDDY_PORT'] = '8010'
  $startInfo.Environment['TASKBUDDY_HOST'] = '127.0.0.1'

  $process = New-Object System.Diagnostics.Process
  $process.StartInfo = $startInfo
  $process.Start() | Out-Null

  Wait-ForHealth -HealthUrl "$IsolatedAppUrl/health" -Process $process
  return @{
    Process = $process
    AppUrl = $IsolatedAppUrl
    ReviewDbPath = $reviewDbPath
  }
}

Push-Location $RepoRoot
try {
  $pythonCandidate = Get-PythonCandidate
  $startedApp = $null

  if ($StartApp) {
    Ensure-Venv -PythonCandidate $pythonCandidate -VenvDir $AppVenvDir
    $appPython = Resolve-VenvPython -VenvDir $AppVenvDir
    Ensure-Requirements -VenvPython $appPython -RequirementFiles @($AppRequirementsFile) -RequirementsHashFile $AppRequirementsHashFile -Label 'app runtime'
    $startedApp = Start-IsolatedReviewApp -AppPython $appPython
    $resolvedAppUrl = $startedApp.AppUrl
  } elseif ($PSBoundParameters.ContainsKey('AppUrl')) {
    $resolvedAppUrl = $AppUrl.TrimEnd('/')
  } else {
    $resolvedAppUrl = $DefaultAppUrl
  }

  Ensure-Venv -PythonCandidate $pythonCandidate -VenvDir $ReviewVenvDir
  $reviewPython = Resolve-VenvPython -VenvDir $ReviewVenvDir
  Ensure-Requirements -VenvPython $reviewPython -RequirementFiles @($ReviewRequirementsFile) -RequirementsHashFile $ReviewRequirementsHashFile -Label 'documentation pack'

  Write-Host 'Ensuring Playwright Chromium is installed in .review-pack-venv'
  & $reviewPython -m playwright install chromium

  Write-Host "Generating TaskBuddy documentation pack from $resolvedAppUrl"
  $generatorArgs = @('scripts\generate_review_pack.py', '--app-url', $resolvedAppUrl)
  if ($SkipVideo) {
    $generatorArgs += '--skip-video'
  }
  & $reviewPython @generatorArgs
} finally {
  if ($startedApp) {
    if (-not $startedApp.Process.HasExited) {
      $startedApp.Process.Kill()
      $startedApp.Process.WaitForExit()
    }
    if (Test-Path $startedApp.ReviewDbPath) {
      Remove-Item $startedApp.ReviewDbPath -Force
    }
  }
  Pop-Location
}
