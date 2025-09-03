import sys
import os
import tkinter as tk
from tkinter import filedialog
from tkinter import ttk
import threading
from merge_text_logs import main as qc_main
from analyzer import main as ylog_main


class LogMergerUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        # 初始化时先隐藏窗口，避免显示后再移动
        self.root.withdraw()
        self.root.title("日志合并")
        icon_xml = os.path.join(os.path.dirname(__file__), "icon", "merge.ico")
        try:
            # 仅在 Windows 下有效
            if os.path.exists(icon_xml):
                self.root.iconbitmap(icon_xml)
        except Exception:
            pass
        # 初始即设置居中几何，避免先显示后移动
        win_w, win_h = 400, 200
        scr_w = self.root.winfo_screenwidth()
        scr_h = self.root.winfo_screenheight()
        pos_x = (scr_w - win_w) // 2
        pos_y = (scr_h - win_h) // 2
        self.root.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")

        self.last_directory = None

        # 使用 ttk 风格与主题美化按钮
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        self.style.configure(
            "Primary.TButton",
            font=("Microsoft YaHei", 10),
            padding=(14, 8),
            foreground="#ffffff",
            background="#3A7AF2",
            borderwidth=0,
        )
        self.style.map(
            "Primary.TButton",
            background=[("active", "#255DF5"), ("pressed", "#1E4FD0"), ("disabled", "#9bb4ff")],
        )

        # 使用 grid 保证底部按钮不被遮挡
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        # 文本日志区域（无滚动条）
        self.log_area = tk.Text(self.root, state="disabled", wrap="word")
        self.log_area.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))

        # 按钮区域
        button_frame = tk.Frame(self.root)
        button_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        # 三列等宽并随窗口扩展
        button_frame.grid_columnconfigure(0, weight=1, uniform="buttons")
        button_frame.grid_columnconfigure(1, weight=1, uniform="buttons")
        button_frame.grid_columnconfigure(2, weight=1, uniform="buttons")

        self.import_button = ttk.Button(button_frame, text="导入高通合并", command=self.select_directory, style="Primary.TButton", cursor="hand2")
        self.import_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.import_ylog_button = ttk.Button(button_frame, text="导入ylog合并", command=self.import_ylog, style="Primary.TButton", cursor="hand2")
        self.import_ylog_button.grid(row=0, column=1, sticky="ew", padx=(0, 8))

        self.open_button = ttk.Button(button_frame, text="打开", command=self.open_imported_directory, style="Primary.TButton", cursor="hand2")
        self.open_button.grid(row=0, column=2, sticky="ew")

        # 完成布局后再显示窗口，避免位置跳动
        self.root.deiconify()

    def append_log(self, message: str) -> None:
        self.log_area.configure(state="normal")
        self.log_area.insert("end", message + "\n")
        self.log_area.see("end")
        self.log_area.configure(state="disabled")

    def append_log_async(self, message: str) -> None:
        self.root.after(0, self.append_log, message)

    def select_directory(self):
        directory = filedialog.askdirectory(title="选择文件夹")
        if directory:
            self.last_directory = directory
            threading.Thread(target=self._merge_qc_worker, args=(directory,), daemon=True).start()

    def _merge_qc_worker(self, directory: str) -> None:
        self.append_log_async(f"已选择文件夹: {directory}")
        try:
            output_file = os.path.join(directory, "out.txt")
            qc_main(directory, output_file)
            self.append_log_async(f"高通日志已合并到: {output_file}")
        except Exception as e:
            self.append_log_async(f"高通日志合并失败: {e}")

    def open_imported_directory(self):
        if self.last_directory and os.path.isdir(self.last_directory):
            try:
                os.startfile(self.last_directory)
                self.append_log(f"已打开文件夹: {self.last_directory}")
            except Exception as e:
                self.append_log(f"打开文件夹失败: {e}")
        else:
            self.append_log("尚未导入任何文件夹")

    def import_ylog(self):
        directory = filedialog.askdirectory(title="选择ylog路径")
        if directory:
            self.last_directory = directory
            threading.Thread(target=self._ylog_worker, args=(directory,), daemon=True).start()

    def _ylog_worker(self, directory: str) -> None:
        self.append_log_async(f"已选择ylog路径: {directory}")
        old_argv = sys.argv[:]
        old_cwd = os.getcwd()
        try:
            os.chdir(directory)
            sys.argv = ["analyzer"]
            ylog_main()
            self.append_log_async("ylog解析完成")
        except Exception as e:
            self.append_log_async(f"ylog解析失败: {e}")
        finally:
            os.chdir(old_cwd)
            sys.argv = old_argv


if __name__ == "__main__":
    root = tk.Tk()
    app = LogMergerUI(root)
    root.mainloop()
