# install/install_ibmcloud_cli.ps1
#
# Installs the IBM Cloud CLI on Windows, then optionally installs
# the plugins used by the IBM Cloud ToolKit.
# Requires: PowerShell 5.1+, internet access

$ErrorActionPreference = "Stop"

$Plugins = @(
    "cloud-databases",
    "vpc-infrastructure",
    "schematic",
    "schematics",
    "cloud-object-storage",
    "container-registry",
    "ks",
    "sl",
    "code-engine"
)

function Test-CommandExists {
    param([string]$Command)
    $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

function Install-IBMCloudCLI {
    $InstallerUrl = "https://download.clis.cloud.ibm.com/ibm-cloud-cli/latest/IBM_Cloud_CLI_latest_windows_amd64.exe"
    $InstallerPath = "$env:TEMP\IBMCloudCLI_installer.exe"

    Write-Host "Downloading IBM Cloud CLI installer..."
    Invoke-WebRequest -Uri $InstallerUrl -OutFile $InstallerPath -UseBasicParsing

    Write-Host "Running installer (silent install)..."
    Start-Process -FilePath $InstallerPath -ArgumentList "/S" -Wait
    Remove-Item $InstallerPath -Force -ErrorAction SilentlyContinue

    # Refresh PATH in current session
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH", "User")
    Write-Host "IBM Cloud CLI installed successfully."
}

function Install-Plugins {
    Write-Host ""
    Write-Host "Installing IBM Cloud CLI plugins..."
    foreach ($Plugin in $Plugins) {
        Write-Host "  Installing plugin: $Plugin"
        try {
            ibmcloud plugin install $Plugin -f 2>&1 | Out-Null
            Write-Host "    OK"
        } catch {
            Write-Warning "  Failed to install plugin '$Plugin': $_"
        }
    }
    Write-Host "Plugin installation complete."
}

# ── Main ──────────────────────────────────────────────────────────────────────

Write-Host "IBM Cloud CLI Installer"
Write-Host "========================"
Write-Host ""

$InstallCLI = Read-Host "Install / verify IBM Cloud CLI? (y/n)"
if ($InstallCLI -match "^[yY]$") {
    if (Test-CommandExists "ibmcloud") {
        $Version = & ibmcloud version 2>$null | Select-Object -First 1
        Write-Host "IBM Cloud CLI is already installed: $Version"
    } else {
        Write-Host "IBM Cloud CLI not found. Installing..."
        Install-IBMCloudCLI
    }
}

Write-Host ""
$InstallPlugins = Read-Host "Install IBM Cloud CLI plugins for the toolkit? (y/n)"
if ($InstallPlugins -match "^[yY]$") {
    Install-Plugins
}

Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Log in:       ibmcloud login"
Write-Host "  2. Run toolkit:  python python\ibm_cloud_enum.py"
Write-Host ""
Write-Host "For more info, see: https://cloud.ibm.com/docs/cli"
Write-Host "Completed."
