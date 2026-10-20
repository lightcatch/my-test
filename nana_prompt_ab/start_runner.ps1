# 直接运行（默认 8 小时、每 30 分钟一批；一轮 = 用户一句 + 奈奈一句 = 2 行）：
#   & D:\PyCode\test\nana_prompt_ab\start_runner.ps1
#   默认每批 2 组 × 2 段 × 4 轮 × 2 行 = 32 行
#
# 只运行一次（2 组 × 1 段 × 4 轮 × 2 行 = 16 行）：
#   & D:\PyCode\test\nana_prompt_ab\start_runner.ps1 -Once -LoopCount 1 -RoundsPerLoop 4
#
# 需要换模型、时长或对话轮数时才附加参数：
#   & D:\PyCode\test\nana_prompt_ab\start_runner.ps1 -Model doubao-seed-2-1-turbo-260628 -DurationHours 2
#   & D:\PyCode\test\nana_prompt_ab\start_runner.ps1 -Once -LoopCount 3 -RoundsPerLoop 6

param(
    [string]$Model = "",
    [string]$UserModel = "",
    [double]$DurationHours = 0,
    [double]$IntervalMinutes = 0,
    [int]$LoopCount = 0,
    [int]$RoundsPerLoop = 0,
    [switch]$Once
)

$ErrorActionPreference = "Stop"
$python = "D:\PyCode\test\.venv\Scripts\python.exe"
$runner = Join-Path $PSScriptRoot "runner.py"
$arguments = @($runner)
if ($DurationHours -gt 0) { $arguments += @("--duration-hours", $DurationHours) }
if ($IntervalMinutes -gt 0) { $arguments += @("--interval-minutes", $IntervalMinutes) }
if ($LoopCount -gt 0) { $arguments += @("--loop-count", $LoopCount) }
if ($RoundsPerLoop -gt 0) { $arguments += @("--rounds-per-loop", $RoundsPerLoop) }
if ($Model) { $arguments += @("--model", $Model) }
if ($UserModel) { $arguments += @("--user-model", $UserModel) }
if ($Once) { $arguments += "--once" }
& $python @arguments
exit $LASTEXITCODE
