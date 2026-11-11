# Called before Compose can replace a legacy node container. Never print identity data.
function Preserve-NodeIdentities {
    foreach ($node in @(@{Service='cluster'; Volume='control-identity'}, @{Service='worker'; Volume='worker-identity'})) {
        $container = docker compose ps -a -q $node.Service
        if ($LASTEXITCODE -ne 0) { throw 'Could not inspect existing lab containers.' }
        if (-not $container) { continue }
        $details = docker inspect $container | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the existing node.' }
        if ($details[0].Mounts | Where-Object Destination -eq '/etc/rancher/node') { continue }
        $project = $details[0].Config.Labels.'com.docker.compose.project'
        if (-not $project) { throw 'Existing node has no Compose project identity.' }
        $volume = $project + '_' + $node.Volume
        $helper = $project + '-identity-migration-' + [guid]::NewGuid().ToString('N')
        $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        $temporary = [IO.Path]::GetFullPath((Join-Path $tempRoot ('flightdeck-identity-' + [guid]::NewGuid().ToString('N'))))
        if (-not $temporary.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid temporary directory.' }
        New-Item -ItemType Directory -Path $temporary | Out-Null
        $helperCreated = $false
        try {
            Write-Host ('Preserving the existing ' + $node.Service + ' identity...')
            docker cp ($container + ':/etc/rancher/node') (Join-Path $temporary 'node')
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $temporary 'node/password'))) {
                throw 'Existing node identity could not be copied. No lab containers were recreated.'
            }
            docker volume create --label "com.docker.compose.project=$project" --label ('com.docker.compose.volume=' + $node.Volume) $volume | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Could not create the persistent identity volume.' }
            $copy = 'set -eu; if [ -s /target/password ] && ! cmp -s /incoming/password /target/password; then echo Existing identity volume differs. No identity was overwritten. >&2; exit 1; fi; cp -a /incoming/. /target/; test -s /target/password'
            docker create --name $helper --network none --mount "type=volume,source=$volume,target=/target" --entrypoint sh $details[0].Config.Image -c $copy | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Could not create the identity migration helper.' }
            $helperCreated = $true
            docker cp (Join-Path $temporary 'node') ($helper + ':/incoming')
            if ($LASTEXITCODE -ne 0) { throw 'Could not transfer the existing identity.' }
            docker start -a $helper
            if ($LASTEXITCODE -ne 0) { throw 'Identity migration failed. No lab containers were recreated.' }
            $helperExit = docker inspect --format '{{.State.ExitCode}}' $helper
            if ($helperExit -ne '0') { throw 'Identity migration failed. No lab containers were recreated.' }
        } finally {
            if ($helperCreated) { docker rm -f -v $helper | Out-Null }
            # Only the unique temporary directory created above is removed.
            if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
        }
    }
}
