"""zapret-warp — графический интерфейс (tkinter)."""
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

from core import config, doctor, engine, strategy, warp

WARP_MODES = ["warp+doh", "warp", "doh", "dot", "warp+dot", "proxy", "tunnel_only"]
WARP_PROTOCOLS = ["MASQUE", "WireGuard"]
WARP_MASQUE = ["h3-with-h2-fallback", "h3-only", "h2-only"]


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("zapret-warp — Simple Fake + Cloudflare WARP")
        self.root.geometry("640x560")
        self.root.minsize(560, 500)

        self.cfg = config.load()
        self.q = queue.Queue()
        self._build()

        self._refresh_status()
        self.root.after(100, self._drain)
        self.root.after(3000, self._schedule_status)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI
    def _build(self):
        pad = {"padx": 8, "pady": 4}

        # статус
        status = ttk.LabelFrame(self.root, text="Статус")
        status.pack(fill="x", **pad)
        self.lbl_engine = ttk.Label(status, text="DPI-десинк: …")
        self.lbl_engine.pack(anchor="w", **pad)
        self.lbl_warp = ttk.Label(status, text="Cloudflare WARP: …")
        self.lbl_warp.pack(anchor="w", **pad)

        # кнопки
        btns = ttk.Frame(self.root)
        btns.pack(fill="x", **pad)
        self.btn_start = ttk.Button(btns, text="▶  СТАРТ", command=self.on_start)
        self.btn_start.pack(side="left", fill="x", expand=True, **pad)
        self.btn_stop = ttk.Button(btns, text="■  СТОП", command=self.on_stop)
        self.btn_stop.pack(side="left", fill="x", expand=True, **pad)
        self.btn_doctor = ttk.Button(btns, text="🔍 Проверка", command=self.on_doctor)
        self.btn_doctor.pack(side="left", fill="x", expand=True, **pad)

        # настройки
        cfg = ttk.LabelFrame(self.root, text="Настройки")
        cfg.pack(fill="x", **pad)

        row = ttk.Frame(cfg); row.pack(fill="x", **pad)
        ttk.Label(row, text="Стратегия:").pack(side="left")
        self.var_strategy = tk.StringVar(value=self.cfg["strategy"])
        self.cmb_strategy = ttk.Combobox(
            row, textvariable=self.var_strategy, values=strategy.list_strategies(),
            state="readonly", width=28,
        )
        self.cmb_strategy.pack(side="left", padx=6)

        row = ttk.Frame(cfg); row.pack(fill="x", **pad)
        ttk.Label(row, text="Интерфейс:").pack(side="left")
        self.var_iface = tk.StringVar(value=self.cfg["interface"])
        self.cmb_iface = ttk.Combobox(
            row, textvariable=self.var_iface, values=engine.list_interfaces(),
            state="readonly", width=12,
        )
        self.cmb_iface.pack(side="left", padx=6)

        self.var_gf_tcp = tk.BooleanVar(value=self.cfg["gamefilter_tcp"])
        self.var_gf_udp = tk.BooleanVar(value=self.cfg["gamefilter_udp"])
        ttk.Checkbutton(cfg, text="GameFilter TCP", variable=self.var_gf_tcp).pack(anchor="w", **pad)
        ttk.Checkbutton(cfg, text="GameFilter UDP", variable=self.var_gf_udp).pack(anchor="w", **pad)

        # WARP
        warp_frame = ttk.LabelFrame(self.root, text="Cloudflare WARP")
        warp_frame.pack(fill="x", **pad)

        self.var_warp = tk.BooleanVar(value=self.cfg["warp_enabled"])
        ttk.Checkbutton(warp_frame, text="Включить WARP", variable=self.var_warp).pack(anchor="w", **pad)

        row = ttk.Frame(warp_frame); row.pack(fill="x", **pad)
        ttk.Label(row, text="Режим:").pack(side="left")
        self.var_mode = tk.StringVar(value=self.cfg["warp_mode"])
        ttk.Combobox(row, textvariable=self.var_mode, values=WARP_MODES,
                     state="readonly", width=14).pack(side="left", padx=6)
        ttk.Label(row, text="Протокол:").pack(side="left")
        self.var_proto = tk.StringVar(value=self.cfg["warp_protocol"])
        ttk.Combobox(row, textvariable=self.var_proto, values=WARP_PROTOCOLS,
                     state="readonly", width=12).pack(side="left", padx=6)
        ttk.Label(row, text="MASQUE:").pack(side="left")
        self.var_masque = tk.StringVar(value=self.cfg["warp_masque"])
        ttk.Combobox(row, textvariable=self.var_masque, values=WARP_MASQUE,
                     state="readonly", width=20).pack(side="left", padx=6)

        # лог
        log = ttk.LabelFrame(self.root, text="Лог")
        log.pack(fill="both", expand=True, **pad)
        self.txt = tk.Text(log, height=10, wrap="word", state="disabled")
        sb = ttk.Scrollbar(log, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=4)
        sb.pack(side="right", fill="y", pady=4)

    # ------------------------------------------------------------- логика
    def _collect(self):
        c = dict(self.cfg)
        c["strategy"] = self.var_strategy.get()
        c["interface"] = self.var_iface.get()
        c["gamefilter_tcp"] = self.var_gf_tcp.get()
        c["gamefilter_udp"] = self.var_gf_udp.get()
        c["warp_enabled"] = self.var_warp.get()
        c["warp_mode"] = self.var_mode.get()
        c["warp_protocol"] = self.var_proto.get()
        c["warp_masque"] = self.var_masque.get()
        return c

    def _log(self, text):
        self.q.put(("log", text))

    def _append_log(self, text):
        self.txt.configure(state="normal")
        self.txt.insert("end", "[" + time.strftime("%H:%M:%S") + "] " + text + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _apply_status(self, d):
        eng = d.get("engine")
        self.lbl_engine.config(
            text="DPI-десинк: " + ("● запущен" if eng else "○ остановлен"),
            foreground="#1a7f1a" if eng else "#a33",
        )
        st = d.get("warp") or ""
        conn = "Connected" in st
        self.lbl_warp.config(
            text="Cloudflare WARP: " + ("● подключен" if conn else "○ отключен"),
            foreground="#1a7f1a" if conn else "#a33",
        )

    def _worker_status(self):
        d = {"engine": engine.is_running()}
        d["warp"] = warp.status(self.cfg) if warp.installed() else "не установлен"
        self.q.put(("status", d))

    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                else:
                    self._apply_status(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    def _refresh_status(self):
        threading.Thread(target=self._worker_status, daemon=True).start()

    def _schedule_status(self):
        self._refresh_status()
        self.root.after(3000, self._schedule_status)

    def on_start(self):
        c = self._collect()
        config.save(c)
        self.cfg = c
        self.btn_start.config(state="disabled")
        self._log("СТАРТ…")
        threading.Thread(target=self._do_start, args=(c,), daemon=True).start()

    def on_doctor(self):
        self._log("Проверка готовности…")
        threading.Thread(target=self._do_doctor, daemon=True).start()

    def _do_doctor(self):
        for line in doctor.format_report(doctor.run()).split("\n"):
            self._log(line)

    def _elevation_hint(self):
        """Подсказка, специфичная для ОС, когда DPI-движок не стартовал."""
        if os.name == "nt":
            if engine.is_admin():
                return ("Подсказка: драйвер WinDivert не загрузился — проверь, что "
                        "bin/winws.exe и bin/WinDivert64.sys лежат рядом с .exe, "
                        "и что winws.exe не блокируется антивирусом.")
            return ("Подсказка: запустите zapret-warp.exe от имени администратора "
                    "(ПКМ → «Запуск от имени администратора»): winws нужен "
                    "драйвер WinDivert, а warp-cli на Windows требует прав админа.")
        return ("Подсказка: запусти GUI без sudo и выполни один раз:\n"
                "    sudo python3 cli.py setup   (NOPASSWD для root-helper)")

    def _do_start(self, c):
        try:
            self._log("Запуск DPI-десинка: " + c["strategy"])
            engine.start(c["strategy"], c["interface"],
                         c["gamefilter_tcp"], c["gamefilter_udp"])
            self._log("DPI-десинк запущен (nfqws/winws)")
        except Exception as e:
            self._log("Ошибка десинка: " + str(e))
            self._log(self._elevation_hint())
            self._log("Готово (с ошибкой).")
            self.root.after(0, lambda: self.btn_start.config(state="normal"))
            return

        if not engine.is_running():
            self._log("Внимание: процесс nfqws/winws не найден — десинк НЕ работает.")
            self._log(self._elevation_hint())

        time.sleep(3)
        if c["warp_enabled"]:
            try:
                if warp.installed():
                    self._log("Подключение WARP…")
                    st = warp.connect(c)
                    self._log("WARP подключен: " + st)
                else:
                    self._log("warp-cli не найден — пропуск WARP")
            except Exception as e:
                self._log("Ошибка WARP: " + str(e))
        self._log("Готово.")
        self.root.after(0, lambda: self.btn_start.config(state="normal"))

    def on_stop(self):
        self._log("СТОП…")
        threading.Thread(target=self._do_stop, daemon=True).start()

    def _do_stop(self):
        try:
            engine.stop()
            self._log("DPI-десинк остановлен")
        except Exception as e:
            self._log("Ошибка остановки десинка: " + str(e))
        try:
            if warp.installed():
                warp.disconnect(self.cfg)
                self._log("WARP отключен")
        except Exception as e:
            self._log("Ошибка WARP: " + str(e))
        self._log("Остановлено.")

    def _on_close(self):
        config.save(self._collect())
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
