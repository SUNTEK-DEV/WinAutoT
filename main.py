"""WinAutoTest - Windows 部件连线检测工具（LED / 扬声器 / 麦克风 / 相机）。

测试项：
- LED 状态灯：红/绿/蓝/白 逐色点亮，人工目视确认连线与颜色正确
- 补光灯：点亮/熄灭，人工确认
- 扬声器：左右声道分别播放测试音，人工听音确认 + 可选麦克风回环自动检测
- 麦克风：录音能量自动检测
- 相机：打开 AMCap 预览软件，人工确认画面

运行：python main.py
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import audio_test
import camera_test
import report as rpt
import serial_led

APP_TITLE = "WinAutoTest - 部件连线检测工具"
PASSED = rpt.PASSED
FAILED = rpt.FAILED
PENDING = rpt.PENDING


class TestRunner:
    """后台线程执行测试，通过 queue 向 GUI 线程投递事件。"""

    def __init__(self, ui_queue: queue.Queue):
        self.ui_queue = ui_queue
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._manual_done = threading.Event()
        self._manual_verdict: str | None = None

    def start(self, target, *args) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._manual_done = threading.Event()
        self._manual_verdict: str | None = None
        self._thread = threading.Thread(
            target=self._wrap, args=(target,) + args, daemon=True)
        self._thread.start()

    def wait_manual(self, timeout: float | None = None) -> str | None:
        """阻塞直到 GUI 线程给出人工判定，或被 stop。

        调用方须先 clear _manual_done，再 emit await_manual，再调用本方法，
        避免 GUI 比 wait 先 resolve 导致丢判定。
        """
        while not self._stop_event.is_set():
            if self._manual_done.wait(timeout=0.2):
                return self._manual_verdict
            if timeout is not None:
                timeout -= 0.2
                if timeout <= 0:
                    return None
        return None

    def resolve_manual(self, verdict: str) -> None:
        self._manual_verdict = verdict
        self._manual_done.set()

    def _wrap(self, target, *args) -> None:
        try:
            target(*args)
        except Exception as exc:  # 后台线程兜底，防止静默死亡
            self.emit("error", f"{type(exc).__name__}: {exc}")

    def stop(self) -> None:
        self._stop_event.set()
        self._manual_done.set()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def emit(self, kind: str, payload=None) -> None:
        self.ui_queue.put((kind, payload))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("880x680")
        self.minsize(760, 560)

        self.report = rpt.TestReport()
        self.ui_queue: queue.Queue = queue.Queue()
        self.runner = TestRunner(self.ui_queue)
        self.led: serial_led.LedController | None = None
        self.led_connected = False
        self.audio_in_dev: int | None = None
        self.audio_out_dev: int | None = None
        self._awaiting_item: str | None = None
        self._cached_input: int | None = None
        self._cached_output: int | None = None
        self._port_list: list[serial_led.LedPort] = []

        self._build_ui()
        self._register_test_items()
        self.after(100, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._log("工具已启动。请先连接 LED 串口，再开始测试。")

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        # 顶部：整机信息 + 串口连接
        top = ttk.LabelFrame(self, text="整机信息 / LED 串口")
        top.pack(fill="x", padx=8, pady=(8, 4))

        ttk.Label(top, text="整机编号:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.sn_entry = ttk.Entry(top, width=22)
        self.sn_entry.grid(row=0, column=1, padx=4)

        ttk.Label(top, text="操作员:").grid(row=0, column=2, sticky="w", padx=4)
        self.op_entry = ttk.Entry(top, width=14)
        self.op_entry.grid(row=0, column=3, padx=4)

        ttk.Label(top, text="串口:").grid(row=0, column=4, sticky="w", padx=4)
        self.port_combo = ttk.Combobox(top, width=26, state="readonly")
        self.port_combo.grid(row=0, column=5, padx=4)
        self.refresh_btn = ttk.Button(top, text="刷新/探测", command=self._refresh_ports)
        self.refresh_btn.grid(row=0, column=6, padx=4)
        self.connect_btn = ttk.Button(top, text="连接", command=self._toggle_led)
        self.connect_btn.grid(row=0, column=7, padx=4)
        self.led_status_label = ttk.Label(top, text="LED: 未连接", foreground="gray")
        self.led_status_label.grid(row=0, column=8, padx=6)

        # 中部：测试项列表
        mid = ttk.LabelFrame(self, text="测试项（双击 Pass/Fail 单元格可改判）")
        mid.pack(fill="both", expand=True, padx=8, pady=4)

        columns = ("name", "method", "status", "detail")
        self.tree = ttk.Treeview(mid, columns=columns, show="headings", height=12)
        self.tree.heading("name", text="测试项")
        self.tree.heading("method", text="判定方式")
        self.tree.heading("status", text="结果")
        self.tree.heading("detail", text="详情")
        self.tree.column("name", width=220, anchor="w")
        self.tree.column("method", width=80, anchor="center")
        self.tree.column("status", width=70, anchor="center")
        self.tree.column("detail", width=380, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)

        scroll = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="left", fill="y", pady=4)
        self.tree.bind("<Double-1>", self._on_item_double_click)

        # 右侧操作按钮
        actions = ttk.Frame(mid)
        actions.pack(side="left", fill="y", padx=6, pady=4)
        ttk.Button(actions, text="▶ 全部测试", width=14,
                   command=self._run_all).pack(pady=3)
        ttk.Button(actions, text="重跑选中项", width=14,
                   command=self._run_selected).pack(pady=3)
        ttk.Button(actions, text="标记 PASS", width=14,
                   command=lambda: self._manual_mark(PASSED)).pack(pady=3)
        ttk.Button(actions, text="标记 FAIL", width=14,
                   command=lambda: self._manual_mark(FAILED)).pack(pady=3)
        ttk.Button(actions, text="重置全部", width=14,
                   command=self._reset_all).pack(pady=3)

        # 底部：日志 + 报告
        bottom = ttk.LabelFrame(self, text="日志 / 报告")
        bottom.pack(fill="both", padx=8, pady=(4, 8))

        self.log_text = tk.Text(bottom, height=8, state="disabled",
                                font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

        report_bar = ttk.Frame(bottom)
        report_bar.pack(fill="x", padx=4, pady=(0, 4))
        self.summary_label = ttk.Label(report_bar, text="汇总: 待测", font=("", 11, "bold"))
        self.summary_label.pack(side="left")
        ttk.Button(report_bar, text="导出 TXT 报告",
                   command=lambda: self._export("txt")).pack(side="right", padx=4)
        ttk.Button(report_bar, text="导出 CSV 报告",
                   command=lambda: self._export("csv")).pack(side="right", padx=4)

        # 音频设备选择
        audio_bar = ttk.Frame(self)
        audio_bar.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(audio_bar, text="录音设备:").pack(side="left")
        self.in_combo = ttk.Combobox(audio_bar, width=42, state="readonly")
        self.in_combo.pack(side="left", padx=4)
        ttk.Label(audio_bar, text="播放设备:").pack(side="left", padx=(10, 0))
        self.out_combo = ttk.Combobox(audio_bar, width=42, state="readonly")
        self.out_combo.pack(side="left", padx=4)
        ttk.Button(audio_bar, text="刷新音频设备", command=self._refresh_audio).pack(side="left", padx=6)

    def _register_test_items(self) -> None:
        """注册标准测试序列。method: auto / manual"""
        specs = [
            ("LED-红色点亮", "manual"),
            ("LED-绿色点亮", "manual"),
            ("LED-蓝色点亮", "manual"),
            ("LED-白色点亮", "manual"),
            ("补光灯点亮", "manual"),
            ("扬声器-左声道", "manual"),
            ("扬声器-右声道", "manual"),
            ("麦克风-回环检测(左)", "auto"),
            ("麦克风-回环检测(右)", "auto"),
            ("相机预览", "manual"),
        ]
        for name, method in specs:
            item = self.report.add_item(name, method)
            self.tree.insert("", "end", iid=item.name,
                             values=(item.name, item.method, item.status, ""))
        self._refresh_ports()
        self._refresh_audio()

    # -------------------------------------------------------------- 串口

    def _refresh_ports(self) -> None:
        ports = serial_led.list_serial_ports()
        self._port_list = ports
        self.port_combo["values"] = [p.label for p in ports]
        if ports:
            self.port_combo.current(0)

    def _toggle_led(self) -> None:
        if self.runner.is_running:
            messagebox.showinfo("提示", "测试进行中，请勿断开串口")
            return
        if self.led_connected:
            self._disconnect_led()
        else:
            self._connect_led()

    def _selected_port_device(self) -> str | None:
        label = self.port_combo.get().strip()
        if not label:
            return None
        for port in getattr(self, "_port_list", []):
            if port.label == label or label.startswith(port.device):
                return port.device
        return None

    def _connect_led(self) -> None:
        device = self._selected_port_device()
        if not device:
            messagebox.showwarning("提示", "请先选择串口（或点击刷新/探测）")
            return
        if self.runner.is_running:
            messagebox.showinfo("提示", "后台任务进行中")
            return

        def work():
            led = serial_led.LedController(device)
            try:
                led.open()
            except Exception as exc:
                self.runner.emit("led_open_failed", (device, str(exc)))
                return
            probe = led.probe_in_place()
            self.runner.emit("led_opened", (led, probe))

        self.runner.start(work)

    def _finish_connect_opened(self, led, probe) -> None:
        if probe is None:
            if not messagebox.askyesno(
                    "未识别到 LED 控制器",
                    f"{led.port} 未应答 VERSION 指令。\n"
                    "仍要使用该串口吗？（部分固件不支持版本查询）"):
                try:
                    led.close()
                except Exception:
                    pass
                return
        self.led = led
        self.led_connected = True
        self.connect_btn.config(text="断开")
        version = probe.version if probe else "未知版本"
        self.led_status_label.config(text=f"LED: {led.port} ({version})",
                                     foreground="green")
        self._log(f"LED 串口已连接: {led.port} {version}")

    def _finish_connect_failed(self, device: str, error: str) -> None:
        messagebox.showerror("连接失败", f"打开 {device} 失败:\n{error}")
        self._log(f"打开 {device} 失败: {error}")

    def _disconnect_led(self) -> None:
        if self.led is not None:
            try:
                self.led.set_off()
            except Exception:
                pass
            self.led.close()
        self.led = None
        self.led_connected = False
        self.connect_btn.config(text="连接")
        self.led_status_label.config(text="LED: 未连接", foreground="gray")
        self._log("LED 串口已断开")

    # -------------------------------------------------------------- 音频

    def _refresh_audio(self) -> None:
        devices = audio_test.list_audio_devices()
        ins = [d for d in devices if d.is_input]
        outs = [d for d in devices if d.is_output]
        self.in_combo["values"] = [f"[{d.index}] {d.name}" for d in ins]
        self.out_combo["values"] = [f"[{d.index}] {d.name}" for d in outs]
        def_in, def_out = audio_test.default_devices()
        self.audio_in_dev = def_in
        self.audio_out_dev = def_out
        for combo, items, default in ((self.in_combo, ins, def_in),
                                      (self.out_combo, outs, def_out)):
            for i, d in enumerate(items):
                if d.index == default:
                    combo.current(i)
                    break

    def _selected_input(self) -> int | None:
        idx = self.in_combo.current()
        if idx < 0:
            return self.audio_in_dev
        label = self.in_combo["values"][idx]
        return int(label.split("]")[0].strip("["))

    def _selected_output(self) -> int | None:
        idx = self.out_combo.current()
        if idx < 0:
            return self.audio_out_dev
        label = self.out_combo["values"][idx]
        return int(label.split("]")[0].strip("["))

    # ----------------------------------------------------------- 测试流程

    def _run_all(self) -> None:
        if self.runner.is_running:
            messagebox.showinfo("提示", "测试进行中，请稍候")
            return
        if not self.led_connected:
            if not messagebox.askyesno(
                    "LED 未连接",
                    "LED 串口未连接，LED/补光灯项将跳过。\n是否继续跑音频和相机测试？"):
                return
        self.report.device_sn = self.sn_entry.get().strip()
        self.report.operator = self.op_entry.get().strip()
        self.report.reset()
        for item in self.report.items:
            self.tree.set(item.name, "status", item.status)
            self.tree.set(item.name, "detail", "")
        self._cached_input = self._selected_input()
        self._cached_output = self._selected_output()
        self.runner.start(self._test_sequence)

    def _run_selected(self) -> None:
        if self.runner.is_running:
            messagebox.showinfo("提示", "测试进行中，请稍候")
            return
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先在列表中选择测试项")
            return
        names = [s for s in selection]
        self.report.device_sn = self.sn_entry.get().strip()
        self.report.operator = self.op_entry.get().strip()
        self._cached_input = self._selected_input()
        self._cached_output = self._selected_output()
        self.runner.start(self._test_sequence, names)

    def _needs_led(self, name: str) -> bool:
        return name.startswith("LED-") or name.startswith("补光灯")

    def _test_sequence(self, only_names: list[str] | None = None) -> None:
        """后台线程：按顺序执行测试。人工项点亮硬件后等待 GUI 判定。"""
        for item in list(self.report.items):
            if only_names is not None and item.name not in only_names:
                continue
            if self.runner._stop_event.is_set():
                break
            if self._needs_led(item.name) and not self.led_connected:
                self.runner.emit("item_result",
                                 (item.name, f"[{rpt.SKIPPED}] LED 串口未连接"))
                continue
            if item.method == "manual":
                try:
                    self._start_manual_stimulus(item.name)
                except Exception as exc:
                    self.runner.emit("item_result",
                                     (item.name, f"[{FAILED}] 硬件动作失败: {exc}"))
                    continue
                self.runner._manual_done.clear()
                self.runner._manual_verdict = None
                self.runner.emit("await_manual", item.name)
                verdict = self.runner.wait_manual()
                self._stop_manual_stimulus(item.name)
                if verdict in (PASSED, FAILED):
                    self.runner.emit("item_result",
                                     (item.name, f"[{verdict}] 人工确认"))
                elif not self.runner._stop_event.is_set():
                    self.runner.emit("item_result",
                                     (item.name, f"[{FAILED}] 未确认"))
            else:
                self.runner.emit("item_start", item.name)
                result = self._run_auto_test(item.name)
                self.runner.emit("item_result", (item.name, result))
        try:
            if self.led is not None and self.led_connected:
                self.led.set_off()
        except Exception:
            pass
        audio_test.stop_playback()
        camera_test.stop_preview()
        self.runner.emit("sequence_done", None)

    def _start_manual_stimulus(self, name: str) -> None:
        """点亮/发声并保持，直到人工确认。失败则抛出，由调用方记 FAIL。"""
        if name == "LED-红色点亮":
            self.led.set_color(255, 0, 0)
        elif name == "LED-绿色点亮":
            self.led.set_color(0, 255, 0)
        elif name == "LED-蓝色点亮":
            self.led.set_color(0, 0, 255)
        elif name == "LED-白色点亮":
            self.led.set_color(255, 255, 255)
        elif name.startswith("补光灯"):
            self.led.set_fill_light(100)
        elif name.startswith("扬声器"):
            channel = "left" if "左" in name else "right"
            self.runner.emit("log", f"循环播放 {channel} 声道测试音，请听音后确认")
            audio_test.play_manual_tone(channel, 1.0,
                                        output_device=self._cached_output,
                                        blocking=False)
        elif name.startswith("相机"):
            self.runner.emit("log", f"启动相机软件: {camera_test.amcap_path()}")
            camera_test.start_preview()

    def _stop_manual_stimulus(self, name: str) -> None:
        try:
            if name.startswith("扬声器"):
                audio_test.stop_playback()
            elif name.startswith("补光灯") and self.led is not None:
                self.led.set_fill_light(0)
            elif name.startswith("相机"):
                camera_test.stop_preview()
        except Exception:
            pass

    def _run_auto_test(self, name: str) -> str:
        """执行自动判定测试项，返回详情文本。"""
        try:
            if name.startswith("麦克风-回环检测"):
                channel = "left" if "左" in name else "right"
                result = audio_test.run_loopback_test(
                    channel,
                    input_device=self._cached_input,
                    output_device=self._cached_output)
                return result.summary()
        except Exception as exc:
            return f"[{FAILED}] 测试异常: {exc}"
        return f"[{FAILED}] 未知测试项: {name}"

    def _finish_sequence(self) -> None:
        overall = self.report.overall
        color = "green" if overall == PASSED else (
            "red" if overall == FAILED else (
                "orange" if overall == rpt.SKIPPED else "black"))
        self.summary_label.config(
            text=f"汇总: {overall}  (通过 {self.report.passed_count} / "
                 f"失败 {self.report.failed_count} / 共 {len(self.report.items)})",
            foreground=color)
        self._log(f"测试序列结束，总判定: {overall}")
        # 人工项若仍待测，提示操作员判定
        pending = [i.name for i in self.report.items if i.status == PENDING]
        if pending:
            self._log("等待人工判定: " + ", ".join(pending))

    # ----------------------------------------------------------- 人工判定

    def _on_item_double_click(self, event) -> None:
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        column = self.tree.identify_column(event.x)
        row_id = self.tree.identify_row(event.y)
        if column in ("#3", "#4") and row_id:
            self._edit_cell(row_id, column)

    def _edit_cell(self, row_id: str, column: str) -> None:
        """双击结果/详情单元格：弹小输入框修改（用于人工改判/备注）。"""
        x, y, w, h = self.tree.bbox(row_id, column)
        value = self.tree.set(row_id, column)
        entry = tk.Entry(self.tree, justify="center" if column == "#3" else "w")
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, value)
        entry.focus_set()

        def commit(event=None) -> None:
            new_value = entry.get().strip()
            entry.destroy()
            if column == "#3":
                upper = new_value.upper()
                if upper in (PASSED, FAILED):
                    self._mark_item(row_id, upper, "人工改判")
                else:
                    self.tree.set(row_id, "status", value)  # 还原
            else:
                self.tree.set(row_id, "detail", new_value)
                item = next((i for i in self.report.items if i.name == row_id), None)
                if item is not None:
                    item.detail = new_value

        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)

    def _manual_mark(self, status: str) -> None:
        if self._awaiting_item:
            self.runner.resolve_manual(status)
            return
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择测试项")
            return
        for row_id in selection:
            self._mark_item(row_id, status, "人工判定")

    def _mark_item(self, name: str, status: str, detail: str) -> None:
        item = next((i for i in self.report.items if i.name == name), None)
        if item is None:
            return
        item.mark(status, detail)
        self.tree.set(name, "status", status)
        self.tree.set(name, "detail", detail)
        self._log(f"{name} -> {status} ({detail})")
        self._update_summary()
        # 人工判定后若 LED 处于点亮状态，切到下一色前先不关灯；
        # 全部人工 LED 项判定完成后关灯由下一项动作覆盖。

    def _update_summary(self) -> None:
        overall = self.report.overall
        color = "green" if overall == PASSED else (
            "red" if overall == FAILED else (
                "orange" if overall == rpt.SKIPPED else "black"))
        self.summary_label.config(
            text=f"汇总: {overall}  (通过 {self.report.passed_count} / "
                 f"失败 {self.report.failed_count} / 共 {len(self.report.items)})",
            foreground=color)

    def _reset_all(self) -> None:
        if self.runner.is_running:
            messagebox.showinfo("提示", "测试进行中，无法重置")
            return
        self.report.reset()
        for item in self.report.items:
            self.tree.set(item.name, "status", item.status)
            self.tree.set(item.name, "detail", "")
        self._update_summary()
        self._log("已重置全部测试项")

    # -------------------------------------------------------------- 报告

    def _export(self, fmt: str) -> None:
        if not any(i.status != PENDING for i in self.report.items):
            messagebox.showinfo("提示", "尚无测试结果可导出")
            return
        self.report.device_sn = self.sn_entry.get().strip()
        self.report.operator = self.op_entry.get().strip()
        try:
            if fmt == "txt":
                path = self.report.save_text("reports")
            else:
                path = self.report.save_csv("reports")
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        self._log(f"报告已导出: {path}")
        messagebox.showinfo("导出成功", f"报告已保存:\n{path}")

    # -------------------------------------------------------------- 事件

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                self._handle_event(kind, payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _handle_event(self, kind: str, payload) -> None:
        if kind == "log":
            self._log(str(payload))
        elif kind == "error":
            self._log(f"[错误] {payload}")
        elif kind == "led_opened":
            led, probe = payload
            self._finish_connect_opened(led, probe)
        elif kind == "led_open_failed":
            device, error = payload
            self._finish_connect_failed(device, error)
        elif kind == "item_start":
            self._log(f"开始: {payload}")
        elif kind == "item_result":
            name, detail = payload
            if detail.startswith(f"[{PASSED}]"):
                status = PASSED
            elif detail.startswith(f"[{rpt.SKIPPED}]"):
                status = rpt.SKIPPED
            else:
                status = FAILED
            self._mark_item(name, status, detail)
        elif kind == "await_manual":
            self._prompt_manual(str(payload))
        elif kind == "sequence_done":
            self._finish_sequence()

    def _prompt_manual(self, name: str) -> None:
        """弹出是/否对话框，把人工判定回传给后台线程。"""
        self._awaiting_item = name
        self.tree.selection_set(name)
        self.tree.see(name)
        self._log(f"请人工确认: {name}")
        ok = messagebox.askyesno(
            "人工确认",
            f"【{name}】是否正常？\n\n"
            "是 = PASS（颜色正确 / 声音正常 / 相机画面正常）\n"
            "否 = FAIL（不亮、颜色错、无声、接反、无画面）")
        verdict = PASSED if ok else FAILED
        self.runner.resolve_manual(verdict)
        self._awaiting_item = None

    def _log(self, message: str) -> None:
        from datetime import datetime
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"[{stamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _on_close(self) -> None:
        self.runner.stop()
        audio_test.stop_playback()
        camera_test.stop_preview()
        worker = self.runner._thread
        if worker is not None and worker.is_alive():
            worker.join(timeout=2.0)
        if self.led is not None:
            try:
                self.led.set_off()
            except Exception:
                pass
            try:
                self.led.close()
            except Exception:
                pass
        self.destroy()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
