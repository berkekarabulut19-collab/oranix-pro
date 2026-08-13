$ErrorActionPreference = 'Stop'

Write-Host '1/3 Python regresyon testleri'
python -m unittest discover -p 'test_*.py'
if ($LASTEXITCODE -ne 0) { throw 'Python testleri başarısız.' }

Write-Host '2/3 Sözdizimi ve modül kontrolleri'
python -m py_compile app.py data_fetcher.py data_manager.py predictor_engine.py predictor_candidate.py prediction_store.py upgrade_guard.py external_data.py model_lab.py
if ($LASTEXITCODE -ne 0) { throw 'Python modül kontrolü başarısız.' }
node --check ui\app.js
if ($LASTEXITCODE -ne 0) { throw 'Arayüz kontrolü başarısız.' }

Write-Host '3/3 Paket kaynak sözleşmesi'
$required = @(
    'ui\index.html', 'ui\styles.css', 'ui\app.js',
    'app.py', 'data_fetcher.py', 'predictor_engine.py',
    'predictor_candidate.py', 'upgrade_guard.py', 'external_data.py', 'model_lab.py'
)
$missing = $required | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missing) { throw "Eksik paket dosyaları: $($missing -join ', ')" }

Write-Host 'RELEASE GATE: BAŞARILI'
