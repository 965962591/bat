import sys
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QCheckBox,
    QGridLayout,
    QTextEdit,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QMessageBox,
    QLabel,
    QMenu,
    QInputDialog,
    QSplitter,
    QDialog,
    QLineEdit,
    QDialogButtonBox,
    QComboBox,
)
import subprocess
from PyQt5.QtGui import QIcon
import threading
from PyQt5.QtCore import QMetaObject, Qt, pyqtSlot, Q_ARG, QTimer, pyqtSignal, QThread
import json
import os
import wmi
import pythoncom
import configparser

from qt_material import apply_stylesheet

# 全局变量定义缓存目录
APP_CACHE_DIR = os.path.join(os.path.dirname(__file__), "app_cache")

class USBDeviceMonitor:
    """USB设备实时监控类（Windows平台专用）"""
    
    def __init__(self, on_device_changed=None):
        self.on_device_changed = on_device_changed
        self.monitor_thread = threading.Thread(target=self.start_monitoring)
        self.monitor_thread.daemon = True
        self.thread_running = False

    def device_changed_callback(self):
        if callable(self.on_device_changed):
            self.on_device_changed()

    def start_monitoring(self):
        pythoncom.CoInitialize()
        try:
            c = wmi.WMI(moniker="root/cimv2")
            arr_filter = c.Win32_PnPEntity.watch_for(
                notification_type="creation",
                delay_secs=1
            )
            rem_filter = c.Win32_PnPEntity.watch_for(
                notification_type="deletion",
                delay_secs=1
            )

            self.thread_running = True
            # print("[监控系统] USB设备监控服务启动")
            while self.thread_running:
                try:
                    new_device = arr_filter(0.5)
                    # print(f"[监控系统] 检测到新设备: {new_device.Description}")
                    self.device_changed_callback()
                except wmi.x_wmi_timed_out:
                    pass

                try:
                    removed_device = rem_filter(0.5)
                    # print(f"[监控系统] 检测到设备移除: {removed_device.Description}")
                    self.device_changed_callback()
                except wmi.x_wmi_timed_out:
                    pass

        except Exception as e:
            print(f"[监控系统] 监控出错: {e}")
        finally:
            pythoncom.CoUninitialize()
            # print("[监控系统] 监控服务已关闭")

    def start(self):
        if not self.monitor_thread.is_alive():
            self.monitor_thread.start()

    def stop(self):
        self.thread_running = False
        if self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2)


