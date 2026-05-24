# H:\agent\vscode-dev-env.ps1
# 统一开发环境：Conda + Visual Studio Tools（PowerShell 版 - 修复版）

Write-Host "🚀 正在初始化开发环境..." -ForegroundColor Cyan

# ========================
# 1. 激活 conda 环境（通过 activate.bat）
# ========================
$condaRoot = "E:\anaconda"
$activateBat = "$condaRoot\Scripts\activate.bat"
$envName = "qwen-helper"

if (Test-Path $activateBat) {
    Write-Host "🔍 激活 Conda 环境: $envName" -ForegroundColor DarkGray
    $envOutput = cmd /c "`"$activateBat`" $envName && set"
    foreach ($line in $envOutput) {
        if ($line -match '^([^=]+)=(.*)$') {
            $name = $matches[1]
            $value = $matches[2]
            # 只设置关键环境变量（避免冲突）
            if ($name -in @("PATH", "CONDA_DEFAULT_ENV", "CONDA_PREFIX")) {
                [System.Environment]::SetEnvironmentVariable($name, $value, [System.EnvironmentVariableTarget]::Process)
                Set-Item "env:$name" $value
            }
        }
    }
    Write-Host "✅ Conda 环境 '$envName' 已激活" -ForegroundColor Green
} else {
    Write-Host "⚠️ 未找到 activate.bat，跳过 conda 激活" -ForegroundColor Yellow
}

# ========================
# 2. 加载 Visual Studio 2022 x64 工具链
# ========================
$vcvarsPaths = @(
    "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat",
    "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat",
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
)

$foundVcvars = $false
foreach ($vcvars in $vcvarsPaths) {
    if (Test-Path $vcvars) {
        Write-Host "🔍 找到 VS 工具链: $vcvars" -ForegroundColor DarkGray
        $envVars = cmd /c "`"$vcvars`" && set"
        foreach ($line in $envVars) {
            if ($line -match '^([^=]+)=(.*)$') {
                $name = $matches[1]
                $value = $matches[2]
                # 设置所有环境变量（包括 PATH）
                [System.Environment]::SetEnvironmentVariable($name, $value, [System.EnvironmentVariableTarget]::Process)
                Set-Item "env:$name" $value
            }
        }
        Write-Host "✅ Visual Studio 2022 x64 工具链已加载" -ForegroundColor Green
        $foundVcvars = $true
        break
    }
}

if (-not $foundVcvars) {
    Write-Host "⚠️ 未找到 vcvars64.bat，跳过 MSVC 加载" -ForegroundColor Yellow
}

# ========================
# 3. 验证当前 Python 环境
# ========================
try {
    $pythonPath = & python -c "import sys; print(sys.executable)" 2>$null
    if ($pythonPath -and ($pythonPath -like "*qwen-helper*")) {
        Write-Host "🐍 当前 Python: $pythonPath" -ForegroundColor Blue
    } else {
        Write-Host "⚠️ Python 未指向 qwen-helper 环境" -ForegroundColor Red
    }
} catch {
    Write-Host "⚠️ 无法检测 Python 路径" -ForegroundColor Red
}

Write-Host "✨ 开发环境准备就绪！" -ForegroundColor Magenta
Write-Host ""