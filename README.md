# WinAutoTest — Suntek 部件连线检测工具

Windows 产线 GUI 工具，用于检查 SK1-27E（RK3576 / LP6 类）整机的 **LED 状态灯、补光灯、扬声器、麦克风、相机、扫码枪** 是否连线正确、工作正常。

LED 协议对齐 `LED-通讯指令 V6.5` 与现有 Android `servicertool`（`/dev/ttyS5` @ 9600，RGB 三字节）。

## 测试项

| 测试项 | 判定 | 说明 |
|--------|------|------|
| LED 红 / 绿 / 蓝 / 白 | 人工 | 串口发 RGB 指令点亮，灯保持到确认 |
| 补光灯点亮 | 人工 | HEX `4C 64 23` 开灯，确认后关闭 |
| 扬声器左 / 右声道 | 人工 | 循环播放 1 kHz，听音确认后停止 |
| 麦克风回环（左 / 右） | 自动 | 播 1 kHz 同时录音，RMS + SNR + 1 kHz 频谱判定 |
| 相机预览 | 人工 | 打开 AMCap，确认画面后关闭 |
| 扫码枪 | 自动 | 9600 串口收一帧（换行或 120ms 空闲），对齐 Android `ScannerSerialClient` |

## 环境

- Windows 10/11
- Python 3.10+（已在 3.13 验证）——仅开发 / 打包机需要；产线 U 盘包不需要装 Python
- 依赖：`pyserial`、`sounddevice`、`numpy`（tkinter 随 Python 自带）

开发机直接跑源码：

```bat
cd D:\WORK\SK1-27E\WinAutoTest
python -m pip install -r requirements.txt
python main.py
```

也可双击 `run.bat`。

跑单元测试：

```bat
python -m pip install pytest
python -m pytest tests -q
```

## U 盘一键运行（绿色免安装）

目标电脑不装 Python、不配环境。在**有 Python 的开发机**上打一次包：

```bat
build.bat
```

完成后得到文件夹 `dist\WinAutoTest\`，把**整个文件夹**拷到 U 盘（不要只拷 exe）：

```
WinAutoTest\
  WinAutoTest.exe      ← 双击即运行
  run.bat              ← 同样一键启动
  amcap+v3.0.9.exe
  _internal\           ← 自带的 Python 运行时与依赖，必须一起拷
  reports\             ← 首次导出报告后自动生成
```

产线电脑：插入 U 盘 → 打开该文件夹 → 双击 `WinAutoTest.exe` 或 `run.bat`。

报告写在 U 盘上程序旁的 `reports\`，不写系统盘。AMCap 优先用 exe 旁边那份，方便单独替换相机预览软件。

不要拷 `.venv`：虚拟环境绑死原机路径，换电脑会失效。

## 使用步骤

1. 用 USB 转串口把设备 LED 控制器接到电脑（Windows 上一般为 `COMx`）。扫码枪用另一路 COM（USB 扫码枪或设备扫码头）。
2. 启动工具，点 **刷新/探测**，选中 **LED 串口** 后点 **连接**。
   - 工具会发 `VERSION`，应答以 `FY` 开头即识别为 LED 控制器。
   - 部分固件不支持版本查询，可选择强行连接。
3. 在 **扫码串口** 下拉框另选扫码枪 COM（不要和 LED 用同一个口）。
4. 填写整机编号、操作员（可选）。
5. 确认录音 / 播放设备（默认系统设备即可）。
6. 右上角 **English / 中文** 可一键切换界面、弹窗、日志和报告语言。
7. 点 **全部测试**：
   - LED / 补光灯 / 扬声器 / 相机：灯、声音或预览画面保持到弹窗确认 → 是=PASS，否=FAIL。
   - 麦克风回环：自动判定（须检测到 1 kHz 测试音）。
   - 扫码枪：20 秒内扫任意码，串口收到一帧即 PASS；超时或打不开串口为 FAIL。
8. 导出 TXT 或 CSV 报告到 `reports/`。

未接 LED 串口时，点「全部测试」可选择继续跑音频、相机和扫码项，LED 项记为「跳过」。未选扫码串口时扫码项同样可跳过。含跳过项的报告总判定为「跳过」，不会给出 PASS。

## LED 协议摘要（V6.5）

- 波特率 **9600 8N1**
- 状态灯常亮：3 字节 RGB，如红 `FF 00 00`、关 `00 00 00`
- 状态灯闪烁：7 字节 `R G B 开灯(10ms) 关灯(10ms) 次数 结束状态`
- 补光灯：`4C <0-100> 23`，查询 `4C FF 23`
- 正确指令会回显所发字节

Windows 侧对应 Android 的 `/dev/ttyS5`，端口号由 USB 转串口驱动分配，请在界面里选择。

## 项目结构

```
WinAutoTest/
  main.py           GUI 入口
  app_paths.py      源码 / 打包后的资源与报告路径
  serial_led.py     LED 串口协议
  audio_test.py     扬声器 / 麦克风回环
  camera_test.py    启动 / 关闭 AMCap 相机预览
  scan_test.py      扫码枪串口（对齐 Android ScannerSerialClient）
  i18n.py           中/英文案
  amcap+v3.0.9.exe  相机预览软件
  report.py         测试报告 TXT/CSV
  requirements.txt
  WinAutoTest.spec  PyInstaller 绿色包配置
  build.bat         打 U 盘免安装包
  run.bat           开发启动；若旁有 WinAutoTest.exe 则直接启动
  tests/            单元测试
  reports/          导出目录（运行后生成）
```

## 注意事项

- 回环检测依赖扬声器声音能被麦克风拾到。产线请把整机麦克风靠近喇叭，或降低环境噪声。
- 阈值：录音 RMS ≥ 0.015（float32 量程）、SNR ≥ 6 dB、1 kHz 附近能量占比 ≥ 15%。可在 `audio_test.py` 调整。
- 单麦克风无法判定左右声道接反，接反需人工听音项确认。
- 测试进行中禁止断开串口。关闭窗口时会停播、关闭相机软件、关灯并断开串口。
- 开发也可双击 `run.bat` 启动；产线请用 `build.bat` 打出的绿色包。
