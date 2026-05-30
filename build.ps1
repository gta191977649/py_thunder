param(
    [ValidateSet("portable", "onefile", "both")]
    [string]$Mode = "portable",
    [switch]$Clean,
    [switch]$AllowMissingAria2
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $root "scripts\build_release.py"

$args = @($script, "--mode", $Mode)
if ($Clean) {
    $args += "--clean"
}
if ($AllowMissingAria2) {
    $args += "--allow-missing-aria2"
}

python @args
exit $LASTEXITCODE