class LogVerboseMaskApp(QWidget):
    COMMANDS_FILE = os.path.join(APP_CACHE_DIR, "commands.json")
    
    # 添加设备变化信号
    device_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        # 确保缓存目录存在
        os.makedirs(APP_CACHE_DIR, exist_ok=True)
        self.specific_commands = self.load_commands()
        self.device_name_mapping = {}  # 设备ID到自定义名称的映射
        self.initUI()
        self.setup_logging()
        
        # 加载设备名称映射
        self.load_device_names()
        
        self.refresh_devices()  # 初始化时刷新设备列表
        
        # 初始化USB设备监控
        self.usb_monitor = USBDeviceMonitor(self.on_device_changed)
        self.usb_monitor.start()
        
        # 连接设备变化信号到刷新函数
        self.device_changed.connect(self.refresh_devices)
        
        # 设置定时器定期刷新设备列表（作为备用方案）
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_devices)
        self.refresh_timer.start(5000)  # 每5秒刷新一次

    def load_commands(self):
        """从文件加载命令"""
        # 确保缓存目录存在
        os.makedirs(APP_CACHE_DIR, exist_ok=True)
        if os.path.exists(self.COMMANDS_FILE):
            try: # 添加 try-except 块处理可能的 JSONDecodeError
                with open(self.COMMANDS_FILE, "r", encoding="utf-8") as file:
                    return json.load(file)
            except json.JSONDecodeError:
                # print(f"警告：无法解析 {self.COMMANDS_FILE}，将使用默认命令。")
                return self.get_default_commands() # 返回默认命令
        else:
            # 如果文件不存在，使用默认命令
            return self.get_default_commands() # 返回默认命令

    def get_default_commands(self): # 新增一个方法来返回默认命令
        """返回默认命令字典"""
        return {
            "HDR": [
                "adb shell setenforce 0",
                'adb shell "mkdir /data/local/tmp/morpho/image_refiner/dump -p"',
                'adb shell "chmod 777 /data/local/tmp/morpho/image_refiner/dump"',
                "adb shell setprop debug.morpho.image_refiner.enable 1",
                "adb shell setprop debug.morpho.image_refiner.dump 3",
                "adb shell setprop debug.morpho.image_refiner.dump_path /data/local/tmp/morpho/image_refiner/dump",
                "adb shell setprop debug.morpho.image_refiner.enable 1",
                "adb shell setprop debug.morpho.image_refiner.draw_logo 1",
            ],
            "超夜": [
                "adb shell setprop persist.vendor.camera.siq.dump 1",
                "adb shell setprop vendor.camera.siq.dump_input_output 1",
            ],
            "Kill": [
                "adb shell input keyevent 3",
                "adb shell \"for pid in $(ps -A | grep vendor.qti.camera.provider@2.7-service_64 | awk '{print $2}'); do kill $pid; done\"",
                "adb shell \"for pid in $(ps -A | grep android.hardware.camera.provider@2.4-service_64 | awk '{print $2}'); do kill $pid; done\"",
                "adb shell \"for pid in $(ps -A | grep cameraserver | awk '{print $2}'); do kill $pid; done\"",
                "adb shell \"for pid in $(ps -A | grep com.android.camera | awk '{print $2}'); do kill $pid; done\"",
                'adb shell "kill $(pidof camerahalserver)"',
                'adb shell "kill $(pidof cameraserver)"',
                "adb shell pkill camera*",
            ],
            "3A": [
                'adb shell "echo enable3ADebugData=TRUE >> /vendor/etc/camera/camxoverridesettings.txt"',
                'adb shell "echo enableTuningMetadata=TRUE >> /vendor/etc/camera/camxoverridesettings.txt"',
                'adb shell "echo dumpSensorEEPROMData=TRUE >> /vendor/etc/camera/camxoverridesettings.txt"',
                'adb shell "echo logCoreCfgMask=0x2780ba >> /vendor/etc/camera/camxoverridesettings.txt"',
                'adb shell "echo reprocessDump=TRUE >> /vendor/etc/camera/camxoverridesettings.txt"',
            ],
            "离线log": [
                'adb shell "echo enableAsciiLogging=1 >> /vendor/etc/camera/camxoverridesettings.txt"',
                'adb shell "echo logWarningMask=0x10080  >> /vendor/etc/camera/camxoverridesettings.txt"',
                'adb shell "echo logVerboseMask=0x10080  >> /vendor/etc/camera/camxoverridesettings.txt"',
                'adb shell "echo logInfoMask=0x10080  >> /vendor/etc/camera/camxoverridesettings.txt"',
                'adb shell "echo logConfigMask=0x10080  >> /vendor/etc/camera/camxoverridesettings.txt"',
                'adb shell "echo logEntryExitMask=0x10080  >> /vendor/etc/camera/camxoverridesettings.txt"',
            ],
        }

    def save_commands(self):
        """将命令保存到文件"""
        # 确保缓存目录存在
        os.makedirs(APP_CACHE_DIR, exist_ok=True)
        try: # 添加 try-except 块处理可能的写入错误
            with open(self.COMMANDS_FILE, "w", encoding="utf-8") as file:
                json.dump(self.specific_commands, file, ensure_ascii=False, indent=4)
        except IOError as e:
            # print(f"错误：无法写入配置文件 {self.COMMANDS_FILE}: {e}")
            QMessageBox.warning(self, "保存错误", f"""无法保存命令配置到:{self.COMMANDS_FILE}错误: {e}""")

    def load_device_names(self):
        """从INI文件加载设备名称映射"""
        ini_path = os.path.join(APP_CACHE_DIR, "bat_filepath.ini")
        try:
            if os.path.exists(ini_path):
                # 直接读取文件内容，专门查找[devices]节
                with open(ini_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 查找[devices]节
                import re
                devices_pattern = r'\[devices\](.*?)(?=\[|$)'
                match = re.search(devices_pattern, content, re.DOTALL)
                
                if match:
                    devices_content = match.group(1).strip()
                    for line in devices_content.split('\n'):
                        line = line.strip()
                        if '=' in line:
                            device_id, custom_name = line.split('=', 1)
                            device_id = device_id.strip()
                            custom_name = custom_name.strip()
                            if device_id and custom_name:
                                self.device_name_mapping[device_id] = custom_name
        except Exception as e:
            print(f"加载设备名称映射时出错: {e}")

    def save_device_names(self):
        """保存设备名称映射到INI文件"""
        ini_path = os.path.join(APP_CACHE_DIR, "bat_filepath.ini")
        try:
            os.makedirs(APP_CACHE_DIR, exist_ok=True)
            
            # 读取现有文件内容
            content = ""
            if os.path.exists(ini_path):
                with open(ini_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            
            # 使用正则表达式查找[devices]节
            import re
            devices_pattern = r'\[devices\](.*?)(?=\[|$)'
            match = re.search(devices_pattern, content, re.DOTALL)
            
            # 构建新的[devices]节内容
            devices_content = "\n"
            for device_id, custom_name in self.device_name_mapping.items():
                devices_content += f"{device_id}={custom_name}\n"
            
            if match:
                # 如果[devices]节存在，替换它
                new_content = content[:match.start()] + f"[devices]{devices_content}" + content[match.end():]
            else:
                # 如果[devices]节不存在，在文件末尾添加
                if not content.endswith('\n'):
                    content += '\n'
                new_content = content + f"[devices]{devices_content}"
            
            # 写入文件
            with open(ini_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            # 同步到下载界面（如果存在）
            if hasattr(self, 'download_dialog') and hasattr(self.download_dialog, 'device_name_mapping'):
                self.download_dialog.device_name_mapping.update(self.device_name_mapping)
                # 刷新下载界面的设备列表
                if hasattr(self.download_dialog, 'refresh_devices'):
                    self.download_dialog.refresh_devices()
                
        except Exception as e:
            print(f"保存设备名称映射时出错: {e}")

    def get_device_display_name(self, device_id):
        """获取设备的显示名称（自定义名称或原始ID）"""
        return self.device_name_mapping.get(device_id, device_id)

    def get_device_original_id(self, display_name):
        """根据显示名称获取原始设备ID"""
        # 如果显示名称就是原始ID，直接返回
        if hasattr(self, 'devices') and display_name in self.devices:
            return display_name
        
        # 否则查找自定义名称对应的原始ID
        for device_id, custom_name in self.device_name_mapping.items():
            if custom_name == display_name:
                return device_id
        
        return display_name

    def edit_device_name(self, device_id):
        """编辑设备名称"""
        current_name = self.device_name_mapping.get(device_id, device_id)
        new_name, ok = QInputDialog.getText(
            self, 
            "重命名设备", 
            f"为设备 {device_id} 输入自定义名称：", 
            text=current_name
        )
        
        if ok and new_name.strip():
            new_name = new_name.strip()
            
            # 检查名称是否已被其他设备使用
            if new_name in self.device_name_mapping.values() and new_name != current_name:
                QMessageBox.warning(self, "错误", "该名称已被其他设备使用，请选择其他名称。")
                return
            
            # 更新映射
            if new_name == device_id:
                # 如果名称与原始ID相同，删除映射
                self.device_name_mapping.pop(device_id, None)
            else:
                # 否则保存新名称
                self.device_name_mapping[device_id] = new_name
            
            # 保存到INI文件
            self.save_device_names()
            
            # 刷新设备显示
            self.refresh_devices()

    def edit_current_device_name(self):
        """编辑当前选中设备的名称"""
        selected_device = self.get_selected_device()
        if not selected_device:
            QMessageBox.warning(self, "设备错误", "请先选择有效的ADB设备！")
            return
        
        self.edit_device_name(selected_device)

    def refresh_devices(self):
        """刷新ADB设备列表"""
        try:
            # 使用 startupinfo 来隐藏命令行窗口
            startupinfo = None
            if hasattr(subprocess, 'STARTUPINFO'):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            
            result = subprocess.run(
                ['adb', 'devices'], 
                capture_output=True, 
                text=True, 
                encoding='utf-8',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]  # 跳过第一行标题
                devices = []
                for line in lines:
                    if line.strip() and '\t' in line:
                        device_id, status = line.strip().split('\t')
                        if status == 'device':  # 只添加已连接的设备
                            devices.append(device_id)
                            # print(f"[设备刷新] 获取到设备: {device_id}")
                
                # 更新设备下拉列表
                current_device = self.device_combo.currentText() if self.device_combo.count() > 0 else ""
                self.device_combo.clear()
                
                if devices:
                    for device in devices:
                        # 显示自定义名称或原始ID
                        display_name = self.get_device_display_name(device)
                        self.device_combo.addItem(display_name, device)  # 存储原始ID作为数据
                    
                    # 尝试保持之前选中的设备
                    if current_device:
                        # 查找当前显示名称对应的设备
                        for i in range(self.device_combo.count()):
                            if self.device_combo.itemText(i) == current_device:
                                self.device_combo.setCurrentIndex(i)
                                break
                        else:
                            # 如果没找到，选择第一个
                            self.device_combo.setCurrentIndex(0)
                    else:
                        self.device_combo.setCurrentIndex(0)
                    
                    self.device_combo.setEnabled(True)  # 确保有设备时启用下拉列表
                    # print(f"[设备刷新] 检测到 {len(devices)} 台设备")
                else:
                    self.device_combo.addItem("未检测到设备")
                    self.device_combo.setEnabled(False)
                    # print("[设备刷新] 未检测到设备")
            else:
                self.device_combo.clear()
                self.device_combo.addItem("ADB命令执行失败")
                self.device_combo.setEnabled(False)
                # print("[设备刷新] ADB命令执行失败")
        except Exception as e:
            self.device_combo.clear()
            self.device_combo.addItem(f"错误: {str(e)}")
            self.device_combo.setEnabled(False)
            # print(f"[设备刷新] 发生错误: {str(e)}")

    def get_selected_device(self):
        """获取当前选中的设备ID"""
        if not self.device_combo.isEnabled():
            return None
        
        current_index = self.device_combo.currentIndex()
        if current_index < 0:
            return None
        
        # 获取当前选中项的数据（原始设备ID）
        device_id = self.device_combo.itemData(current_index)
        if device_id is None:
            # 如果没有数据，使用显示文本
            current_text = self.device_combo.currentText()
            if current_text in ["未检测到设备", "ADB命令执行失败"]:
                return None
            # 根据显示名称查找原始设备ID
            device_id = self.get_device_original_id(current_text)
        
        return device_id

    def switch_usb_mode(self, mode_name, usb_function):
        """切换USB模式"""
        selected_device = self.get_selected_device()
        if not selected_device:
            QMessageBox.warning(self, "设备错误", "请先选择有效的ADB设备！")
            return
        
        try:
            if usb_function:
                # 有USB功能参数的情况（文件传输或传输照片）
                command = f"adb -s {selected_device} shell svc usb setFunctions {usb_function}"
            else:
                # 仅充电模式（无参数）
                command = f"adb -s {selected_device} shell svc usb setFunctions"
            
            # print(f"执行USB模式切换命令: {command}")
            
            # 执行命令
            # 使用 startupinfo 来隐藏命令行窗口
            startupinfo = None
            if hasattr(subprocess, 'STARTUPINFO'):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True, 
                encoding='utf-8',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            
            if result.returncode == 0:
                QMessageBox.information(self, "成功", f"USB模式已切换到: {mode_name}")
                # print(f"USB模式切换成功: {mode_name}")
            else:
                error_msg = result.stderr.strip() if result.stderr else "未知错误"
                QMessageBox.warning(self, "执行失败", f"切换USB模式失败: {error_msg}")
                # print(f"USB模式切换失败: {error_msg}")
                
        except Exception as e:
            error_msg = f"执行USB模式切换时出错: {str(e)}"
            QMessageBox.critical(self, "错误", error_msg)
            # print(error_msg)

    def initUI(self):
        self.setWindowTitle("Bat脚本执行")
        self.resize(1200, 900)
        icon_path = os.path.join(os.path.dirname(__file__), "icon", "bat.ico")
        self.setWindowIcon(QIcon(icon_path))
        self.mask_value = 0x00000000

        # 创建主布局
        main_layout = QVBoxLayout()

        # 创建设备选择区域
        device_layout = QHBoxLayout()
        device_label = QLabel("选择设备:")
        self.device_combo = QComboBox()
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self.refresh_devices)
        
        # 添加编辑设备名称按钮
        edit_device_button = QPushButton("编辑设备名称")
        edit_device_button.clicked.connect(self.edit_current_device_name)
        
        # 添加USB功能切换按钮
        usb_label = QLabel("USB模式:")
        only_charge_button = QPushButton("仅充电")
        file_transfer_button = QPushButton("文件传输")
        photo_transfer_button = QPushButton("传输照片")
        
        # 连接按钮信号
        only_charge_button.clicked.connect(lambda: self.switch_usb_mode("仅充电", ""))
        file_transfer_button.clicked.connect(lambda: self.switch_usb_mode("文件传输", "mtp"))
        photo_transfer_button.clicked.connect(lambda: self.switch_usb_mode("传输照片", "ptp"))
        
        device_layout.addWidget(device_label)
        device_layout.addWidget(self.device_combo)
        device_layout.addWidget(refresh_button)
        device_layout.addWidget(edit_device_button)
        device_layout.addWidget(usb_label)
        device_layout.addWidget(only_charge_button)
        device_layout.addWidget(file_transfer_button)
        device_layout.addWidget(photo_transfer_button)
        device_layout.addStretch()  # 添加弹性空间
        
        main_layout.addLayout(device_layout)

        # 创建 QSplitter
        splitter = QSplitter(Qt.Horizontal)

        # 创建显示数值的文本框
        self.mask_display = QTextEdit()
        splitter.addWidget(self.mask_display)

        # 将 QSplitter 添加到主布局
        main_layout.addWidget(splitter)

        # 创建水平布局以在同一行显示按钮
        button_layout = QHBoxLayout()

        # 创建运行按钮
        run_button = QPushButton("运行")
        run_button.clicked.connect(self.execute_adb_commands)
        button_layout.addWidget(run_button)

        # 创建批量执行按钮
        batch_run_button = QPushButton("批量执行")
        batch_run_button.clicked.connect(self.batch_execute_adb_commands)
        button_layout.addWidget(batch_run_button)

        # 创建下载按钮
        download_button = QPushButton("下载")
        download_button.clicked.connect(self.open_download_window)
        button_layout.addWidget(download_button)

        # 创建新增按钮
        add_button = QPushButton("新增")
        add_button.clicked.connect(self.add_new_script)
        button_layout.addWidget(add_button)
        
        # 创建原生运行按钮
        native_run_button = QPushButton("原生运行")
        native_run_button.clicked.connect(self.native_run_script)
        button_layout.addWidget(native_run_button)
        # 将按钮布局添加到主布局
        main_layout.addLayout(button_layout)

        # 创建复选框布局
        grid_layout = QGridLayout()

        # 添加第一个标签
        script_label = QLabel("高通脚本：")
        grid_layout.addWidget(script_label, 0, 0, 1, 4)

        # 初始化脚本复选框列表
        self.script_checkboxes = []

        # 添加脚本复选框
        script_labels = [
            "Sensor",
            "Application",
            "IQ module",
            "IFace",
            "Utilities",
            "LMME",
            "ISP",
            "Sync",
            "NCS",
            "Post Processor",
            "MemSpy",
            "Metadata",
            "Image Lib",
            "Asserts",
            "AEC",
            "CPP",
            "Core",
            "AWB",
            "HAL",
            "HWI",
            "AF",
            "JPEG",
            "CHI",
            "DRQ",
            "Stats",
            "FD",
            "CSL",
            "FD",
        ]
        for i, label in enumerate(script_labels):
            checkbox = QCheckBox(label)
            checkbox.stateChanged.connect(self.update_script_mask)
            row = (i // 4) + 1  # 从第1行开始
            col = i % 4
            grid_layout.addWidget(checkbox, row, col)
            self.script_checkboxes.append(checkbox)

        # 添加第二个标签
        command_label = QLabel("自定义脚本：")
        command_start_row = (len(script_labels) // 4) + 1
        grid_layout.addWidget(command_label, command_start_row, 0, 1, 4)  # 占据一整行

        # 初始化命令复选框列表
        self.command_checkboxes = []

        # 动态添加命令复选框
        command_checkboxes = list(self.specific_commands.keys())  # 从加载的命令中获取键
        for i, label in enumerate(command_checkboxes):
            checkbox = QCheckBox(label)
            checkbox.stateChanged.connect(self.update_command_mask)
            checkbox.setContextMenuPolicy(Qt.CustomContextMenu)
            checkbox.customContextMenuRequested.connect(
                lambda pos, cb=checkbox: self.show_context_menu(pos, cb)
            )
            row = command_start_row + 1 + (i // 4)  # 从命令标签的下一行开始
            col = i % 4
            grid_layout.addWidget(checkbox, row, col)
            self.command_checkboxes.append(checkbox)

        main_layout.addLayout(grid_layout)
        self.setLayout(main_layout)

    def update_script_mask(self):
        """更新 script_label 下的复选框"""
        self.mask_value = 0x00000000
        commands = []
        # 定义每个标签对应的指令值
        command_values = [
            0x00000002,
            0x00000800,
            0x00200000,
            0x00000004,
            0x00001000,
            0x00400000,
            0x00000008,
            0x00002000,
            0x00800000,
            0x00000010,
            0x00004000,
            0x01000000,
            0x00000020,
            0x00008000,
            0x02000000,
            0x00000040,
            0x00010000,
            0x04000000,
            0x00000080,
            0x00020000,
            0x08000000,
            0x00000100,
            0x00040000,
            0x00080000,
            0x00000200,
            0x00100000,
            0x00000400,
            0x00100000,
        ]
        current_text = self.mask_display.toPlainText().split("\n")
        current_text = [line for line in current_text if line.strip()]  # 移除空行
        for i, checkbox in enumerate(self.script_checkboxes):
            command = f'adb shell "echo logVerboseMask=0x{command_values[i]:08X} >> /vendor/etc/camera/camxoverridesettings.txt"'
            if checkbox.isChecked():
                if i < len(command_values):
                    self.mask_value |= command_values[i]
                    if command not in current_text:
                        commands.append(command)
            else:
                if command in current_text:
                    current_text.remove(command)
        self.mask_display.setText("\n".join(current_text + commands))

    def update_command_mask(self):
        """更新 command_label 下的复选框"""
        commands = []
        current_text = self.mask_display.toPlainText().split("\n")
        current_text = [line for line in current_text if line.strip()]  # 移除空行
        # print(f"update_command_mask - 当前文本框内容: {current_text}")
        
        for checkbox in self.command_checkboxes:
            command_list = self.specific_commands.get(checkbox.text(), [])
            
            if checkbox.isChecked():
                for command in command_list:
                    if command not in current_text:
                        # print(f"update_command_mask - 添加命令: {command}")

                        commands.append(command)
                    else:
                        print(f"update_command_mask - 命令已存在，跳过: {command}")
            else:
                for command in command_list:
                    if command in current_text:
                        # print(f"update_command_mask - 移除命令: {command}")
                        current_text.remove(command)
        
        final_commands = current_text + commands
        # print(f"update_command_mask - 最终命令列表: {final_commands}")
        self.mask_display.setText("\n".join(final_commands))

    @pyqtSlot()
    def show_success_message(self):
        QMessageBox.information(self, "成功", "脚本执行成功！")

    def setup_logging(self):
        """移除日志记录设置"""
        pass

    def write(self, message):
        """移除日志消息写入"""
        pass

    def execute_adb_commands(self):
        # 首先检查设备连接状态
        selected_device = self.get_selected_device()
        print(f"execute_adb_commands - 选中的设备: {selected_device}")
        if not selected_device:
            QMessageBox.warning(self, "设备错误", "请先选择有效的ADB设备！")
            return
        
        # 检查设备是否仍然连接
        try:
            # 使用 startupinfo 来隐藏命令行窗口
            startupinfo = None
            if hasattr(subprocess, 'STARTUPINFO'):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            
            result = subprocess.run(
                ['adb', 'devices'], 
                capture_output=True, 
                text=True, 
                encoding='utf-8',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]
                devices = []
                for line in lines:
                    if line.strip() and '\t' in line:
                        device_id, status = line.strip().split('\t')
                        if status == 'device':
                            devices.append(device_id)
                
                if selected_device not in devices:
                    QMessageBox.warning(self, "设备错误", f"设备 {selected_device} 已断开连接，请重新选择设备！")
                    self.refresh_devices()
                    return
            else:
                QMessageBox.warning(self, "ADB错误", "无法获取设备列表，请检查ADB连接！")
                return
        except Exception as e:
            QMessageBox.warning(self, "ADB错误", f"检查设备状态时出错: {str(e)}")
            return

        def create_temp_bat(commands):
            """创建临时bat文件"""
            import tempfile

            with tempfile.NamedTemporaryFile(
                mode="w", delete=False, suffix=".bat", encoding="gbk"
            ) as f:
                f.write("@echo off\n")
                f.write("echo [INFO] 开始执行脚本...\n")
                f.write(f"echo [INFO] 目标设备: {selected_device}\n")
                f.write("\n".join(commands))
                f.write("\necho [INFO] 执行完成!\n")
                return f.name.replace("/", "\\")  # 确保Windows路径格式

        def run_commands_in_thread():
            # print(f"run_commands_in_thread - 开始收集命令，目标设备: {selected_device}")
            # 收集所有要执行的命令
            all_commands = []

            # ADB初始化命令（指定设备）
            all_commands.extend([
                f"adb -s {selected_device} root", 
                f"adb -s {selected_device} remount", 
                f"adb -s {selected_device} wait-for-device"
            ])

            # 添加文本框中的命令（指定设备）
            text_edit_commands = self.mask_display.toPlainText().split("\n")
            # print(f"run_commands_in_thread - 文本框中的命令: {text_edit_commands}")
            for cmd in text_edit_commands:
                if cmd.strip():
                    if cmd.startswith("adb shell"):
                        # 将 "adb shell" 替换为 "adb -s {selected_device} shell"
                        new_cmd = cmd.replace("adb shell", f"adb -s {selected_device} shell")
                        # print(f"run_commands_in_thread - 替换命令: {cmd} -> {new_cmd}")
                        all_commands.append(new_cmd)
                    elif cmd.startswith("adb "):
                        # 对所有其他 adb 命令添加设备号
                        new_cmd = cmd.replace("adb ", f"adb -s {selected_device} ", 1)
                        # print(f"run_commands_in_thread - 替换adb命令: {cmd} -> {new_cmd}")
                        all_commands.append(new_cmd)
                    else:
                        # print(f"run_commands_in_thread - 直接添加命令: {cmd}")
                        all_commands.append(cmd)

            # 添加特定命令（指定设备）
            for checkbox in self.command_checkboxes:
                if checkbox.isChecked() and checkbox.text() in self.specific_commands:
                    # print(f"处理复选框 '{checkbox.text()}' 的命令")
                    for cmd in self.specific_commands[checkbox.text()]:
                        # print(f"原始命令: {cmd}")
                        if cmd.startswith("adb shell"):
                            # 将 "adb shell" 替换为 "adb -s {selected_device} shell"
                            new_cmd = cmd.replace("adb shell", f"adb -s {selected_device} shell")
                            # print(f"替换后命令: {new_cmd}")
                            all_commands.append(new_cmd)
                        elif cmd.startswith("adb "):
                            # 对所有其他 adb 命令添加设备号
                            new_cmd = cmd.replace("adb ", f"adb -s {selected_device} ", 1)
                            # print(f"替换adb命令: {cmd} -> {new_cmd}")
                            all_commands.append(new_cmd)
                        else:
                            # print(f"非adb命令，直接添加: {cmd}")
                            all_commands.append(cmd)

            # 添加查看配置文件的命令（指定设备）
            all_commands.append(
                f"adb -s {selected_device} shell cat /vendor/etc/camera/camxoverridesettings.txt"
            )

            # 生成临时bat文件
            # print(f"run_commands_in_thread - 最终命令列表: {all_commands}")
            bat_path = create_temp_bat(all_commands)

            try:
                # 执行bat文件
                # 使用 startupinfo 来隐藏命令行窗口
                startupinfo = None
                if hasattr(subprocess, 'STARTUPINFO'):
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE
                
                subprocess.run(
                    f'cmd /c "{bat_path}"', 
                    shell=True,
                    startupinfo=startupinfo,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                )
            finally:
                # 删除临时文件
                import os

                os.remove(bat_path)

            # 显示成功提示
            QMetaObject.invokeMethod(self, "show_success_message", Qt.QueuedConnection)

        # 创建并启动线程
        thread = threading.Thread(target=run_commands_in_thread)
        thread.start()

    def batch_execute_adb_commands(self):
        """批量执行ADB命令到所有连接的设备"""
        # 先刷新设备列表
        self.refresh_devices()
        
        # 获取当前连接的设备列表
        try:
            # 使用 startupinfo 来隐藏命令行窗口
            startupinfo = None
            if hasattr(subprocess, 'STARTUPINFO'):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            
            result = subprocess.run(
                ['adb', 'devices'], 
                capture_output=True, 
                text=True, 
                encoding='utf-8',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]
                devices = []
                for line in lines:
                    if line.strip() and '\t' in line:
                        device_id, status = line.strip().split('\t')
                        if status == 'device':  # 只添加已连接的设备
                            devices.append(device_id)
                
                if not devices:
                    QMessageBox.warning(self, "设备错误", "未检测到任何已连接的ADB设备！")
                    return
                
                # 显示确认对话框
                device_list = "\n".join([f"• {device}" for device in devices])
                reply = QMessageBox.question(
                    self, 
                    "批量执行确认", 
                    f"检测到 {len(devices)} 台设备:\n{device_list}\n\n确定要在所有设备上执行脚本吗？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                
                if reply == QMessageBox.Yes:
                    # 开始批量执行
                    self.start_batch_execution(devices)
                else:
                    print("用户取消了批量执行")
                    
            else:
                QMessageBox.warning(self, "ADB错误", "无法获取设备列表，请检查ADB连接！")
                return
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"获取设备列表时出错: {str(e)}")
            return

    def start_batch_execution(self, devices):
        """开始批量执行到多个设备"""
        def batch_execute_in_thread():
            total_devices = len(devices)
            success_count = 0
            failed_devices = []
            
            for i, device in enumerate(devices, 1):
                try:
                    print(f"[{i}/{total_devices}] 正在设备 {device} 上执行脚本...")
                    
                    # 收集要执行的命令
                    all_commands = []
                    
                    # ADB初始化命令（指定设备）
                    all_commands.extend([
                        f"adb -s {device} root", 
                        f"adb -s {device} remount", 
                        f"adb -s {device} wait-for-device"
                    ])

                    # 添加文本框中的命令（指定设备）
                    text_edit_commands = self.mask_display.toPlainText().split("\n")
                    for cmd in text_edit_commands:
                        if cmd.strip():
                            if cmd.startswith("adb shell"):
                                # 将 "adb shell" 替换为 "adb -s {device} shell"
                                new_cmd = cmd.replace("adb shell", f"adb -s {device} shell")
                                all_commands.append(new_cmd)
                            elif cmd.startswith("adb "):
                                # 对所有其他 adb 命令添加设备号
                                new_cmd = cmd.replace("adb ", f"adb -s {device} ", 1)
                                all_commands.append(new_cmd)
                            else:
                                all_commands.append(cmd)

                    # 添加特定命令（指定设备）
                    for checkbox in self.command_checkboxes:
                        if checkbox.isChecked() and checkbox.text() in self.specific_commands:
                            # print(f"批量执行 - 处理复选框 '{checkbox.text()}' 的命令")
                            for cmd in self.specific_commands[checkbox.text()]:
                                # print(f"批量执行 - 原始命令: {cmd}")
                                if cmd.startswith("adb shell"):
                                    # 将 "adb shell" 替换为 "adb -s {device} shell"
                                    new_cmd = cmd.replace("adb shell", f"adb -s {device} shell")
                                    # print(f"批量执行 - 替换后命令: {new_cmd}")
                                    all_commands.append(new_cmd)
                                elif cmd.startswith("adb "):
                                    # 对所有其他 adb 命令添加设备号
                                    new_cmd = cmd.replace("adb ", f"adb -s {device} ", 1)
                                    # print(f"批量执行 - 替换adb命令: {cmd} -> {new_cmd}")
                                    all_commands.append(new_cmd)
                                else:
                                    # print(f"批量执行 - 非adb命令，直接添加: {cmd}")
                                    all_commands.append(cmd)

                    # 添加查看配置文件的命令（指定设备）
                    all_commands.append(
                        f"adb -s {device} shell cat /vendor/etc/camera/camxoverridesettings.txt"
                    )

                    # 创建临时bat文件
                    bat_path = self.create_temp_bat_for_device(all_commands, device)
                    
                    try:
                        # 执行bat文件
                        # 使用 startupinfo 来隐藏命令行窗口
                        startupinfo = None
                        if hasattr(subprocess, 'STARTUPINFO'):
                            startupinfo = subprocess.STARTUPINFO()
                            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                            startupinfo.wShowWindow = subprocess.SW_HIDE
                        
                        result = subprocess.run(
                            f'cmd /c "{bat_path}"', 
                            shell=True, 
                            capture_output=True, 
                            text=True, 
                            encoding='gbk',
                            startupinfo=startupinfo,
                            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                        )
                        if result.returncode == 0:
                            print(f"设备 {device} 执行成功")
                            success_count += 1
                        else:
                            print(f"设备 {device} 执行失败: {result.stderr}")
                            failed_devices.append(device)
                    finally:
                        # 删除临时文件
                        import os
                        if os.path.exists(bat_path):
                            os.remove(bat_path)
                            
                except Exception as e:
                    print(f"设备 {device} 执行出错: {str(e)}")
                    failed_devices.append(device)
            
            # 显示批量执行结果
            QMetaObject.invokeMethod(self, "show_batch_execution_result", Qt.QueuedConnection,
                                   Q_ARG(int, success_count), 
                                   Q_ARG(int, total_devices), 
                                   Q_ARG(list, failed_devices))

        # 创建并启动线程
        thread = threading.Thread(target=batch_execute_in_thread)
        thread.start()

    def create_temp_bat_for_device(self, commands, device):
        """为指定设备创建临时bat文件"""
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".bat", encoding="gbk"
        ) as f:
            f.write("@echo off\n")
            f.write(f"echo [INFO] 开始执行脚本到设备: {device}\n")
            f.write("echo [INFO] 开始执行脚本...\n")
            f.write("\n".join(commands))
            f.write(f"\necho [INFO] 设备 {device} 执行完成!\n")
            return f.name.replace("/", "\\")  # 确保Windows路径格式

    @pyqtSlot(int, int, list)
    def show_batch_execution_result(self, success_count, total_count, failed_devices):
        """显示批量执行结果"""
        if failed_devices:
            failed_list = "\n".join([f"• {device}" for device in failed_devices])
            message = f"批量执行完成！\n\n成功: {success_count}/{total_count}\n\n失败的设备:\n{failed_list}"
            QMetaObject.invokeMethod(self, "show_batch_result_dialog", Qt.QueuedConnection, 
                                   Q_ARG(str, message), Q_ARG(bool, True))
        else:
            message = f"批量执行完成！\n\n所有 {total_count} 台设备都执行成功！"
            QMetaObject.invokeMethod(self, "show_batch_result_dialog", Qt.QueuedConnection, 
                                   Q_ARG(str, message), Q_ARG(bool, False))

    @pyqtSlot(str, bool)
    def show_batch_result_dialog(self, message, has_failures):
        """在主线程中显示批量执行结果对话框"""
        if has_failures:
            QMessageBox.information(self, "批量执行结果", message)
        else:
            QMessageBox.information(self, "批量执行结果", message)

    def show_context_menu(self, pos, checkbox):
        menu = QMenu(self)
        edit_action = menu.addAction("编辑命令")
        delete_action = menu.addAction("删除")
        rename_action = menu.addAction("重命名")
        action = menu.exec_(checkbox.mapToGlobal(pos))
        if action == edit_action:
            self.edit_command(checkbox.text())
        elif action == delete_action:
            self.delete_command(checkbox)
        elif action == rename_action:
            self.rename_command(checkbox)

    def edit_command(self, command_key):
        current_commands = self.specific_commands.get(command_key, [])
        if isinstance(current_commands, list):
            current_commands = "\n".join(current_commands)
        
        # 创建自定义编辑对话框
        dialog = ScriptEditDialog(self, command_key, current_commands)
        if dialog.exec_() == QDialog.Accepted:
            new_commands = dialog.get_content()
            if new_commands:
                self.specific_commands[command_key] = new_commands.split("\n")
                self.save_commands()

    def rename_command(self, checkbox):
        """重命名选中的命令复选框"""
        old_name = checkbox.text()
        new_name, ok = QInputDialog.getText(
            self, "重命名脚本", "输入新的脚本名称：", text=old_name
        )
        if ok and new_name:
            if new_name in self.specific_commands:
                QMessageBox.warning(self, "错误", "脚本名称已存在。")
                return
            # 更新 specific_commands 字典
            self.specific_commands[new_name] = self.specific_commands.pop(old_name)
            self.save_commands()
            # 更新复选框标签
            checkbox.setText(new_name)

    def add_new_script(self):
        dialog = ScriptInputDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            script_name, script_content = dialog.get_inputs()
            if script_name and script_content:
                self.specific_commands[script_name] = script_content.split("\n")
                self.save_commands()
                # 创建新的复选框
                new_checkbox = QCheckBox(script_name)
                new_checkbox.stateChanged.connect(
                    self.update_command_mask
                )  # 确保连接到 update_command_mask
                new_checkbox.setContextMenuPolicy(Qt.CustomContextMenu)
                new_checkbox.customContextMenuRequested.connect(
                    lambda pos, cb=new_checkbox: self.show_context_menu(pos, cb)
                )
                self.command_checkboxes.append(new_checkbox)  # 添加到命令复选框列表
                self.layout().addWidget(new_checkbox)
                # 重新排列命令复选框
                self.rearrange_command_checkboxes()

    def native_run_script(self):
        """原生运行：生成bat文件并直接运行"""
        # 首先检查设备连接状态
        selected_device = self.get_selected_device()
        if not selected_device:
            QMessageBox.warning(self, "设备错误", "请先选择有效的ADB设备！")
            return
        
        # 检查设备是否仍然连接
        try:
            startupinfo = None
            if hasattr(subprocess, 'STARTUPINFO'):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            
            result = subprocess.run(
                ['adb', 'devices'], 
                capture_output=True, 
                text=True, 
                encoding='utf-8',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]
                devices = []
                for line in lines:
                    if line.strip() and '\t' in line:
                        device_id, status = line.strip().split('\t')
                        if status == 'device':
                            devices.append(device_id)
                
                if selected_device not in devices:
                    QMessageBox.warning(self, "设备错误", f"设备 {selected_device} 已断开连接，请重新选择设备！")
                    self.refresh_devices()
                    return
            else:
                QMessageBox.warning(self, "ADB错误", "无法获取设备列表，请检查ADB连接！")
                return
        except Exception as e:
            QMessageBox.warning(self, "ADB错误", f"检查设备状态时出错: {str(e)}")
            return

        # 收集所有要执行的命令
        all_commands = []

        # ADB初始化命令（指定设备）
        all_commands.extend([
            f"adb -s {selected_device} root", 
            f"adb -s {selected_device} remount", 
            f"adb -s {selected_device} wait-for-device"
        ])

        # 添加文本框中的命令（指定设备）
        text_edit_commands = self.mask_display.toPlainText().split("\n")
        for cmd in text_edit_commands:
            if cmd.strip():
                if cmd.startswith("adb shell"):
                    # 将 "adb shell" 替换为 "adb -s {selected_device} shell"
                    new_cmd = cmd.replace("adb shell", f"adb -s {selected_device} shell")
                    all_commands.append(new_cmd)
                elif cmd.startswith("adb "):
                    # 对所有其他 adb 命令添加设备号
                    new_cmd = cmd.replace("adb ", f"adb -s {selected_device} ", 1)
                    all_commands.append(new_cmd)
                else:
                    all_commands.append(cmd)

        # 添加特定命令（指定设备）
        for checkbox in self.command_checkboxes:
            if checkbox.isChecked() and checkbox.text() in self.specific_commands:
                for cmd in self.specific_commands[checkbox.text()]:
                    if cmd.startswith("adb shell"):
                        # 将 "adb shell" 替换为 "adb -s {selected_device} shell"
                        new_cmd = cmd.replace("adb shell", f"adb -s {selected_device} shell")
                        all_commands.append(new_cmd)
                    elif cmd.startswith("adb "):
                        # 对所有其他 adb 命令添加设备号
                        new_cmd = cmd.replace("adb ", f"adb -s {selected_device} ", 1)
                        all_commands.append(new_cmd)
                    else:
                        all_commands.append(cmd)

        # 添加查看配置文件的命令（指定设备）
        all_commands.append(
            f"adb -s {selected_device} shell cat /vendor/etc/camera/camxoverridesettings.txt"
        )

        # 生成bat文件
        import tempfile
        import datetime
        
        # 创建带时间戳的文件名
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        device_display_name = self.get_device_display_name(selected_device)
        bat_filename = f"bat_script_{device_display_name}_{timestamp}.bat"
        
        # 确保缓存目录存在
        os.makedirs(APP_CACHE_DIR, exist_ok=True)
        bat_path = os.path.join(APP_CACHE_DIR, bat_filename)
        
        try:
            # 创建bat文件（使用ANSI编码，避免中文乱码）
            with open(bat_path, "w", encoding="gbk") as f:
                f.write("@echo off\n")
                f.write("chcp 936 >nul\n")  # 设置GBK编码，支持中文显示
                f.write("title Bat脚本执行 - {device_display_name}\n")  # 设置窗口标题
                f.write("color 0A\n")  # 设置颜色：黑底绿字
                f.write("echo ========================================\n")
                f.write("echo            Bat脚本执行器\n")
                f.write("echo ========================================\n")
                f.write("echo.\n")
                f.write(f"echo [INFO] 目标设备: {selected_device}\n")
                f.write(f"echo [INFO] 设备显示名称: {device_display_name}\n")
                f.write(f"echo [INFO] 脚本生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("echo [INFO] 开始执行脚本...\n")
                f.write("echo.\n")
                f.write("echo ========================================\n")
                f.write("echo            执行命令列表\n")
                f.write("echo ========================================\n")
                f.write("\n".join(all_commands))
                f.write("\necho.\n")
                f.write("echo ========================================\n")
                f.write("echo            执行完成\n")
                f.write("echo ========================================\n")
                f.write("echo.\n")
                f.write("echo 按任意键关闭窗口...\n")
                f.write("pause >nul\n")  # 静默暂停，不显示"请按任意键继续..."
            
            # 显示成功消息
            QMessageBox.information(self, "脚本生成成功", 
                                  f"bat脚本已生成：\n{bat_path}\n\n即将运行此脚本...")
            
            # 直接运行bat文件（调用Windows cmd窗口）
            # 使用os.startfile直接打开bat文件，这样会使用系统默认的cmd窗口
            try:
                # 方法1：使用os.startfile直接打开bat文件（推荐）
                os.startfile(bat_path)
            except Exception as e:
                # 方法2：如果os.startfile失败，使用subprocess调用cmd
                try:
                    startupinfo = None
                    if hasattr(subprocess, 'STARTUPINFO'):
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        startupinfo.wShowWindow = 1  # 1 = SW_SHOW，显示窗口
                    
                    # 使用线程异步执行，避免阻塞主界面
                    def run_bat_async():
                        try:
                            # 使用cmd /k 保持窗口打开，让用户看到执行结果
                            subprocess.run(
                                f'cmd /k "{bat_path}"', 
                                shell=True,
                                startupinfo=startupinfo
                            )
                        except Exception as e:
                            print(f"运行bat脚本时出错: {e}")
                    
                    # 创建并启动线程
                    import threading
                    bat_thread = threading.Thread(target=run_bat_async)
                    bat_thread.daemon = True  # 设置为守护线程
                    bat_thread.start()
                    
                except Exception as subprocess_error:
                    print(f"subprocess调用失败: {subprocess_error}")
                    # 方法3：最后的备选方案，使用start命令
                    try:
                        os.system(f'start "{bat_filename}" "{bat_path}"')
                    except Exception as start_error:
                        print(f"start命令也失败: {start_error}")
                        QMessageBox.warning(self, "警告", f"无法自动运行bat脚本，请手动运行：\n{bat_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成或运行bat脚本时出错：\n{str(e)}")

    def delete_command(self, checkbox):
        command_key = checkbox.text()
        # 移除命令
        if command_key in self.specific_commands:
            del self.specific_commands[command_key]
            self.save_commands()
        
        # 从界面移除复选框
        # 查找正确的网格布局
        grid_layout = None
        main_layout = self.layout()
        for i in range(main_layout.count()):
            item = main_layout.itemAt(i)
            if item.layout():
                if isinstance(item.layout(), QGridLayout):
                    grid_layout = item.layout()
                    break
        
        if grid_layout:
            grid_layout.removeWidget(checkbox)
        checkbox.deleteLater()
        
        # 从命令复选框列表中移除
        self.command_checkboxes.remove(checkbox)
        # 重新排列命令复选框
        self.rearrange_command_checkboxes()
        # 更新 mask
        self.update_script_mask()

    def rearrange_command_checkboxes(self):
        """重新排列 command_label 下的命令复选框"""
        # 查找正确的网格布局
        grid_layout = None
        main_layout = self.layout()
        for i in range(main_layout.count()):
            item = main_layout.itemAt(i)
            if item.layout():
                if isinstance(item.layout(), QGridLayout):
                    grid_layout = item.layout()
                    break
        
        if grid_layout:
            # 清除当前布局中的所有命令复选框
            for i in reversed(range(grid_layout.count())):
                widget = grid_layout.itemAt(i).widget()
                if isinstance(widget, QCheckBox) and widget in self.command_checkboxes:
                    grid_layout.removeWidget(widget)

            # 重新添加命令复选框
            columns = 4
            command_start_row = (len(self.script_checkboxes) // 4) + 2
            for index, checkbox in enumerate(self.command_checkboxes):
                row = command_start_row + 1 + (index // columns)
                col = index % columns
                grid_layout.addWidget(checkbox, row, col)
            
            # 强制更新界面
            grid_layout.update()
            self.update()
            self.repaint()
        else:
            print("错误：未找到网格布局")

    def on_device_changed(self):
        """设备变化回调函数"""
        # 在主线程中发送信号
        self.device_changed.emit()

    def open_download_window(self):
        """打开文件下载窗口"""
        self.download_dialog = FileDownloadDialog(self)
        self.download_dialog.show()

    def closeEvent(self, event):
        """窗口关闭事件处理"""
        # 停止USB监控
        if hasattr(self, 'usb_monitor'):
            self.usb_monitor.stop()
        
        # 停止定时器
        if hasattr(self, 'refresh_timer'):
            self.refresh_timer.stop()
        
        event.accept()

    def keyPressEvent(self, event):
        """按下 Esc 键关闭窗口"""
        if event.key() == Qt.Key_Escape:
            self.close()


class ScriptInputDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新增脚本")
        
        # 设置对话框大小
        self.resize(900, 600)
        self.setMinimumSize(500, 400)

        # 创建布局
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        # 创建脚本名称标签和输入框
        name_label = QLabel("输入脚本名:")
        layout.addWidget(name_label)
        
        self.script_name_input = QLineEdit(self)
        self.script_name_input.setPlaceholderText("请输入脚本名称")
        self.script_name_input.setMinimumHeight(30)
        layout.addWidget(self.script_name_input)

        # 创建脚本内容标签和输入框
        content_label = QLabel("输入脚本内容:")
        layout.addWidget(content_label)
        
        self.script_content_input = QTextEdit(self)
        self.script_content_input.setPlaceholderText("请输入脚本内容，每行一个命令")
        self.script_content_input.setMinimumHeight(300)
        layout.addWidget(self.script_content_input)

        # 创建按钮
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def get_inputs(self):
        return self.script_name_input.text(), self.script_content_input.toPlainText()


class ScriptEditDialog(QDialog):
    def __init__(self, parent=None, script_name="", script_content=""):
        super().__init__(parent)
        self.setWindowTitle(f"编辑脚本 - {script_name}")
        
        # 设置对话框大小
        self.resize(900, 600)
        self.setMinimumSize(500, 400)

        # 创建布局
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        # 创建脚本名称标签（只读显示）
        name_label = QLabel(f"脚本名称: {script_name}")
        name_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        layout.addWidget(name_label)

        # 创建脚本内容标签和输入框
        content_label = QLabel("脚本内容:")
        layout.addWidget(content_label)
        
        self.script_content_input = QTextEdit(self)
        self.script_content_input.setPlaceholderText("请输入脚本内容，每行一个命令")
        self.script_content_input.setMinimumHeight(400)
        self.script_content_input.setText(script_content)
        layout.addWidget(self.script_content_input)

        # 创建按钮
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def get_content(self):
        return self.script_content_input.toPlainText()


class FileDownloadDialog(QDialog):
    """文件下载对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("从相机/储存卡下载照片")
        self.resize(800, 600)
        self.setMinimumSize(600, 500)
        
        # 设置图标
        icon_path = os.path.join(os.path.dirname(__file__), "icon", "file_down.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        # 初始化变量
        self.selected_source_paths = []
        self.selected_destination_path = ""
        self.devices = []
        self.top_folder_checkboxes = []
        self.device_name_mapping = {}  # 设备ID到自定义名称的映射
        self.device_checkboxes = {}  # 设备ID到复选框的映射
        
        # 创建界面
        self.initUI()
        
        # 加载设备名称映射
        self.load_device_names()
        
        # 刷新设备列表
        self.refresh_devices()
        
        # 设置定时器定期刷新设备列表
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_devices)
        self.refresh_timer.start(5000)  # 每5秒刷新一次

    def load_device_names(self):
        """从INI文件加载设备名称映射"""
        ini_path = self.get_ini_path()
        try:
            if os.path.exists(ini_path):
                # 直接读取文件内容，专门查找[devices]节
                with open(ini_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 查找[devices]节
                import re
                devices_pattern = r'\[devices\](.*?)(?=\[|$)'
                match = re.search(devices_pattern, content, re.DOTALL)
                
                if match:
                    devices_content = match.group(1).strip()
                    for line in devices_content.split('\n'):
                        line = line.strip()
                        if '=' in line:
                            device_id, custom_name = line.split('=', 1)
                            device_id = device_id.strip()
                            custom_name = custom_name.strip()
                            if device_id and custom_name:
                                self.device_name_mapping[device_id] = custom_name
                        
                # 同步主界面的设备名称映射
                if hasattr(self.parent, 'device_name_mapping'):
                    for device_id, custom_name in self.parent.device_name_mapping.items():
                        if device_id not in self.device_name_mapping:
                            self.device_name_mapping[device_id] = custom_name
        except Exception as e:
            print(f"加载设备名称映射时出错: {e}")

    def save_device_names(self):
        """保存设备名称映射到INI文件"""
        ini_path = self.get_ini_path()
        try:
            os.makedirs(APP_CACHE_DIR, exist_ok=True)
            
            # 读取现有文件内容
            content = ""
            if os.path.exists(ini_path):
                with open(ini_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            
            # 使用正则表达式查找[devices]节
            import re
            devices_pattern = r'\[devices\](.*?)(?=\[|$)'
            match = re.search(devices_pattern, content, re.DOTALL)
            
            # 构建新的[devices]节内容
            devices_content = "\n"
            for device_id, custom_name in self.device_name_mapping.items():
                devices_content += f"{device_id}={custom_name}\n"
            
            if match:
                # 如果[devices]节存在，替换它
                new_content = content[:match.start()] + f"[devices]{devices_content}" + content[match.end():]
            else:
                # 如果[devices]节不存在，在文件末尾添加
                if not content.endswith('\n'):
                    content += '\n'
                new_content = content + f"[devices]{devices_content}"
            
            # 写入文件
            with open(ini_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            # 同步到主界面的设备名称映射
            if hasattr(self.parent, 'device_name_mapping'):
                self.parent.device_name_mapping.update(self.device_name_mapping)
                # 刷新主界面的设备列表
                if hasattr(self.parent, 'refresh_devices'):
                    self.parent.refresh_devices()
                
        except Exception as e:
            print(f"保存设备名称映射时出错: {e}")

    def get_device_display_name(self, device_id):
        """获取设备的显示名称（自定义名称或原始ID）"""
        return self.device_name_mapping.get(device_id, device_id)

    def get_device_original_id(self, display_name):
        """根据显示名称获取原始设备ID"""
        # 如果显示名称就是原始ID，直接返回
        if hasattr(self, 'devices') and display_name in self.devices:
            return display_name
        
        # 否则查找自定义名称对应的原始ID
        for device_id, custom_name in self.device_name_mapping.items():
            if custom_name == display_name:
                return device_id
        
        return display_name

    def edit_device_name(self, device_id):
        """编辑设备名称"""
        current_name = self.device_name_mapping.get(device_id, device_id)
        new_name, ok = QInputDialog.getText(
            self, 
            "重命名设备", 
            f"为设备 {device_id} 输入自定义名称：", 
            text=current_name
        )
        
        if ok and new_name.strip():
            new_name = new_name.strip()
            
            # 检查名称是否已被其他设备使用
            if new_name in self.device_name_mapping.values() and new_name != current_name:
                QMessageBox.warning(self, "错误", "该名称已被其他设备使用，请选择其他名称。")
                return
            
            # 更新映射
            if new_name == device_id:
                # 如果名称与原始ID相同，删除映射
                self.device_name_mapping.pop(device_id, None)
            else:
                # 否则保存新名称
                self.device_name_mapping[device_id] = new_name
            
            # 保存到INI文件
            self.save_device_names()
            
            # 刷新设备显示
            self.refresh_devices()

    def load_fixed_source_paths(self):
        """读取固定路径与配置文件。优先从 [source] 节读取。
        支持三种格式：
        1) INI: [source] 下 paths= 多行；或 path1=, path2= ...
        2) 旧格式: [source] 下直接逐行列出路径
        3) 若文件不存在或解析失败，返回默认列表
        返回: List[str]
        """
        ini_path = os.path.join(APP_CACHE_DIR, "bat_filepath.ini")
        default_paths = ["sdcard/dcim/camera/", "data/vendor/camera/"]
        default_target = os.path.expanduser("~/Pictures")

        try:
            os.makedirs(APP_CACHE_DIR, exist_ok=True)
            config = configparser.ConfigParser()

            if not os.path.exists(ini_path):
                # 初始化新格式 INI
                config["source"] = {"paths": "\n".join(default_paths)}
                config["target"] = {"path": default_target}
                with open(ini_path, "w", encoding="utf-8") as f:
                    config.write(f)
                return default_paths

            # 读取现有文件内容
            with open(ini_path, "r", encoding="utf-8") as f:
                content = f.read()

            paths: list = []
            try:
                # 优先尝试标准 INI 解析
                config.read_string(content)
                if config.has_section("source"):
                    if config.has_option("source", "paths"):
                        raw = config.get("source", "paths")
                        for line in raw.splitlines():
                            p = line.strip()
                            if p:
                                paths.append(p.lstrip("/"))
                    else:
                        for key, val in config.items("source"):
                            if key.lower().startswith("path"):
                                p = val.strip()
                                if p:
                                    paths.append(p.lstrip("/"))
            except configparser.Error:
                # 标准解析失败则走旧格式解析
                pass

            if not paths:
                # 旧格式: 读取 [source] 节中的逐行内容
                paths = self._read_legacy_section_lines("source")

            return paths or default_paths
        except Exception:
            return default_paths

    def get_ini_path(self):
        return os.path.join(APP_CACHE_DIR, "bat_filepath.ini")

    def _read_legacy_section_lines(self, section_name):
        """从旧格式 INI 中读取某个节下的逐行内容（无 key=value）。"""
        ini_path = self.get_ini_path()
        lines = []
        try:
            in_section = False
            with open(ini_path, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    if line.startswith("[") and line.endswith("]"):
                        in_section = (line[1:-1].strip().lower() == section_name.lower())
                        continue
                    if in_section and not line.startswith("#"):
                        lines.append(line)
        except Exception:
            return []
        return lines

    def load_target_path(self):
        """读取 [target] 的本地保存路径，若无则返回默认图片目录。"""
        ini_path = self.get_ini_path()
        default_target = os.path.expanduser("~/Pictures")
        try:
            if not os.path.exists(ini_path):
                return default_target

            # 直接读取 [target] 下第一行非空内容作为路径
            legacy_lines = self._read_legacy_section_lines("target")
            if legacy_lines:
                return legacy_lines[0].strip()
            return default_target
        except Exception:
            return default_target

    def save_target_path(self, path):
        """仅更新 INI 中的 [target] 段，直接存储路径，不改动 [source] 段的任何内容。"""
        ini_path = self.get_ini_path()
        try:
            os.makedirs(APP_CACHE_DIR, exist_ok=True)
            if not os.path.exists(ini_path):
                # 若文件不存在，仅写入 target 段
                with open(ini_path, "w", encoding="utf-8") as f:
                    f.write(f"[target]\n{path}\n")
                return

            with open(ini_path, "r", encoding="utf-8") as f:
                content = f.read()

            import re
            # 捕获 [target] 段（到下一个段或文件结尾）
            pattern = r"(?ms)^\[target\][\s\S]*?(?=^\[|\Z)"
            match = re.search(pattern, content)
            if match:
                # 替换整个 [target] 段内容为新路径
                new_block = f"[target]\n{path}\n"
                new_content = content[:match.start()] + new_block + content[match.end():]
            else:
                # 不存在 [target] 段，则追加一个
                if not content.endswith("\n"):
                    content += "\n"
                new_content = content + f"[target]\n{path}\n"

            with open(ini_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except Exception:
            # 静默失败
            pass

    def initUI(self):
        """初始化用户界面"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 8, 16, 16)

        # 来源区域
        source_group = QWidget()
        source_layout = QVBoxLayout(source_group)
        source_layout.setContentsMargins(0, 0, 0, 0)
 
        # 置顶文件夹选择区域
        top_folders_group = QWidget()
        top_folders_layout = QVBoxLayout(top_folders_group)
        top_folders_layout.setContentsMargins(0, 0, 0, 0)
        top_folders_layout.setSpacing(6)
        
        top_folders_title = QLabel("置顶文件夹选择:")
        top_folders_title.setStyleSheet("font-weight: bold; color: #34495e;")
        top_folders_layout.addWidget(top_folders_title)
        
        # 创建置顶文件夹复选框（从INI加载）
        self.top_folders_container = QWidget()
        self.top_folders_layout = QGridLayout(self.top_folders_container)
        
        fixed_paths = self.load_fixed_source_paths()
        self.top_folder_checkboxes = []
        columns = 3  # 每行显示3个复选框
        for idx, p in enumerate(fixed_paths):
            cb = QCheckBox(p)
            cb.setToolTip("选择此文件夹进行下载")
            cb.stateChanged.connect(self.on_top_folder_changed)
            row = idx // columns
            col = idx % columns
            self.top_folders_layout.addWidget(cb, row, col)
            self.top_folder_checkboxes.append(cb)
        # self.top_folders_layout.addStretch()  # 网格布局不需要addStretch()
        
        top_folders_layout.addWidget(self.top_folders_container)
        source_layout.addWidget(top_folders_group)
        
        # 文件夹选择区域（隐藏）
        self.folder_selection_widget = QWidget()
        folder_layout = QVBoxLayout(self.folder_selection_widget)
        folder_title = QLabel("选择要下载的文件夹:")
        folder_title.setStyleSheet("font-weight: bold; color: #34495e;")
        folder_layout.addWidget(folder_title)
        self.folder_checkboxes_container = QWidget()
        self.folder_checkboxes_layout = QVBoxLayout(self.folder_checkboxes_container)
        folder_layout.addWidget(self.folder_checkboxes_container)
        self.folder_selection_widget.setVisible(False)
        source_layout.addWidget(self.folder_selection_widget)
        
        layout.addWidget(source_group)
        
        # 目标区域
        dest_group = QWidget()
        dest_layout = QVBoxLayout(dest_group)
        
        dest_title = QLabel("目标")
        dest_title.setStyleSheet("font-weight: bold; font-size: 14px; color: #2c3e50;")
        dest_layout.addWidget(dest_title)
        
        # 目标位置选择
        dest_location_layout = QHBoxLayout()
        dest_location_label = QLabel("位置:")
        self.dest_location_input = QLineEdit()
        self.dest_location_input.setText(self.load_target_path())
        
        self.browse_dest_btn = QPushButton("浏览")
        self.browse_dest_btn.setToolTip("浏览目标文件夹")
        self.open_dest_btn = QPushButton("打开")
        self.open_dest_btn.setToolTip("打开目标文件夹")
        self.open_dest_btn.clicked.connect(self.open_target_folder)
        self.browse_dest_btn.clicked.connect(self.browse_destination)
        
        dest_location_layout.addWidget(dest_location_label)
        dest_location_layout.addWidget(self.dest_location_input)
        dest_location_layout.addWidget(self.browse_dest_btn)
        dest_location_layout.addWidget(self.open_dest_btn)
        dest_layout.addLayout(dest_location_layout)
        
        # 子文件夹创建选项
        subfolder_layout = QHBoxLayout()
        subfolder_label = QLabel("子文件夹命名:")
        self.subfolder_combo = QComboBox()
        self.subfolder_combo.addItems(["年\\日", "年\\月\\日", "年\\月\\日\\时", "年\\月\\日\\时分", "年\\月\\日\\时分秒"])
        self.subfolder_combo.setCurrentText("年\\日")
        
        # 根据选择的子文件夹格式动态显示示例
        self.subfolder_example = QLabel()
        self.subfolder_example.setStyleSheet("color: #7f8c8d; font-size: 12px;")
        def update_subfolder_example():
            from datetime import datetime
            now = datetime.now()
            fmt = self.subfolder_combo.currentText()
            if "年\\月\\日\\时分秒" in fmt:
                example = now.strftime("YYYY-MM-DD-HH-MM-SS")
            elif "年\\月\\日\\时分" in fmt:
                example = now.strftime("YYYY-MM-DD-HH-MM")
            elif "年\\月\\日\\时" in fmt:
                example = now.strftime("YYYY-MM-DD-HH")
            elif "年\\月\\日" in fmt:
                example = now.strftime("YYYY-MM-DD")
            elif "年\\日" in fmt:
                example = now.strftime("YYYY-MM")
            else:
                example = now.strftime("YYYY-MM-DD")
            self.subfolder_example.setText(f"示例: {example}")
        self.subfolder_combo.currentTextChanged.connect(update_subfolder_example)
        update_subfolder_example()
        subfolder_example = self.subfolder_example
        subfolder_example.setStyleSheet("color: #7f8c8d; font-size: 12px;")
        
        subfolder_layout.addWidget(subfolder_label)
        subfolder_layout.addWidget(self.subfolder_combo)
        subfolder_layout.addWidget(subfolder_example)
        subfolder_layout.addStretch()
        dest_layout.addLayout(subfolder_layout)
        
        layout.addWidget(dest_group)
        
        # 设备选择区域
        device_group = QWidget()
        device_layout = QVBoxLayout(device_group)
        
        device_title = QLabel("选择目标设备:")
        device_title.setStyleSheet("font-weight: bold; font-size: 14px; color: #2c3e50;")
        device_layout.addWidget(device_title)
        
        # 设备列表
        device_list_layout = QVBoxLayout()
        self.device_list_widget = QWidget()
        self.device_list_layout = QVBoxLayout(self.device_list_widget)
        
        device_list_layout.addWidget(self.device_list_widget)
        device_layout.addLayout(device_list_layout)
        
        layout.addWidget(device_group)
        
        # 操作按钮
        button_layout = QHBoxLayout()
        
        self.download_btn = QPushButton("开始下载")
        self.download_btn.clicked.connect(self.start_download)
        self.download_btn.setEnabled(False)
        
        refresh_devices_btn = QPushButton("刷新设备")
        refresh_devices_btn.clicked.connect(self.refresh_devices)
        
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        
        button_layout.addStretch()
        button_layout.addWidget(refresh_devices_btn)
        button_layout.addWidget(self.download_btn)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        # 进度显示
        self.progress_label = QLabel("准备就绪")
        self.progress_label.setStyleSheet("color: #27ae60; font-weight: bold;")
        layout.addWidget(self.progress_label)

    def refresh_devices(self):
        """刷新ADB设备列表"""
        try:
            # 在刷新前记录当前已选中的设备，刷新后用于恢复选中状态
            selected_before = set()
            for device_id, checkbox in self.device_checkboxes.items():
                if checkbox.isChecked():
                    selected_before.add(device_id)

            startupinfo = None
            if hasattr(subprocess, 'STARTUPINFO'):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            
            result = subprocess.run(
                ['adb', 'devices'], 
                capture_output=True, 
                text=True, 
                encoding='utf-8',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]
                self.devices = []
                for line in lines:
                    if line.strip() and '\t' in line:
                        device_id, status = line.strip().split('\t')
                        if status == 'device':
                            self.devices.append(device_id)
                # 保留仍然存在的、之前已被选中的设备
                self.previously_selected_devices = {d for d in selected_before if d in self.devices}

                self.update_device_checkboxes()
                self.update_download_button_state()
            else:
                self.devices = []
                self.previously_selected_devices = set()
                self.update_device_checkboxes()
                
        except Exception as e:
            self.devices = []
            self.previously_selected_devices = set()
            self.update_device_checkboxes()

    def update_device_checkboxes(self):
        """更新设备复选框"""
        # 清除现有的设备复选框和映射
        for i in reversed(range(self.device_list_layout.count())):
            widget = self.device_list_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        
        self.device_checkboxes.clear()
        
        if not self.devices:
            no_device_label = QLabel("未检测到设备")
            no_device_label.setStyleSheet("color: #e74c3c; font-style: italic;")
            self.device_list_layout.addWidget(no_device_label)
        else:
            previously_selected = getattr(self, 'previously_selected_devices', set())
            for device in self.devices:
                # 创建水平布局容器
                device_container = QWidget()
                device_layout = QHBoxLayout(device_container)
                device_layout.setContentsMargins(0, 0, 0, 0)
                device_layout.setSpacing(5)
                
                # 创建复选框，显示自定义名称或原始ID
                display_name = self.get_device_display_name(device)
                checkbox = QCheckBox(display_name)
                checkbox.stateChanged.connect(self.update_download_button_state)
                
                # 保存复选框引用
                self.device_checkboxes[device] = checkbox
                
                # 如果之前被选中，恢复选中状态
                if device in previously_selected:
                    checkbox.setChecked(True)
                
                # 创建编辑按钮
                edit_btn = QPushButton("编辑")
                # edit_btn.setMaximumWidth(100)
                edit_btn.clicked.connect(lambda checked, d=device: self.edit_device_name(d))
                
                # 添加到容器布局
                device_layout.addWidget(checkbox)
                device_layout.addWidget(edit_btn)
                device_layout.addStretch()
                
                # 将容器添加到主布局
                self.device_list_layout.addWidget(device_container)


    def load_folder_contents(self, folder_path):
        """加载文件夹内容"""
        try:
            # 清除现有的文件夹复选框
            for i in reversed(range(self.folder_checkboxes_layout.count())):
                widget = self.folder_checkboxes_layout.itemAt(i).widget()
                if widget:
                    widget.deleteLater()
            
            # 获取文件夹列表
            folders = []
            for item in os.listdir(folder_path):
                item_path = os.path.join(folder_path, item)
                if os.path.isdir(item_path):
                    folders.append(item)
            
            if folders:
                for folder in sorted(folders):
                    checkbox = QCheckBox(folder)
                    checkbox.stateChanged.connect(self.update_download_button_state)
                    self.folder_checkboxes_layout.addWidget(checkbox)
                
                self.folder_selection_widget.setVisible(True)
            else:
                self.folder_selection_widget.setVisible(False)
                
        except Exception as e:
            print(f"加载文件夹内容时出错: {e}")

    def browse_destination(self):
        """浏览目标位置"""
        from PyQt5.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "选择目标文件夹")
        if folder:
            self.dest_location_input.setText(folder)
            # 保存到 INI [target]
            try:
                self.save_target_path(folder)
            except Exception:
                pass


    def on_manual_select_changed(self, state):
        """手动选择复选框状态改变 (此功能已禁用，仅用于内部状态更新)"""
        # Manual selection is no longer a user-facing feature.
        # This method is kept for completeness but should not affect UI visibility of folder_selection_widget.
        self.update_download_button_state()

    def on_top_folder_changed(self, state):
        """置顶文件夹复选框状态改变"""
        # 不再重置目标文件夹地址，只更新下载按钮状态
        self.update_download_button_state()

    def update_download_button_state(self):
        """更新下载按钮状态"""
        # 检查是否有选中的设备
        has_selected_device = False
        for device_id, checkbox in self.device_checkboxes.items():
            if checkbox.isChecked():
                has_selected_device = True
                break
        
        # 检查是否有选中的置顶文件夹
        has_selected_folder = any(cb.isChecked() for cb in self.top_folder_checkboxes)
        
        # 检查是否有目标路径
        has_destination = bool(self.dest_location_input.text().strip())
        
        self.download_btn.setEnabled(has_selected_device and has_selected_folder and has_destination)

    def start_download(self):
        """开始下载"""
        # 获取选中的设备（使用原始设备ID）
        selected_devices = []
        for device_id, checkbox in self.device_checkboxes.items():
            if checkbox.isChecked():
                selected_devices.append(device_id)
        
        if not selected_devices:
            QMessageBox.warning(self, "警告", "请选择至少一个设备！")
            return
        
        # 获取选中的置顶文件夹
        selected_folders = []
        for cb in self.top_folder_checkboxes:
            if cb.isChecked():
                selected_folders.append(cb.text())
        
        if not selected_folders:
            QMessageBox.warning(self, "警告", "请选择至少一个文件夹！")
            return
        
        # 获取目标路径
        dest_path = self.dest_location_input.text().strip()
        if not dest_path:
            QMessageBox.warning(self, "警告", "请选择目标路径！")
            return
        
        # 检查目标路径是否存在且可写
        if not os.path.exists(dest_path):
            QMessageBox.warning(self, "文件夹不存在", 
                              f"目标文件夹不存在：\n{dest_path}\n\n请选择一个新的本地文件夹。")
            # 自动打开文件夹选择对话框
            from PyQt5.QtWidgets import QFileDialog
            new_folder = QFileDialog.getExistingDirectory(
                self, 
                "选择下载目标文件夹", 
                os.path.expanduser("~/Pictures")  # 默认打开图片文件夹
            )
            
            if new_folder:
                # 更新目标路径输入框
                self.dest_location_input.setText(new_folder)
                
                # 保存新的目标路径到INI文件
                try:
                    self.save_target_path(new_folder)
                except Exception:
                    pass
                
                # 更新下载按钮状态
                self.update_download_button_state()
                
                # 提示用户重新开始下载
                QMessageBox.information(self, "路径已更新", 
                                      f"目标路径已更新为：\n{new_folder}\n\n请重新点击'开始下载'按钮。")
            else:
                # 用户取消了选择
                QMessageBox.information(self, "下载取消", "下载已取消。")
            return
        
        # 检查目标路径是否可写
        try:
            test_file = os.path.join(dest_path, "test_write_permission.tmp")
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
        except Exception as e:
            QMessageBox.warning(self, "文件夹权限错误", 
                              f"目标文件夹无写入权限：\n{dest_path}\n\n错误：{str(e)}\n\n请选择一个有写入权限的文件夹。")
            # 自动打开文件夹选择对话框
            from PyQt5.QtWidgets import QFileDialog
            new_folder = QFileDialog.getExistingDirectory(
                self, 
                "选择下载目标文件夹", 
                os.path.expanduser("~/Pictures")  # 默认打开图片文件夹
            )
            
            if new_folder:
                # 更新目标路径输入框
                self.dest_location_input.setText(new_folder)
                
                # 保存新的目标路径到INI文件
                try:
                    self.save_target_path(new_folder)
                except Exception:
                    pass
                
                # 更新下载按钮状态
                self.update_download_button_state()
                
                # 提示用户重新开始下载
                QMessageBox.information(self, "路径已更新", 
                                      f"目标路径已更新为：\n{new_folder}\n\n请重新点击'开始下载'按钮。")
            else:
                # 用户取消了选择
                QMessageBox.information(self, "下载取消", "下载已取消。")
            return
        
        # 将当前目标路径写入 INI
        try:
            self.save_target_path(dest_path)
        except Exception:
            pass
        
        # 创建下载线程
        self.download_thread = DownloadThread(
            selected_devices, 
            selected_folders, 
            dest_path, 
            self.subfolder_combo.currentText(),
            True,  # 总是使用手动模式，因为我们现在有明确的文件夹列表
            self.device_name_mapping  # 传递设备名称映射
        )
        self.download_thread.progress_updated.connect(self.update_progress)
        self.download_thread.download_finished.connect(self.download_finished)
        self.download_thread.folder_not_found.connect(self.handle_folder_not_found)  # 连接新信号
        self.download_thread.start()
        
        # 禁用下载按钮
        self.download_btn.setEnabled(False)
        self.progress_label.setText("正在下载...")
        self.progress_label.setStyleSheet("color: #f39c12; font-weight: bold;")

    def update_progress(self, message):
        """更新进度信息"""
        self.progress_label.setText(message)

    def download_finished(self, success_count, total_count, failed_devices):
        """下载完成处理"""
        self.download_btn.setEnabled(True)
        
        if failed_devices:
            failed_list = "\n".join([f"• {device}" for device in failed_devices])
            message = f"下载完成！\n\n成功: {success_count}/{total_count}\n\n失败的设备:\n{failed_list}"
            QMessageBox.information(self, "下载结果", message)
        else:
            message = f"下载完成！\n\n所有 {total_count} 台设备都下载成功！"
            QMessageBox.information(self, "下载结果", message)
        
        self.progress_label.setText("下载完成")
        self.progress_label.setStyleSheet("color: #27ae60; font-weight: bold;")

    def open_target_folder(self):
        """打开目标文件夹"""
        dest_path = self.dest_location_input.text().strip()
        if not dest_path:
            QMessageBox.warning(self, "警告", "请先设置目标路径！")
            return
        
        if not os.path.exists(dest_path):
            QMessageBox.warning(self, "文件夹不存在", 
                              f"目标文件夹不存在：\n{dest_path}\n\n请先选择有效的目标文件夹。")
            return
        
        try:
            # 使用系统默认的文件管理器打开文件夹
            if sys.platform == "win32":
                os.startfile(dest_path)
            elif sys.platform == "darwin":  # macOS
                subprocess.run(["open", dest_path])
            else:  # Linux
                subprocess.run(["xdg-open", dest_path])
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开文件夹：\n{str(e)}")

    def handle_folder_not_found(self, dest_path):
        """处理目标文件夹不存在的情况"""
        from PyQt5.QtWidgets import QFileDialog
        
        # 停止下载线程
        if hasattr(self, 'download_thread') and self.download_thread.isRunning():
            self.download_thread.terminate()
            self.download_thread.wait()
        
        # 显示错误消息并提示用户选择文件夹
        QMessageBox.warning(self, "文件夹不存在", 
                          f"目标文件夹不存在：\n{dest_path}\n\n请选择一个新的本地文件夹。")
        
        # 打开文件夹选择对话框
        new_folder = QFileDialog.getExistingDirectory(
            self, 
            "选择下载目标文件夹", 
            os.path.expanduser("~/Pictures")  # 默认打开图片文件夹
        )
        
        if new_folder:
            # 更新目标路径输入框
            self.dest_location_input.setText(new_folder)
            
            # 保存新的目标路径到INI文件
            try:
                self.save_target_path(new_folder)
            except Exception:
                pass
            
            # 重新启用下载按钮并更新状态
            self.download_btn.setEnabled(True)
            self.progress_label.setText("已选择新文件夹，请重新开始下载")
            self.progress_label.setStyleSheet("color: #3498db; font-weight: bold;")
            
            # 更新下载按钮状态（确保按钮状态正确）
            self.update_download_button_state()
        else:
            # 用户取消了选择
            self.download_btn.setEnabled(True)
            self.progress_label.setText("下载已取消")
            self.progress_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
            
            # 更新下载按钮状态
            self.update_download_button_state()

    def closeEvent(self, event):
        """窗口关闭事件"""
        if hasattr(self, 'refresh_timer'):
            self.refresh_timer.stop()
        if hasattr(self, 'download_thread') and self.download_thread.isRunning():
            self.download_thread.terminate()
            self.download_thread.wait()
        event.accept()


class DownloadThread(QThread):
    """下载线程"""
    
    progress_updated = pyqtSignal(str)
    download_finished = pyqtSignal(int, int, list)
    folder_not_found = pyqtSignal(str)  # 新增信号：当目标文件夹不存在时发送
    
    def __init__(self, devices, folders, dest_path, subfolder_format, is_manual_mode, device_name_mapping=None):
        super().__init__()
        self.devices = devices
        self.folders = folders
        self.dest_path = dest_path
        self.subfolder_format = subfolder_format
        self.is_manual_mode = is_manual_mode
        self.device_name_mapping = device_name_mapping or {}
        
    def run(self):
        """执行下载"""
        import datetime
        import tempfile
        
        # 检查目标路径是否存在
        if not os.path.exists(self.dest_path):
            # 发送信号通知主线程显示文件夹选择对话框
            self.progress_updated.emit("目标文件夹不存在，请选择本地文件夹")
            # 这里我们需要通过信号来通知主线程显示对话框
            # 由于QThread不能直接显示对话框，我们需要通过信号传递
            self.folder_not_found.emit(self.dest_path)
            return  # 直接返回，不发送download_finished信号
        
        # 创建时间戳文件夹
        timestamp = datetime.datetime.now()
        timestamp_str = self.format_timestamp(timestamp)
        timestamp_folder = os.path.join(self.dest_path, timestamp_str)
        
        # 检查时间戳文件夹是否可以创建
        try:
            os.makedirs(timestamp_folder, exist_ok=True)
        except Exception as e:
            self.progress_updated.emit(f"无法创建目标文件夹: {str(e)}")
            self.folder_not_found.emit(self.dest_path)
            return  # 直接返回，不发送download_finished信号
        
        success_count = 0
        failed_devices = []
        
        for device in self.devices:
            try:
                # 获取设备显示名称
                device_display_name = self.device_name_mapping.get(device, device)
                self.progress_updated.emit(f"正在处理设备: {device_display_name}")
                
                # 创建设备子文件夹，使用自定义名称或原始ID
                device_folder = os.path.join(timestamp_folder, device_display_name)
                try:
                    os.makedirs(device_folder, exist_ok=True)
                except Exception as e:
                    self.progress_updated.emit(f"无法创建设备文件夹: {str(e)}")
                    failed_devices.append(device)
                    continue
                
                if self.is_manual_mode:
                    # 手动模式：下载选中的文件夹
                    for folder in self.folders:
                        self.progress_updated.emit(f"正在下载文件夹: {folder}")
                        
                        # 执行adb pull命令
                        # 对于置顶文件夹，直接使用完整路径；对于手动选择的文件夹，添加/sdcard前缀
                        if folder.startswith("sdcard/") or folder.startswith("data/"):
                            source_path = f"/{folder}"
                        else:
                            source_path = f"/sdcard/{folder}"
                        
                        result = self.execute_adb_pull(device, source_path, device_folder)
                        
                        if result:
                            self.progress_updated.emit(f"文件夹 {folder} 下载成功")
                        else:
                            self.progress_updated.emit(f"文件夹 {folder} 下载失败")
                else:
                    # 非手动模式：下载整个存储卡
                    self.progress_updated.emit("正在下载整个存储卡")
                    
                    # 这里可以实现下载整个存储卡的逻辑
                    # 暂时跳过
                    pass
                
                success_count += 1
                self.progress_updated.emit(f"设备 {device_display_name} 处理完成")
                
            except Exception as e:
                device_display_name = self.device_name_mapping.get(device, device)
                self.progress_updated.emit(f"设备 {device_display_name} 处理失败: {str(e)}")
                failed_devices.append(device)
        
        # 只有在正常完成下载时才发送完成信号
        self.download_finished.emit(success_count, len(self.devices), failed_devices)
    
    def format_timestamp(self, timestamp):
        """格式化时间戳"""
        # 按照优先级判断，从最具体的开始
        if "年\\月\\日\\时分秒" in self.subfolder_format:
            return timestamp.strftime("%Y-%m-%d-%H-%M-%S")
        elif "年\\月\\日\\时分" in self.subfolder_format:
            return timestamp.strftime("%Y-%m-%d-%H-%M")
        elif "年\\月\\日\\时" in self.subfolder_format:
            return timestamp.strftime("%Y-%m-%d-%H")
        elif "年\\月\\日" in self.subfolder_format:
            return timestamp.strftime("%Y-%m-%d")
        elif "年\\日" in self.subfolder_format:
            return timestamp.strftime("%Y-%m-%d")
        else:
            return timestamp.strftime("%Y-%m-%d")
    
    def execute_adb_pull(self, device, source_path, dest_path):
        """执行adb pull命令"""
        try:
            startupinfo = None
            if hasattr(subprocess, 'STARTUPINFO'):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            
            command = f'adb -s {device} pull "{source_path}" "{dest_path}"'
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            
            return result.returncode == 0
            
        except Exception as e:
            print(f"执行adb pull命令时出错: {e}")
            return False


if __name__ == "__main__":
    app = QApplication(sys.argv)
    apply_stylesheet(app, theme='light_blue.xml', extra={'font_size': 16})
    ex = LogVerboseMaskApp()
    ex.show()
    sys.exit(app.exec_())

