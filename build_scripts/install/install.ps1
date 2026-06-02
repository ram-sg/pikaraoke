Param(
    [switch]$Confirm = $true,
    [switch]$Local = $false
)

$ErrorActionPreference = "Stop"

Write-Host "--- Biaoke Windows Installer ---" -ForegroundColor Cyan

# 1. Check for Winget
if (!(Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Error "Winget not found. Please ensure you are on a modern version of Windows 10 or 11."
    exit 1
}

# Determine packages to install
$installList = @("biaoke (via uv)")
$skipDeno = $false
if (Get-Command node -ErrorAction SilentlyContinue) {
    Write-Host "Node.js detected. Skipping Deno installation."
    $skipDeno = $true
}

if (!(Get-Command ffmpeg -ErrorAction SilentlyContinue)) { $installList += "ffmpeg" }
if (!$skipDeno -and !(Get-Command deno -ErrorAction SilentlyContinue)) { $installList += "deno" }

Write-Host "The following packages will be installed/updated: $($installList -join ', ')"
if ($Confirm) {
    $confirmation = Read-Host "Do you want to proceed? (y/n)"
    if ($confirmation -notmatch "^[Yy]$") {
        Write-Host "Installation cancelled."
        exit 1
    }
}

# 2. Install Dependencies via Winget
Write-Host "Installing Winget dependencies..." -ForegroundColor Yellow

# Install Visual C++ Redistributable (Required for gevent/greenlet)
Write-Host "Checking Visual C++ Redistributable..."
winget list -e --id "Microsoft.VCRedist.2015+.x64" --accept-source-agreements
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing Visual C++ Redistributable (x64)..."
    winget install --id "Microsoft.VCRedist.2015+.x64" -e --silent --accept-source-agreements --accept-package-agreements
} else {
    Write-Host "Visual C++ Redistributable is already installed."
}

# Install FFmpeg
if (!(Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "Installing ffmpeg..."
    winget install --id=Gyan.FFmpeg -e --silent --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw "Failed to install ffmpeg via winget" }
} else {
    Write-Host "ffmpeg is already installed."
}

# 3. Install Deno
if (!$skipDeno) {
    if (!(Get-Command deno -ErrorAction SilentlyContinue)) {
        Write-Host "Installing deno..."
        winget install --id=DenoLand.Deno -e --silent --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -ne 0) { throw "Failed to install deno via winget" }
    } else {
        Write-Host "deno is already installed."
    }
}

# 4. Install/Configure uv
if (!(Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..."
    # Attempt to install uv via irm
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    if ($LASTEXITCODE -ne 0) { throw "Failed to install uv" }

    # Reload Path for the current session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}
# 5. Install/Upgrade dependencies via uv
Write-Host "Checking for existing uv installations..." -ForegroundColor Yellow
$uvPackages = ""
$uvPackages = uv tool list | Out-String

# 6. install biaoke with uv
if ($uvPackages -match "biaoke") {
    Write-Host "Upgrading biaoke via uv..." -ForegroundColor Yellow
    if ($Local) {
        uv tool install --force .
    } else {
        uv tool upgrade biaoke
    }
} else {
    Write-Host "Installing biaoke via uv..." -ForegroundColor Yellow
    if ($Local) {
        uv tool install .
    } else {
        uv tool install biaoke
    }
}
if ($LASTEXITCODE -ne 0) { throw "Failed to install/upgrade biaoke via uv tool" }

# 7. Create Desktop Shortcut
Write-Host "Creating Desktop Shortcuts..." -ForegroundColor Yellow
try {
    $desktopPath = [System.Environment]::GetFolderPath("Desktop")
    if ([string]::IsNullOrWhiteSpace($desktopPath)) { throw "Could not resolve Desktop path" }
    # Robust path resolution for biaoke.exe
    $biaokeExe = ""
    $exePaths = @(
        (Get-Command biaoke -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        (Join-Path $env:LOCALAPPDATA "uv\bin\biaoke.exe"),
        (Join-Path $HOME ".local\bin\biaoke.exe") # uv also uses this on some setups
    )
    foreach ($p in $exePaths) { if ($p -and (Test-Path $p)) { $biaokeExe = $p; break } }

    if ($biaokeExe) {
        $WScriptShell = New-Object -ComObject WScript.Shell

        # Download Icon from GitHub once if needed
        $iconPath = Join-Path ([System.IO.Path]::GetDirectoryName($biaokeExe)) "logo.ico"
        $iconFound = $false
        try {
            $iconUrl = "https://raw.githubusercontent.com/vicwomg/biaoke/refs/heads/master/biaoke/static/icons/logo.ico"
            if (!(Test-Path $iconPath)) {
                Invoke-WebRequest -Uri $iconUrl -OutFile $iconPath -ErrorAction Stop
            }
            if (Test-Path $iconPath) { $iconFound = $true }
        } catch {
            Write-Host "Could not download icon from GitHub." -ForegroundColor Cyan
        }

        # Create multiple shortcuts
        $shortcutConfigs = @(
            @{ Name = "Biaoke"; Args = "" },
            @{ Name = "Biaoke (headless)"; Args = "--headless" }
        )

        foreach ($config in $shortcutConfigs) {
            $sName = $config.Name
            $shortcutPath = Join-Path $desktopPath "$sName.lnk"
            $shortcut = $WScriptShell.CreateShortcut($shortcutPath)
            $shortcut.TargetPath = $biaokeExe
            $shortcut.Arguments = $config.Args
            $shortcut.WorkingDirectory = [System.IO.Path]::GetDirectoryName($biaokeExe)
            if ($iconFound) {
                $shortcut.IconLocation = "$iconPath,0"
            }
            $shortcut.Save()
            Write-Host "Created shortcut: $sName" -ForegroundColor Green
        }
    } else {
        Write-Host "Could not find biaoke.exe to create shortcuts." -ForegroundColor Red
    }
} catch {
    Write-Host "Failed to create desktop shortcuts: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n--------------------------------------------------------" -ForegroundColor Green
Write-Host "Installation complete!" -ForegroundColor Green
Write-Host "Please restart your terminal (PowerShell) to ensure all PATH changes are loaded."
Write-Host "Then, simply run: `biaoke` or launch Biaoke from the desktop shortcuts."
Write-Host "`nTIP: Put your karaoke files in: $(Join-Path $HOME 'biaoke-songs')" -ForegroundColor Cyan
Write-Host "--------------------------------------------------------"
