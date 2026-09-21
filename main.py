"""WinAutoTest - Windows 部件连线检测工具（LED / 扬声器 / 麦克风 / 相机）。

测试项：
- LED 状态灯：红/绿/蓝/白 逐色点亮，人工目视确认连线与颜色正确
- 补光灯：点亮/熄灭，人工确认
- 扬声器：左右声道分别播放测试音，人工听音确认 + 可选麦克风回环自动检测
- 麦克风：录音能量自动检测
- 相机：打开 AMCap 预览软件，人工确认画面
- 扫码枪：9600 串口收一帧，对齐 Android ScannerSerialClient

运行：python main.py ；产线绿色包：build.bat 后双击 WinAutoTest.exe
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import app_paths
import audio_test
import camera_test
import i18n
import report as rpt
import scan_test
import serial_led

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
        self.title(i18n.t("app.title"))
        self.geometry("920x700")
        self.minsize(800, 580)

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
        self._led_version = ""
        self._cached_scanner: str | None = None

        self._build_ui()
        self._register_test_items()
        self.after(100, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._log(i18n.t("log.started"))

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        # 顶部：整机信息 + 串口连接
        self.top_frame = ttk.LabelFrame(self, text=i18n.t("frame.device"))
        self.top_frame.pack(fill="x", padx=8, pady=(8, 4))

        self.sn_label = ttk.Label(self.top_frame, text=i18n.t("label.sn"))
        self.sn_label.grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.sn_entry = ttk.Entry(self.top_frame, width=22)
        self.sn_entry.grid(row=0, column=1, padx=4)

        self.op_label = ttk.Label(self.top_frame, text=i18n.t("label.operator"))
        self.op_label.grid(row=0, column=2, sticky="w", padx=4)
        self.op_entry = ttk.Entry(self.top_frame, width=14)
        self.op_entry.grid(row=0, column=3, padx=4)

        self.port_label = ttk.Label(self.top_frame, text=i18n.t("label.port"))
        self.port_label.grid(row=0, column=4, sticky="w", padx=4)
        self.port_combo = ttk.Combobox(self.top_frame, width=26, state="readonly")
        self.port_combo.grid(row=0, column=5, padx=4)
        self.refresh_btn = ttk.Button(self.top_frame, text=i18n.t("btn.refresh_ports"),
                                      command=self._refresh_ports)
        self.refresh_btn.grid(row=0, column=6, padx=4)
        self.connect_btn = ttk.Button(self.top_frame, text=i18n.t("btn.connect"),
                                      command=self._toggle_led)
        self.connect_btn.grid(row=0, column=7, padx=4)
        self.led_status_label = ttk.Label(self.top_frame, text=i18n.t("led.disconnected"),
                                          foreground="gray")
        self.led_status_label.grid(row=0, column=8, padx=6)
        self.lang_btn = ttk.Button(self.top_frame, text=i18n.t("btn.lang"), width=10,
                                   command=self._toggle_language)
        self.lang_btn.grid(row=0, column=9, padx=6)

        self.scanner_label = ttk.Label(self.top_frame, text=i18n.t("label.scanner"))
        self.scanner_label.grid(row=1, column=0, sticky="w", padx=4, pady=(0, 4))
        self.scanner_combo = ttk.Combobox(self.top_frame, width=26, state="readonly")
        self.scanner_combo.grid(row=1, column=1, columnspan=2, padx=4, pady=(0, 4), sticky="w")
        self.scan_status_label = ttk.Label(self.top_frame, text=i18n.t("scan.disconnected"),
                                           foreground="gray")
        self.scan_status_label.grid(row=1, column=3, columnspan=3, sticky="w", padx=4, pady=(0, 4))
        self.scanner_combo.bind("<<ComboboxSelected>>", self._on_scanner_selected)

        # 中部：测试项列表
        self.mid_frame = ttk.LabelFrame(self, text=i18n.t("frame.tests"))
        self.mid_frame.pack(fill="both", expand=True, padx=8, pady=4)

        columns = ("name", "method", "status", "detail")
        self.tree = ttk.Treeview(self.mid_frame, columns=columns, show="headings", height=12)
        self.tree.heading("name", text=i18n.t("tree.name"))
        self.tree.heading("method", text=i18n.t("tree.method"))
        self.tree.heading("status", text=i18n.t("tree.status"))
        self.tree.heading("detail", text=i18n.t("tree.detail"))
        self.tree.column("name", width=220, anchor="w")
        self.tree.column("method", width=80, anchor="center")
        self.tree.column("status", width=70, anchor="center")
        self.tree.column("detail", width=380, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)

        scroll = ttk.Scrollbar(self.mid_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="left", fill="y", pady=4)
        self.tree.bind("<Double-1>", self._on_item_double_click)

        # 右侧操作按钮
        actions = ttk.Frame(self.mid_frame)
        actions.pack(side="left", fill="y", padx=6, pady=4)
        self.run_all_btn = ttk.Button(actions, text=i18n.t("btn.run_all"), width=16,
                                      command=self._run_all)
        self.run_all_btn.pack(pady=3)
        self.run_sel_btn = ttk.Button(actions, text=i18n.t("btn.run_selected"), width=16,
                                      command=self._run_selected)
        self.run_sel_btn.pack(pady=3)
        self.mark_pass_btn = ttk.Button(actions, text=i18n.t("btn.mark_pass"), width=16,
                                        command=lambda: self._manual_mark(PASSED))
        self.mark_pass_btn.pack(pady=3)
        self.mark_fail_btn = ttk.Button(actions, text=i18n.t("btn.mark_fail"), width=16,
                                        command=lambda: self._manual_mark(FAILED))
        self.mark_fail_btn.pack(pady=3)
        self.reset_btn = ttk.Button(actions, text=i18n.t("btn.reset"), width=16,
                                    command=self._reset_all)
        self.reset_btn.pack(pady=3)

        # 底部：日志 + 报告
        self.bottom_frame = ttk.LabelFrame(self, text=i18n.t("frame.log"))
        self.bottom_frame.pack(fill="both", padx=8, pady=(4, 8))

        self.log_text = tk.Text(self.bottom_frame, height=8, state="disabled",
                                font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

        report_bar = ttk.Frame(self.bottom_frame)
        report_bar.pack(fill="x", padx=4, pady=(0, 4))
        self.summary_label = ttk.Label(report_bar, text="", font=("", 11, "bold"))
        self.summary_label.pack(side="left")
        self.export_txt_btn = ttk.Button(report_bar, text=i18n.t("btn.export_txt"),
                                         command=lambda: self._export("txt"))
        self.export_txt_btn.pack(side="right", padx=4)
        self.export_csv_btn = ttk.Button(report_bar, text=i18n.t("btn.export_csv"),
                                         command=lambda: self._export("csv"))
        self.export_csv_btn.pack(side="right", padx=4)

        # 音频设备选择
        audio_bar = ttk.Frame(self)
        audio_bar.pack(fill="x", padx=8, pady=(0, 4))
        self.in_label = ttk.Label(audio_bar, text=i18n.t("label.input"))
        self.in_label.pack(side="left")
        self.in_combo = ttk.Combobox(audio_bar, width=42, state="readonly")
        self.in_combo.pack(side="left", padx=4)
        self.out_label = ttk.Label(audio_bar, text=i18n.t("label.output"))
        self.out_label.pack(side="left", padx=(10, 0))
        self.out_combo = ttk.Combobox(audio_bar, width=42, state="readonly")
        self.out_combo.pack(side="left", padx=4)
        self.refresh_audio_btn = ttk.Button(audio_bar, text=i18n.t("btn.refresh_audio"),
                                            command=self._refresh_audio)
        self.refresh_audio_btn.pack(side="left", padx=6)
        self._update_summary()

    def _register_test_items(self) -> None:
        """注册标准测试序列。method: auto / manual"""
        for item_id, method in i18n.TEST_SPECS:
            item = self.report.add_item(item_id, method)
            self.tree.insert("", "end", iid=item.name,
                             values=(i18n.item_name(item.name),
                                     i18n.method_label(item.method),
                                     i18n.status_label(item.status), ""))
        self._refresh_ports()
        self._refresh_audio()
        self._update_summary()

    def _toggle_language(self) -> None:
        if self.runner.is_running:
            messagebox.showinfo(i18n.t("msg.title"), i18n.t("msg.test_running"))
            return
        i18n.toggle_lang()
        self._apply_language()
        self._log(i18n.t("log.switched"))

    def _apply_language(self) -> None:
        self.title(i18n.t("app.title"))
        self.top_frame.config(text=i18n.t("frame.device"))
        self.sn_label.config(text=i18n.t("label.sn"))
        self.op_label.config(text=i18n.t("label.operator"))
        self.port_label.config(text=i18n.t("label.port"))
        self.scanner_label.config(text=i18n.t("label.scanner"))
        self.refresh_btn.config(text=i18n.t("btn.refresh_ports"))
        self.connect_btn.config(
            text=i18n.t("btn.disconnect") if self.led_connected else i18n.t("btn.connect"))
        self.lang_btn.config(text=i18n.t("btn.lang"))
        self.mid_frame.config(text=i18n.t("frame.tests"))
        self.tree.heading("name", text=i18n.t("tree.name"))
        self.tree.heading("method", text=i18n.t("tree.method"))
        self.tree.heading("status", text=i18n.t("tree.status"))
        self.tree.heading("detail", text=i18n.t("tree.detail"))
        self.run_all_btn.config(text=i18n.t("btn.run_all"))
        self.run_sel_btn.config(text=i18n.t("btn.run_selected"))
        self.mark_pass_btn.config(text=i18n.t("btn.mark_pass"))
        self.mark_fail_btn.config(text=i18n.t("btn.mark_fail"))
        self.reset_btn.config(text=i18n.t("btn.reset"))
        self.bottom_frame.config(text=i18n.t("frame.log"))
        self.export_txt_btn.config(text=i18n.t("btn.export_txt"))
        self.export_csv_btn.config(text=i18n.t("btn.export_csv"))
        self.in_label.config(text=i18n.t("label.input"))
        self.out_label.config(text=i18n.t("label.output"))
        self.refresh_audio_btn.config(text=i18n.t("btn.refresh_audio"))
        self._refresh_led_status_text()
        self._refresh_scanner_status_text()
        self._refresh_ports()
        for item in self.report.items:
            self.tree.set(item.name, "name", i18n.item_name(item.name))
            self.tree.set(item.name, "method", i18n.method_label(item.method))
            self.tree.set(item.name, "status", i18n.status_label(item.status))
        self._update_summary()

    def _refresh_led_status_text(self) -> None:
        if self.led_connected and self.led is not None:
            version = self._led_version or i18n.t("led.unknown_version")
            self.led_status_label.config(
                text=i18n.t("led.connected", port=self.led.port, version=version),
                foreground="green")
        else:
            self.led_status_label.config(text=i18n.t("led.disconnected"), foreground="gray")

    # -------------------------------------------------------------- 串口

    def _refresh_ports(self) -> None:
        current = self._selected_port_device()
        current_scan = self._selected_scanner_device()
        ports = serial_led.list_serial_ports()
        self._port_list = ports
        labels = [p.label for p in ports]
        self.port_combo["values"] = labels
        scan_labels = [""] + labels
        self.scanner_combo["values"] = scan_labels
        if current:
            for i, port in enumerate(ports):
                if port.device == current:
                    self.port_combo.current(i)
                    break
            else:
                if ports:
                    self.port_combo.current(0)
        elif ports:
            self.port_combo.current(0)
        if current_scan:
            for i, port in enumerate(ports):
                if port.device == current_scan:
                    self.scanner_combo.current(i + 1)
                    break
            else:
                self.scanner_combo.current(0)
        else:
            self.scanner_combo.current(0)
        self._refresh_scanner_status_text()

    def _selected_scanner_device(self) -> str | None:
        label = self.scanner_combo.get().strip()
        if not label:
            return None
        for port in getattr(self, "_port_list", []):
            if port.label == label or label.startswith(port.device):
                return port.device
        return None

    def _on_scanner_selected(self, _event=None) -> None:
        self._refresh_scanner_status_text()

    def _refresh_scanner_status_text(self) -> None:
        device = self._selected_scanner_device()
        if device:
            self.scan_status_label.config(
                text=i18n.t("scan.selected", port=device), foreground="green")
        else:
            self.scan_status_label.config(
                text=i18n.t("scan.disconnected"), foreground="gray")

    def _toggle_led(self) -> None:
        if self.runner.is_running:
            messagebox.showinfo(i18n.t("msg.title"), i18n.t("msg.test_running_no_disconnect"))
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
            messagebox.showwarning(i18n.t("msg.title"), i18n.t("msg.select_port"))
            return
        if self.runner.is_running:
            messagebox.showinfo(i18n.t("msg.title"), i18n.t("msg.background_busy"))
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
                    i18n.t("msg.led_unrecognized_title"),
                    i18n.t("msg.led_unrecognized_body", port=led.port)):
                try:
                    led.close()
                except Exception:
                    pass
                return
        self.led = led
        self.led_connected = True
        self.connect_btn.config(text=i18n.t("btn.disconnect"))
        self._led_version = probe.version if probe else ""
        self._refresh_led_status_text()
        version = self._led_version or i18n.t("led.unknown_version")
        self._log(i18n.t("log.led_connected", port=led.port, version=version))

    def _finish_connect_failed(self, device: str, error: str) -> None:
        messagebox.showerror(
            i18n.t("msg.connect_failed"),
            i18n.t("msg.connect_failed_body", device=device, error=error))
        self._log(i18n.t("log.open_failed", device=device, error=error))

    def _disconnect_led(self) -> None:
        if self.led is not None:
            try:
                self.led.set_off()
            except Exception:
                pass
            self.led.close()
        self.led = None
        self.led_connected = False
        self._led_version = ""
        self.connect_btn.config(text=i18n.t("btn.connect"))
        self.led_status_label.config(text=i18n.t("led.disconnected"), foreground="gray")
        self._log(i18n.t("log.led_disconnected"))

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
            messagebox.showinfo(i18n.t("msg.title"), i18n.t("msg.test_running"))
            return
        if not self.led_connected:
            if not messagebox.askyesno(
                    i18n.t("msg.led_not_connected_title"),
                    i18n.t("msg.led_not_connected_body")):
                return
        if not self._selected_scanner_device():
            if not messagebox.askyesno(
                    i18n.t("msg.scanner_not_selected_title"),
                    i18n.t("msg.scanner_not_selected_body")):
                return
        self.report.device_sn = self.sn_entry.get().strip()
        self.report.operator = self.op_entry.get().strip()
        self.report.reset()
        for item in self.report.items:
            self.tree.set(item.name, "status", i18n.status_label(item.status))
            self.tree.set(item.name, "detail", "")
        self._cached_input = self._selected_input()
        self._cached_output = self._selected_output()
        self._cached_scanner = self._selected_scanner_device()
        self.runner.start(self._test_sequence)

    def _run_selected(self) -> None:
        if self.runner.is_running:
            messagebox.showinfo(i18n.t("msg.title"), i18n.t("msg.test_running"))
            return
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo(i18n.t("msg.title"), i18n.t("msg.select_item"))
            return
        names = [s for s in selection]
        self.report.device_sn = self.sn_entry.get().strip()
        self.report.operator = self.op_entry.get().strip()
        self._cached_input = self._selected_input()
        self._cached_output = self._selected_output()
        self._cached_scanner = self._selected_scanner_device()
        self.runner.start(self._test_sequence, names)

    def _needs_led(self, name: str) -> bool:
        return name in i18n.LED_ITEM_IDS

    def _test_sequence(self, only_names: list[str] | None = None) -> None:
        """后台线程：按顺序执行测试。人工项点亮硬件后等待 GUI 判定。"""
        for item in list(self.report.items):
            if only_names is not None and item.name not in only_names:
                continue
            if self.runner._stop_event.is_set():
                break
            if self._needs_led(item.name) and not self.led_connected:
                self.runner.emit("item_result",
                                 (item.name, i18n.t("result.led_skipped",
                                                    status=rpt.SKIPPED)))
                continue
            if item.method == "manual":
                try:
                    self._start_manual_stimulus(item.name)
                except Exception as exc:
                    self.runner.emit("item_result",
                                     (item.name, i18n.t("result.hw_failed",
                                                        status=FAILED, error=exc)))
                    continue
                self.runner._manual_done.clear()
                self.runner._manual_verdict = None
                self.runner.emit("await_manual", item.name)
                verdict = self.runner.wait_manual()
                self._stop_manual_stimulus(item.name)
                if verdict in (PASSED, FAILED):
                    self.runner.emit("item_result",
                                     (item.name, i18n.t("result.manual_confirm",
                                                        status=verdict)))
                elif not self.runner._stop_event.is_set():
                    self.runner.emit("item_result",
                                     (item.name, i18n.t("result.unconfirmed",
                                                        status=FAILED)))
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
        if name == "led_red":
            self.led.set_color(255, 0, 0)
        elif name == "led_green":
            self.led.set_color(0, 255, 0)
        elif name == "led_blue":
            self.led.set_color(0, 0, 255)
        elif name == "led_white":
            self.led.set_color(255, 255, 255)
        elif name == "fill_light":
            self.led.set_fill_light(100)
        elif name in ("speaker_left", "speaker_right"):
            channel = "left" if name == "speaker_left" else "right"
            self.runner.emit("log", i18n.t("log.play_tone",
                                           channel=i18n.t(f"channel.{channel}")))
            audio_test.play_manual_tone(channel, 1.0,
                                        output_device=self._cached_output,
                                        blocking=False)
        elif name == "camera":
            self.runner.emit("log", i18n.t("log.start_camera",
                                           path=camera_test.amcap_path()))
            camera_test.start_preview()

    def _stop_manual_stimulus(self, name: str) -> None:
        try:
            if name in ("speaker_left", "speaker_right"):
                audio_test.stop_playback()
            elif name == "fill_light" and self.led is not None:
                self.led.set_fill_light(0)
            elif name == "camera":
                camera_test.stop_preview()
        except Exception:
            pass

    def _run_auto_test(self, name: str) -> str:
        """执行自动判定测试项，返回详情文本。"""
        try:
            if name in ("mic_left", "mic_right"):
                channel = "left" if name == "mic_left" else "right"
                result = audio_test.run_loopback_test(
                    channel,
                    input_device=self._cached_input,
                    output_device=self._cached_output)
                return result.summary()
            if name == "scanner":
                return self._run_scanner_test()
        except Exception as exc:
            return i18n.t("result.test_error", status=FAILED, error=exc)
        return i18n.t("result.unknown_item", status=FAILED, name=name)

    def _run_scanner_test(self) -> str:
        port = self._cached_scanner
        if not port:
            return i18n.t("result.scan_skipped", status=rpt.SKIPPED)
        if self.led_connected and self.led is not None and self.led.port == port:
            return i18n.t("result.scan_same_port", status=FAILED)
        self.runner.emit("log", i18n.t("log.scan_waiting",
                                       timeout=scan_test.DEFAULT_SCAN_TIMEOUT))
        client = scan_test.ScannerClient(port)
        try:
            client.open()
            result = client.read_single_scan(
                timeout=scan_test.DEFAULT_SCAN_TIMEOUT,
                should_stop=self.runner._stop_event.is_set)
        except Exception as exc:
            return i18n.t("result.scan_fail", status=FAILED, error=exc)
        finally:
            client.close()
        if result.success:
            self.runner.emit("log", i18n.t("log.scan_got", content=result.content))
        return result.summary()

    def _finish_sequence(self) -> None:
        overall = self.report.overall
        self._update_summary()
        self._log(i18n.t("log.sequence_done", overall=i18n.status_label(overall)))
        pending = [i18n.item_name(i.name) for i in self.report.items
                   if i.status == PENDING]
        if pending:
            self._log(i18n.t("log.wait_manual", items=", ".join(pending)))

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
                    self._mark_item(row_id, upper, i18n.t("detail.override"))
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
            messagebox.showinfo(i18n.t("msg.title"), i18n.t("msg.select_item"))
            return
        for row_id in selection:
            self._mark_item(row_id, status, i18n.t("detail.manual"))

    def _mark_item(self, name: str, status: str, detail: str) -> None:
        item = next((i for i in self.report.items if i.name == name), None)
        if item is None:
            return
        item.mark(status, detail)
        self.tree.set(name, "status", i18n.status_label(status))
        self.tree.set(name, "detail", detail)
        self._log(f"{i18n.item_name(name)} -> {i18n.status_label(status)} ({detail})")
        self._update_summary()
        # 人工判定后若 LED 处于点亮状态，切到下一色前先不关灯；
        # 全部人工 LED 项判定完成后关灯由下一项动作覆盖。

    def _update_summary(self) -> None:
        overall = self.report.overall
        color = "green" if overall == PASSED else (
            "red" if overall == FAILED else (
                "orange" if overall == rpt.SKIPPED else "black"))
        self.summary_label.config(
            text=i18n.t("summary",
                        overall=i18n.status_label(overall),
                        passed=self.report.passed_count,
                        failed=self.report.failed_count,
                        total=len(self.report.items)),
            foreground=color)

    def _reset_all(self) -> None:
        if self.runner.is_running:
            messagebox.showinfo(i18n.t("msg.title"), i18n.t("msg.cannot_reset"))
            return
        self.report.reset()
        for item in self.report.items:
            self.tree.set(item.name, "status", i18n.status_label(item.status))
            self.tree.set(item.name, "detail", "")
        self._update_summary()
        self._log(i18n.t("log.reset"))

    # -------------------------------------------------------------- 报告

    def _export(self, fmt: str) -> None:
        if not any(i.status != PENDING for i in self.report.items):
            messagebox.showinfo(i18n.t("msg.title"), i18n.t("msg.nothing_to_export"))
            return
        self.report.device_sn = self.sn_entry.get().strip()
        self.report.operator = self.op_entry.get().strip()
        try:
            if fmt == "txt":
                path = self.report.save_text(app_paths.reports_dir())
            else:
                path = self.report.save_csv(app_paths.reports_dir())
        except Exception as exc:
            messagebox.showerror(i18n.t("msg.export_failed"), str(exc))
            return
        self._log(i18n.t("log.exported", path=path))
        messagebox.showinfo(i18n.t("msg.export_ok"),
                            i18n.t("msg.export_ok_body", path=path))

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
            self._log(i18n.t("log.error", payload=payload))
        elif kind == "led_opened":
            led, probe = payload
            self._finish_connect_opened(led, probe)
        elif kind == "led_open_failed":
            device, error = payload
            self._finish_connect_failed(device, error)
        elif kind == "item_start":
            self._log(i18n.t("log.item_start", name=i18n.item_name(str(payload))))
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
        self._log(i18n.t("log.confirm", name=i18n.item_name(name)))
        ok = messagebox.askyesno(
            i18n.t("msg.confirm_title"),
            i18n.t("msg.confirm_body", name=i18n.item_name(name)))
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
        worker = self.runner._thread
        if worker is not None and worker.is_alive():
            worker.join(timeout=5.0)
        audio_test.stop_playback()
        camera_test.stop_preview()
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
