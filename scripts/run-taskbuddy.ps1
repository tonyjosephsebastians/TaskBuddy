param()

$ErrorActionPreference = 'Stop'

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$VenvDir = Join-Path $RepoRoot '.venv'
$RequirementsFile = Join-Path $RepoRoot 'requirements.txt'
$RequirementsHashFile = Join-Path $VenvDir '.requirements.sha256'
$AppUrl = 'http://localhost:8000'

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
    [hashtable]$PythonCandidate
  )

  if (Test-Path $VenvDir) {
    return
  }

  Write-Host "Creating virtual environment in $VenvDir"
  & $PythonCandidate.command @($PythonCandidate.args + @('-m', 'venv', $VenvDir))
}

function Get-RequirementsHash {
  (Get-FileHash -Algorithm SHA256 -Path $RequirementsFile).Hash
}

Push-Location $RepoRoot
try {
  $pythonCandidate = Get-PythonCandidate
  Ensure-Venv -PythonCandidate $pythonCandidate

  $venvPython = Join-Path $VenvDir 'Scripts\python.exe'
  $activateScript = Join-Path $VenvDir 'Scripts\Activate.ps1'

  if (-not (Test-Path $venvPython)) {
    throw "Virtual environment python executable was not found at $venvPython"
  }

  $requirementsHash = Get-RequirementsHash
  $storedHash = if (Test-Path $RequirementsHashFile) { (Get-Content $RequirementsHashFile -Raw).Trim() } else { '' }

  if ($requirementsHash -ne $storedHash) {
    Write-Host 'Installing Python dependencies from requirements.txt'
    & $venvPython -m pip install -r $RequirementsFile
    Set-Content -Path $RequirementsHashFile -Value $requirementsHash
  }

  . $activateScript

  Write-Host "Starting TaskBuddy at $AppUrl"
  python app.py
} finally {
  Pop-Location
}
