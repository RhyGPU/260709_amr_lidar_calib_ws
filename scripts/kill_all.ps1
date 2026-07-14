# Kill ALL AMR LiDAR background processes: the raw-MS3 emitter, the subscriber,
# the relay (server/client), and the calibration app (app.py). Matches on the
# process command line so unrelated Python on this machine is left alone.
#
# Run via kill_all.bat (double-click) or:  powershell -File kill_all.ps1

$patterns = @(
    'amr_lidar.ms3_emitter',
    'amr_lidar.ms3_subscriber',
    'amr_lidar.relay_server',
    'amr_lidar.relay_client',
    'lidar_2d_calibration',
    'app.py'
)

$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object {
        $cl = $_.CommandLine
        if (-not $cl) { return $false }
        foreach ($p in $patterns) { if ($cl -like "*$p*") { return $true } }
        return $false
    }

if ($procs) {
    foreach ($pr in $procs) {
        Write-Host ("killing PID {0} : {1}" -f $pr.ProcessId, $pr.CommandLine)
        # WMI Terminate first: it reaps wedged/orphaned instances that
        # Stop-Process / taskkill report success on but fail to actually kill
        # (e.g. a GUI process whose launcher is gone but still holds the UDP
        # ports). Fall back to Stop-Process if WMI is unavailable.
        $r = Invoke-CimMethod -InputObject $pr -MethodName Terminate -ErrorAction SilentlyContinue
        if ($null -eq $r -or $r.ReturnValue -ne 0) {
            try { Stop-Process -Id $pr.ProcessId -Force -ErrorAction Stop }
            catch { Write-Host "  (could not terminate - may need a reboot)" }
        }
    }
    Start-Sleep -Milliseconds 400
    Write-Host ("Done. {0} process(es) targeted." -f @($procs).Count)
} else {
    Write-Host "Nothing to kill - no AMR LiDAR / calibration python processes running."
}
