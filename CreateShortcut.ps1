$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:USERPROFILE\Desktop\AMALYN TECH.lnk")
$Shortcut.TargetPath = "$PSScriptRoot\START AMALYN.bat"
$Shortcut.WorkingDirectory = $PSScriptRoot
$Shortcut.Description = "AMALYN TECH - AI Audio Intelligence"
$Shortcut.Save()
Write-Host "Shortcut created on Desktop"