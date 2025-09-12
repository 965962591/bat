import sys
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QMainWindow,
    QCheckBox,
    QGridLayout,
    QTextEdit,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QMessageBox,
    QLabel,
    QMenu,
    QAction,
    QInputDialog,
    QSplitter,
    QDialog,
    QLineEdit,
    QDialogButtonBox,
    QComboBox,
    QProgressBar,
    QSpinBox,
    QTabWidget,
    QRadioButton,
    QButtonGroup,
    QSizePolicy,
)
from PyQt5.QtWidgets import QScrollArea
import subprocess
from PyQt5.QtGui import QIcon
import threading
from PyQt5.QtCore import QMetaObject, Qt, pyqtSlot, Q_ARG, QTimer, pyqtSignal, QThread
import json
import os
import wmi
import pythoncom
import configparser
from datetime import datetime

from qt_material import apply_stylesheet
from rename import FileOrganizer
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


class LogVerboseMaskApp(QMainWindow):
    COMMANDS_FILE = os.path.join(APP_CACHE_DIR, "commands.json")
    
    # 添加设备变化信号
    device_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        # 确保缓存目录存在
        os.makedirs(APP_CACHE_DIR, exist_ok=True)
        self.specific_commands = self.load_commands()
        self.device_name_mapping = {}  # 设备ID到自定义名称的映射
        
        # 标签页相关变量
        self.tab_widget = None
        self.tab_checkboxes = {}  # 存储每个标签页的复选框 {tab_name: [checkboxes]}
        self.tab_script_checkboxes = {}  # 存储高通脚本复选框 {tab_name: [checkboxes]}
        
        # 初始化scrcpy进程变量 - 支持多设备同时投屏
        self.scrcpy_processes = {}  # 存储每个设备的投屏进程 {device_id: process}
        
        # 初始化重命名工具窗口变量
        self.file_organizer = None
        
        # 初始化下载对话框变量
        self.download_dialog = None
        
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
                    loaded_data = json.load(file)
                    # 检查是否是新的标签页格式
                    if self.is_new_format(loaded_data):
                        return loaded_data
                    else:
                        # 转换旧格式到新格式
                        return self.convert_old_format(loaded_data)
            except json.JSONDecodeError:
                # print(f"警告：无法解析 {self.COMMANDS_FILE}，将使用默认命令。")
                return self.get_default_commands() # 返回默认命令
        else:
            # 如果文件不存在，使用默认命令
            return self.get_default_commands() # 返回默认命令

    def is_new_format(self, data):
        """检查数据是否是新格式（按标签页分类）"""
        if not isinstance(data, dict):
            return False
        
        # 检查是否包含标签页键
        expected_tabs = ["高通", "MTK", "Unisoc", "Others"]
        return any(tab in data for tab in expected_tabs)

    def convert_old_format(self, old_data):
        """将旧格式转换为新格式"""
        new_data = self.get_default_commands()
        
        # 将旧的自定义脚本移动到Others标签页
        if isinstance(old_data, dict):
            for script_name, commands in old_data.items():
                # 跳过已经是默认脚本的，只添加自定义脚本
                if script_name not in new_data["Others"]:
                    new_data["Others"][script_name] = commands
        
        # 保存转换后的新格式
        self.save_commands_to_file(new_data)
        
        return new_data

    def save_commands_to_file(self, data):
        """将数据保存到文件"""
        try:
            with open(self.COMMANDS_FILE, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=4)
        except IOError as e:
            print(f"保存命令配置时出错: {e}")

    def get_default_commands(self): # 新增一个方法来返回默认命令
        """返回默认命令字典，按标签页分类"""
        return {
            "高通": {},
            "MTK": {},
            "Unisoc": {},
            "Others": {
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
        }

    def save_commands(self):
        """将命令保存到文件"""
        # 确保缓存目录存在
        os.makedirs(APP_CACHE_DIR, exist_ok=True)
        try:
            self.save_commands_to_file(self.specific_commands)
        except Exception as e:
            QMessageBox.warning(self, "保存错误", f"无法保存命令配置到: {self.COMMANDS_FILE}\n错误: {e}")

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
            
            # 若其他设备已使用相同名称，则覆盖：移除其他设备上的该名称
            for other_device_id, other_name in list(self.device_name_mapping.items()):
                if other_device_id != device_id and other_name == new_name:
                    self.device_name_mapping.pop(other_device_id, None)
            
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
                self.show_auto_close_message("成功", f"USB模式已切换到: {mode_name}", QMessageBox.Information, 3000)
                # print(f"USB模式切换成功: {mode_name}")
            else:
                error_msg = result.stderr.strip() if result.stderr else "未知错误"
                self.show_auto_close_message("执行失败", f"切换USB模式失败: {error_msg}", QMessageBox.Warning, 3000)
                # print(f"USB模式切换失败: {error_msg}")
                
        except Exception as e:
            error_msg = f"执行USB模式切换时出错: {str(e)}"
            self.show_auto_close_message("错误", error_msg, QMessageBox.Critical, 3000)
            # print(error_msg)

    def take_screenshot(self):
        """通过ADB发送截屏键事件"""
        selected_device = self.get_selected_device()
        if not selected_device:
            QMessageBox.warning(self, "设备错误", "请先选择有效的ADB设备！")
            return

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            remote_dir = "/sdcard/Pictures/Screenshots/"
            remote_path = f"{remote_dir}Screenshot_{timestamp}.png"

            startupinfo = None
            if hasattr(subprocess, 'STARTUPINFO'):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

            # 确保目录存在
            mkdir_cmd = f"adb -s {selected_device} shell mkdir -p {remote_dir}"
            subprocess.run(
                mkdir_cmd,
                shell=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )

            # 执行截屏
            screencap_cmd = f"adb -s {selected_device} shell screencap -p {remote_path}"
            result = subprocess.run(
                screencap_cmd,
                shell=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )

            if result.returncode == 0:
                print(f"已保存截图到: {remote_path}")
                self.show_auto_close_message("成功", f"已保存截图到: {remote_path}", QMessageBox.Information, 3000)
            else:
                error_msg = result.stderr.strip() if result.stderr else "未知错误"
                self.show_auto_close_message("执行失败", f"截屏失败: {error_msg}", QMessageBox.Warning, 3000)
        except Exception as e:
            self.show_auto_close_message("错误", f"执行截屏命令时出错: {str(e)}", QMessageBox.Critical, 3000)


    def take_photo(self):
        """通过ADB发送拍照键事件"""
        selected_device = self.get_selected_device()
        if not selected_device:
            QMessageBox.warning(self, "设备错误", "请先选择有效的ADB设备！")
            return

        try:
            command = f"adb -s {selected_device} shell input keyevent 27"

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
                # QMessageBox.information(self, "成功", "已发送拍照按键事件")
                print(f"已发送拍照按键事件: {command}")
            else:
                error_msg = result.stderr.strip() if result.stderr else "未知错误"
                QMessageBox.warning(self, "执行失败", f"发送拍照事件失败: {error_msg}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"执行拍照命令时出错: {str(e)}")


    def reboot_device(self):
        """重启设备"""
        selected_device = self.get_selected_device()
        if not selected_device:
            QMessageBox.warning(self, "设备错误", "请先选择有效的ADB设备！")
            return

        try:
            command = f"adb -s {selected_device} shell reboot -p"

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
                # QMessageBox.information(self, "成功", "已发送拍照按键事件")
                print(f"已发送关机按键事件: {command}")
            else:
                error_msg = result.stderr.strip() if result.stderr else "未知错误"
                QMessageBox.warning(self, "执行失败", f"发送关机事件失败: {error_msg}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"执行关机命令时出错: {str(e)}")
            
    def restart_device(self):
        """重启设备"""
        selected_device = self.get_selected_device()
        if not selected_device:
            QMessageBox.warning(self, "设备错误", "请先选择有效的ADB设备！")
            return

        try:
            command = f"adb -s {selected_device} shell reboot"

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
                # QMessageBox.information(self, "成功", "已发送拍照按键事件")
                print(f"已发送重启按键事件: {command}")
            else:
                error_msg = result.stderr.strip() if result.stderr else "未知错误"
                QMessageBox.warning(self, "执行失败", f"发送重启事件失败: {error_msg}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"执行重启命令时出错: {str(e)}")

    def lightscreen(self):
        """亮屏"""
        selected_device = self.get_selected_device()
        if not selected_device:
            QMessageBox.warning(self, "设备错误", "请先选择有效的ADB设备！")
            return

        try:
            command = f"adb -s {selected_device} shell input keyevent 26"

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
                # QMessageBox.information(self, "成功", "已发送拍照按键事件")
                print(f"已发送亮屏按键事件: {command}")
            else:
                error_msg = result.stderr.strip() if result.stderr else "未知错误"
                QMessageBox.warning(self, "执行失败", f"发送亮屏事件失败: {error_msg}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"执行亮屏命令时出错: {str(e)}")

    def create_menu_bar(self):
        """创建菜单栏"""
        menubar = self.menuBar()
        
        # 创建USB模式菜单
        usb_menu = menubar.addMenu('USB模式')
        
        # 仅充电模式
        only_charge_action = QAction('仅充电', self)
        only_charge_action.setToolTip('仅充电模式，不进行文件传输')
        only_charge_action.triggered.connect(lambda: self.switch_usb_mode("仅充电", ""))
        usb_menu.addAction(only_charge_action)
        
        # 文件传输模式
        file_transfer_action = QAction('文件传输', self)
        file_transfer_action.setToolTip('文件传输模式，可以进行文件传输')
        file_transfer_action.triggered.connect(lambda: self.switch_usb_mode("文件传输", "mtp"))
        usb_menu.addAction(file_transfer_action)
        
        # 传输照片模式
        photo_transfer_action = QAction('传输照片', self)
        photo_transfer_action.setToolTip('传输照片模式，可以进行照片传输')
        photo_transfer_action.triggered.connect(lambda: self.switch_usb_mode("传输照片", "ptp"))
        usb_menu.addAction(photo_transfer_action)
        
        # 创建暗码菜单
        secret_menu = menubar.addMenu('暗码功能')
        self.create_secret_code_menu(secret_menu)
        
        # 创建快捷功能菜单
        quick_menu = menubar.addMenu('快捷功能')
        self.create_quick_functions_menu(quick_menu)

        #安装APK菜单
        install_apk_menu = menubar.addMenu('安装APK')
        install_apk_menu.setToolTip('选择文件夹，批量安装文件夹内apk文件')
        self.create_install_apk_menu(install_apk_menu)

        #连接wifi
        connect_wifi_menu = menubar.addMenu('连接WiFi')
        connect_wifi_menu.setToolTip('选择WiFi，连接指定WiFi,请在配置文件中提前配置WiFi信息')
        self.create_connect_wifi_menu(connect_wifi_menu)

    def create_connect_wifi_menu(self, connect_wifi_menu):
        """创建连接WiFi菜单（动态加载SSID）"""
        # 先清空原有菜单项（若有）
        connect_wifi_menu.clear()

        # 读取WiFi配置
        wifi_map = self.load_wifi_configs()
        if not wifi_map:
            noitem = QAction('未配置WiFi (编辑 app_cache/bat_filepath.ini [WIFI])', self)
            noitem.setEnabled(False)
            connect_wifi_menu.addAction(noitem)
            return

        # 为每个SSID添加菜单项
        for ssid, pwd in wifi_map.items():
            action = QAction(ssid, self)
            masked = '*' * len(pwd) if pwd else ''
            action.setToolTip(f'SSID: {ssid}  密码: {masked}')
            action.triggered.connect(lambda checked, s=ssid, p=pwd: self.connect_wifi_with(s, p))
            connect_wifi_menu.addAction(action)

    def connect_wifi_enable(self):
        """开启WiFi (svc wifi enable)"""
        selected_device = self.get_selected_device()
        if not selected_device:
            QMessageBox.warning(self, "设备错误", "请先选择有效的ADB设备！")
            return
        try:
            startupinfo = None
            if hasattr(subprocess, 'STARTUPINFO'):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            cmd = f"adb -s {selected_device} shell svc wifi enable"
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                startupinfo=startupinfo
            )
            if result.returncode == 0:
                QMessageBox.information(self, "成功", "已开启WiFi。")
            else:
                QMessageBox.warning(self, "失败", f"开启WiFi失败：\n{(result.stderr or result.stdout or '').strip()}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"执行失败：\n{str(e)}")

    def connect_wifi_with(self, ssid, password):
        """连接指定WiFi: cmd wifi connect-network "SSID" wpa2 "PASSWORD""" 
        selected_device = self.get_selected_device()
        if not selected_device:
            QMessageBox.warning(self, "设备错误", "请先选择有效的ADB设备！")
            return
        if not ssid:
            QMessageBox.warning(self, "配置错误", "SSID 不能为空！")
            return
        try:
            startupinfo = None
            if hasattr(subprocess, 'STARTUPINFO'):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

            # 先尝试开启WiFi（不打断流程，即使失败也继续尝试连接）
            try:
                enable_cmd = f"adb -s {selected_device} shell svc wifi enable"
                subprocess.run(
                    enable_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    startupinfo=startupinfo
                )
            except Exception:
                pass

            # 按需求使用 wpa2
            ssid_escaped = ssid.replace('"', '\\"')
            pwd_escaped = (password or '').replace('"', '\\"')
            cmd = f"adb -s {selected_device} shell cmd wifi connect-network \"{ssid_escaped}\" wpa2 \"{pwd_escaped}\""
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                startupinfo=startupinfo
            )
            if result.returncode == 0 and ('Success' in (result.stdout or '') or not result.stderr):
                QMessageBox.information(self, "成功", f"已连接到 WiFi：{ssid}")
            else:
                err = (result.stderr or result.stdout or '').strip()
                QMessageBox.warning(self, "失败", f"连接 WiFi 失败：\n{err}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"执行失败：\n{str(e)}")

    def load_wifi_configs(self):
        """从INI文件加载 [WIFI] 配置，返回 {ssid: password}"""
        ini_path = os.path.join(APP_CACHE_DIR, "bat_filepath.ini")
        wifi_map = {}
        try:
            if os.path.exists(ini_path):
                with open(ini_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                import re
                pattern = r'\[WIFI\](.*?)(?=\[|$)'
                match = re.search(pattern, content, re.DOTALL)
                if match:
                    wifi_content = match.group(1)
                    for line in wifi_content.split('\n'):
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        if '=' in line:
                            ssid, pwd = line.split('=', 1)
                            ssid = ssid.strip()
                            pwd = pwd.strip()
                            if ssid:
                                wifi_map[ssid] = pwd
        except Exception as e:
            print(f"加载WIFI配置时出错: {e}")
        return wifi_map

    def create_install_apk_menu(self, install_apk_menu):
        """创建安装APK菜单"""
        install_apk_action = QAction('批量安装APK', self)
        install_apk_action.setToolTip('批量安装APK')
        install_apk_action.triggered.connect(self.install_apk)
        install_apk_menu.addAction(install_apk_action)

    def install_apk(self):
        """安装APK"""
        selected_device = self.get_selected_device()
        if not selected_device:
            QMessageBox.warning(self, "设备错误", "请先选择有效的ADB设备！")
            return
        try:
            from PyQt5.QtWidgets import QFileDialog, QProgressDialog
            folder = QFileDialog.getExistingDirectory(self, "选择包含APK的文件夹")
            if not folder:
                return

            # 收集该目录下的所有apk文件（不递归）
            try:
                entries = os.listdir(folder)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"无法读取文件夹：\n{str(e)}")
                return

            apk_files = []
            for name in entries:
                path = os.path.join(folder, name)
                if os.path.isfile(path) and name.lower().endswith('.apk'):
                    apk_files.append(path)

            if not apk_files:
                QMessageBox.information(self, "提示", "该文件夹下未找到APK文件。")
                return

            total = len(apk_files)

            # 进度对话框
            progress = QProgressDialog("准备安装...", "取消", 0, total, self)
            progress.setWindowTitle("批量安装APK")
            progress.setWindowModality(Qt.WindowModal)
            progress.setAutoClose(False)
            progress.setAutoReset(False)
            progress.setMinimumDuration(0)
            progress.setValue(0)

            # 启动后台线程
            self.install_thread = InstallApkThread(selected_device, apk_files)

            def on_progress_changed(index, total_count, filename):
                base = os.path.basename(filename) if filename else ""
                progress.setLabelText(f"正在安装: {base}  ({index}/{total_count})")
                progress.setMaximum(total_count)
                progress.setValue(index)

            def on_finished(success_list, failed_list, cancelled):
                progress.close()
                if cancelled:
                    QMessageBox.information(self, "已取消", "用户取消了批量安装。")
                else:
                    success_count = len(success_list)
                    failed_count = len(failed_list)
                    summary = [
                        f"共发现APK：{total}",
                        f"安装成功：{success_count}",
                        f"安装失败：{failed_count}"
                    ]
                    if failed_list:
                        summary.append("\n失败明细：")
                        preview = failed_list[:20]
                        summary.extend(preview)
                        if failed_count > 20:
                            summary.append(f"... 以及另外 {failed_count - 20} 条失败")
                    QMessageBox.information(self, "批量安装结果", "\n".join(summary))
                # 清理线程对象
                try:
                    self.install_thread.deleteLater()
                except Exception:
                    pass

            def on_canceled():
                if hasattr(self, 'install_thread') and self.install_thread is not None:
                    self.install_thread.request_cancel()

            self.install_thread.progress_changed.connect(on_progress_changed)
            self.install_thread.install_finished.connect(on_finished)
            progress.canceled.connect(on_canceled)
            self.install_thread.start()
            progress.show()

        except Exception as e:
            QMessageBox.critical(self, "错误", f"批量安装过程中发生异常：\n{str(e)}")

    def load_secret_codes(self):
        """从INI文件加载暗码配置"""
        ini_path = os.path.join(APP_CACHE_DIR, "bat_filepath.ini")
        secret_codes = {}
        try:
            if os.path.exists(ini_path):
                # 直接读取文件内容，专门查找[SECRET_CODE]节
                with open(ini_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 查找[SECRET_CODE]节
                import re
                secret_pattern = r'\[SECRET_CODE\](.*?)(?=\[|$)'
                match = re.search(secret_pattern, content, re.DOTALL)
                
                if match:
                    secret_content = match.group(1).strip()
                    for line in secret_content.split('\n'):
                        line = line.strip()
                        if '=' in line:
                            # 处理带引号的键值对
                            if line.startswith('"') and '"' in line[1:]:
                                # 找到第一个引号结束的位置
                                quote_end = line.find('"', 1)
                                if quote_end > 0:
                                    key = line[1:quote_end]
                                    value_part = line[quote_end + 1:].strip()
                                    if value_part.startswith('='):
                                        value = value_part[1:].strip()
                                        if value:
                                            secret_codes[key] = value
                            else:
                                # 处理不带引号的键值对
                                key, value = line.split('=', 1)
                                key = key.strip()
                                value = value.strip()
                                if key and value:
                                    secret_codes[key] = value
        except Exception as e:
            print(f"加载暗码配置时出错: {e}")
        
        return secret_codes

    def create_secret_code_menu(self, secret_menu):
        """创建暗码菜单项"""
        secret_codes = self.load_secret_codes()
        
        if not secret_codes:
            # 如果没有配置暗码，添加一个默认项
            no_code_action = QAction('未配置暗码', self)
            no_code_action.setEnabled(False)
            secret_menu.addAction(no_code_action)
            return
        
        # 为每个暗码创建菜单项
        for name, code in secret_codes.items():
            action = QAction(name, self)
            action.setToolTip(f'执行暗码: {code}')
            action.triggered.connect(lambda checked, c=code, n=name: self.execute_secret_code(c, n))
            secret_menu.addAction(action)

    def execute_secret_code(self, code, name):
        """执行暗码"""
        selected_device = self.get_selected_device()
        if not selected_device:
            QMessageBox.warning(self, "设备错误", "请先选择有效的ADB设备！")
            return
        
        try:
            # 构建adb命令
            command = f"adb -s {selected_device} shell am broadcast -a android.provider.Telephony.SECRET_CODE -d android_secret_code://{code}"
            
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
                self.show_auto_close_message("成功", f"暗码 '{name}' (代码: {code}) 执行成功！", QMessageBox.Information, 3000)
                print(f"暗码执行成功: {name} ({code})")
            else:
                error_msg = result.stderr.strip() if result.stderr else "未知错误"
                self.show_auto_close_message("执行失败", f"暗码 '{name}' 执行失败: {error_msg}", QMessageBox.Warning, 3000)
                print(f"暗码执行失败: {name} ({code}) - {error_msg}")
                
        except Exception as e:
            error_msg = f"执行暗码时出错: {str(e)}"
            self.show_auto_close_message("错误", error_msg, QMessageBox.Critical, 3000)
            print(error_msg)

    def create_quick_functions_menu(self, quick_menu):
        """创建快捷功能菜单"""
        # 拍照功能
        take_photo_action = QAction('拍照', self)
        take_photo_action.setToolTip('启动相机后点击拍照')
        take_photo_action.triggered.connect(self.take_photo)
        quick_menu.addAction(take_photo_action)
        
        # 截屏功能
        screenshot_action = QAction('截屏', self)
        screenshot_action.setToolTip('截图路径/sdcard/Pictures/Screenshots/')
        screenshot_action.triggered.connect(self.take_screenshot)
        quick_menu.addAction(screenshot_action)
        
        # 关机功能
        reboot_action = QAction('关机', self)
        reboot_action.setToolTip('关机')
        reboot_action.triggered.connect(self.reboot_device)
        quick_menu.addAction(reboot_action)

        # 重启功能
        restart_action = QAction('重启', self)
        restart_action.setToolTip('重启')
        restart_action.triggered.connect(self.restart_device)
        quick_menu.addAction(restart_action)
        
        # 亮屏功能
        lightscreen_action = QAction('亮屏', self)
        lightscreen_action.setToolTip('亮屏')
        lightscreen_action.triggered.connect(self.lightscreen)
        quick_menu.addAction(lightscreen_action)
        


    def initUI(self):
        self.setWindowTitle("Bat脚本管理器")
        self.resize(1200, 900)
        icon_path = os.path.join(os.path.dirname(__file__), "icon", "bat.ico")
        self.setWindowIcon(QIcon(icon_path))
        self.mask_value = 0x00000000

        # 创建菜单栏
        self.create_menu_bar()

        # 创建中央widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QVBoxLayout(central_widget)

        # 创建设备选择区域
        device_layout = QHBoxLayout()
        device_label = QLabel("选择设备:")
        device_label.setToolTip("选择设备需要执行的设备")
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(150)  # 设置最小宽度
        # self.device_combo.setMaximumWidth(35)  # 设置最大宽度
        self.device_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # 设置大小策略
        refresh_button = QPushButton("刷新")
        refresh_button.setToolTip("刷新设备列表")
        refresh_button.clicked.connect(self.refresh_devices)
        
        # 添加编辑设备名称按钮
        edit_device_button = QPushButton("编辑名称")
        edit_device_button.setToolTip("自定义设备名称")
        edit_device_button.clicked.connect(self.edit_current_device_name)
        # 添加投屏按钮
        adb_interface_button = QPushButton("投屏")
        adb_interface_button.setToolTip("打开adb投屏窗口")
        adb_interface_button.clicked.connect(self.open_adb_interface)
        
        # 快捷功能（拍照、截屏）已移至菜单栏
        # 批量拍摄控件：数量、间隔、拍摄、暂停/继续
        capture_count_label = QLabel("拍摄数量:")
        self.capture_count_spin = QSpinBox()
        self.capture_count_spin.setRange(1, 100000)
        self.capture_count_spin.setValue(10)

        capture_interval_label = QLabel("拍摄间隔(秒):")
        self.capture_interval_spin = QSpinBox()
        self.capture_interval_spin.setRange(1, 3600)
        self.capture_interval_spin.setValue(1)

        self.capture_start_btn = QPushButton("拍摄")
        self.capture_start_btn.setToolTip("按数量与间隔进行批量拍摄")
        self.capture_pause_btn = QPushButton("暂停/继续")
        self.capture_pause_btn.setEnabled(False)
        #保存
        save_image_button = QPushButton("保存")
        save_image_button.setToolTip("保存指定数量图片到本地")
        # 连接按钮信号
        self.capture_start_btn.clicked.connect(self.start_batch_capture)
        self.capture_pause_btn.clicked.connect(self.toggle_capture_pause)
        save_image_button.clicked.connect(self.save_image_to_local)
        device_layout.addWidget(device_label)
        device_layout.addWidget(self.device_combo)
        device_layout.addWidget(refresh_button)
        device_layout.addWidget(edit_device_button)
        device_layout.addWidget(adb_interface_button)
        device_layout.addWidget(capture_count_label)
        device_layout.addWidget(self.capture_count_spin)
        device_layout.addWidget(capture_interval_label)
        device_layout.addWidget(self.capture_interval_spin)
        device_layout.addWidget(self.capture_start_btn)
        device_layout.addWidget(self.capture_pause_btn)
        device_layout.addWidget(save_image_button)
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
        run_button.setToolTip("选中的单个设备执行脚本")
        run_button.clicked.connect(self.execute_adb_commands)
        button_layout.addWidget(run_button)

        # 创建批量执行按钮
        batch_run_button = QPushButton("批量执行")
        batch_run_button.setToolTip("已连接设备批量执行脚本")
        batch_run_button.clicked.connect(self.batch_execute_adb_commands)
        button_layout.addWidget(batch_run_button)

        # 创建下载按钮
        download_button = QPushButton("下载")
        download_button.setToolTip("启动下载窗口，从相机/储存卡下载照片")
        download_button.clicked.connect(self.open_download_window)
        button_layout.addWidget(download_button)

        # 创建新增按钮
        add_button = QPushButton("新增脚本")
        add_button.setToolTip("新增自定义脚本，方便自己编写脚本")
        add_button.clicked.connect(self.add_new_script)
        button_layout.addWidget(add_button)
        
        # 创建原生运行按钮
        native_run_button = QPushButton("原生运行")
        native_run_button.setToolTip("原生运行主直接运行bat文件，最原生的Windows方式")
        native_run_button.clicked.connect(self.native_run_script)
        button_layout.addWidget(native_run_button)
        # 将按钮布局添加到主布局
        main_layout.addLayout(button_layout)

        # 创建上半部分widget（包含设备选择和按钮区域）
        top_widget = QWidget()
        top_widget.setLayout(main_layout)

        # 创建标签页控件
        self.tab_widget = QTabWidget()
        self.create_tabs()

        # 创建垂直分割器
        main_splitter = QSplitter(Qt.Vertical)
        main_splitter.addWidget(top_widget)
        main_splitter.addWidget(self.tab_widget)
        
        # 设置分割器比例（1:1）
        main_splitter.setSizes([450, 450])  # 根据窗口高度1200的一半设置
        
        # 将主分割器设置为中央widget的内容
        central_widget_layout = QVBoxLayout(central_widget)
        central_widget_layout.addWidget(main_splitter)
        central_widget_layout.setContentsMargins(0, 0, 0, 0)  # 移除边距

        # 批量拍摄状态变量
        self.capture_thread = None
        self.capture_stop_event = threading.Event()
        self.capture_pause_event = threading.Event()
        self.capture_running = False

    def create_tabs(self):
        """创建标签页"""
        # 定义标签页名称
        tab_names = ["高通固定页", "高通", "MTK", "Unisoc", "Others"]
        
        # 初始化标签页复选框字典
        for tab_name in tab_names:
            self.tab_checkboxes[tab_name] = []
            self.tab_script_checkboxes[tab_name] = []
        
        # 为每个标签页创建内容
        for tab_name in tab_names:
            tab_widget = QWidget()
            tab_layout = QVBoxLayout(tab_widget)
            tab_layout.setContentsMargins(0, 0, 0, 0)  # 移除边距
            
            # 创建滚动区域
            scroll_area = QScrollArea()
            scroll_widget = QWidget()
            scroll_layout = QGridLayout(scroll_widget)
            scroll_layout.setContentsMargins(10, 10, 10, 10)  # 设置内边距
            scroll_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)  # 设置顶部左对齐
            scroll_layout.setHorizontalSpacing(20)  # 设置水平间距
            scroll_layout.setVerticalSpacing(10)    # 设置垂直间距
            scroll_layout.setColumnStretch(0, 1)    # 让各列均匀分布
            scroll_layout.setColumnStretch(1, 1)
            scroll_layout.setColumnStretch(2, 1)
            scroll_layout.setColumnStretch(3, 1)
            
            if tab_name == "高通固定页":
                # 高通固定页：只包含高通脚本复选框，不可修改
                self.create_qualcomm_fixed_tab(scroll_layout, tab_name)
            else:
                # 其他标签页（高通、MTK、Unisoc、Others）：只包含自定义脚本复选框
                self.create_other_tab(scroll_layout, tab_name)
            
            scroll_area.setWidget(scroll_widget)
            scroll_area.setWidgetResizable(True)
            scroll_area.setAlignment(Qt.AlignTop)  # 滚动区域也设置为顶部对齐
            tab_layout.addWidget(scroll_area)
            
            self.tab_widget.addTab(tab_widget, tab_name)

    def create_qualcomm_fixed_tab(self, layout, tab_name):
        """创建高通固定页内容（只读）"""
        # 高通脚本复选框
        script_labels = [
            "Sensor", "Application", "IQ module", "IFace",
            "Utilities", "LMME", "ISP", "Sync",
            "NCS", "Post Processor", "MemSpy", "Metadata",
            "Image Lib", "Asserts", "AEC", "CPP",
            "Core", "AWB", "HAL", "HWI",
            "AF", "JPEG", "CHI", "DRQ",
            "Stats", "FD", "CSL", "FD",
        ]
        
        for i, label in enumerate(script_labels):
            checkbox = QCheckBox(label)
            checkbox.stateChanged.connect(self.update_script_mask)
            # 高通固定页的复选框不设置右键菜单，不可编辑
            checkbox.setContextMenuPolicy(Qt.NoContextMenu)  # 禁用右键菜单
            row = i // 4
            col = i % 4
            layout.addWidget(checkbox, row, col)
            self.tab_script_checkboxes[tab_name].append(checkbox)

    def create_other_tab(self, layout, tab_name):
        """创建其他标签页内容"""
        # 添加自定义脚本复选框
        self.add_custom_scripts_to_tab(layout, tab_name, 0)

    def add_custom_scripts_to_tab(self, layout, tab_name, start_row):
        """向标签页添加自定义脚本复选框"""
        # 获取该标签页的自定义脚本
        tab_commands = self.specific_commands.get(tab_name, {})
        
        for i, (script_name, commands) in enumerate(tab_commands.items()):
            checkbox = QCheckBox(script_name)
            checkbox.stateChanged.connect(self.update_command_mask)
            checkbox.setContextMenuPolicy(Qt.CustomContextMenu)
            checkbox.customContextMenuRequested.connect(
                lambda pos, cb=checkbox: self.show_context_menu(pos, cb)
            )
            row = start_row + (i // 4)
            col = i % 4
            layout.addWidget(checkbox, row, col)
            self.tab_checkboxes[tab_name].append(checkbox)

    def _hidden_startupinfo(self):
        startupinfo = None
        if hasattr(subprocess, 'STARTUPINFO'):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        return startupinfo

    def start_batch_capture(self):
        """按照数量和间隔执行批量拍摄（单设备）。"""
        if self.capture_running:
            return
        selected_device = self.get_selected_device()
        if not selected_device:
            QMessageBox.warning(self, "设备错误", "请先选择有效的ADB设备！")
            return

        total_shots = self.capture_count_spin.value()
        interval_seconds = max(1, self.capture_interval_spin.value())

        # 启动相机
        try:
            start_cmd = f"adb -s {selected_device} shell am start -a android.media.action.STILL_IMAGE_CAMERA"
            subprocess.run(
                start_cmd,
                shell=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                startupinfo=self._hidden_startupinfo(),
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
        except Exception as e:
            QMessageBox.warning(self, "启动失败", f"无法启动相机: {e}")
            return

        self.capture_stop_event.clear()
        self.capture_pause_event.clear()

        def worker():
            try:
                # 启动相机后等待3秒再开始拍摄
                import time as _t
                _t.sleep(3)
                for i in range(1, total_shots + 1):
                    if self.capture_stop_event.is_set():
                        break
                    # 暂停控制
                    while self.capture_pause_event.is_set():
                        if self.capture_stop_event.is_set():
                            break
                        _t.sleep(0.1)

                    if self.capture_stop_event.is_set():
                        break

                    # 拍照
                    command = f"adb -s {selected_device} shell input keyevent 27"
                    result = subprocess.run(
                        command,
                        shell=True,
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        startupinfo=self._hidden_startupinfo(),
                        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                    )
                    if result.returncode != 0:
                        err = result.stderr.strip() if result.stderr else "未知错误"
                        print(f"批量拍摄失败: {err}")
                        break

                    print(f"批量拍摄 {i}/{total_shots}")

                    # 等待间隔（最后一张不等待）
                    if i < total_shots:
                        import time as _t
                        for _ in range(interval_seconds * 10):
                            if self.capture_stop_event.is_set():
                                break
                            while self.capture_pause_event.is_set():
                                if self.capture_stop_event.is_set():
                                    break
                                _t.sleep(0.1)
                            if self.capture_stop_event.is_set():
                                break
                            _t.sleep(0.1)
            finally:
                # 结束状态恢复
                self.capture_running = False
                QMetaObject.invokeMethod(self.capture_pause_btn, "setEnabled", Qt.QueuedConnection, Q_ARG(bool, False))
                QMetaObject.invokeMethod(self.capture_start_btn, "setEnabled", Qt.QueuedConnection, Q_ARG(bool, True))

        self.capture_thread = threading.Thread(target=worker, daemon=True)
        self.capture_running = True
        self.capture_start_btn.setEnabled(False)
        self.capture_pause_btn.setEnabled(True)
        self.capture_thread.start()

    def toggle_capture_pause(self):
        """切换批量拍摄暂停与继续。"""
        if not self.capture_running:
            return
        if self.capture_pause_event.is_set():
            self.capture_pause_event.clear()
        else:
            self.capture_pause_event.set()

    def save_image_to_local(self):
        """
        保存图片到本地
        1、获取到拍摄的张数
        2、从/sdcard/scim/camera/ 中下载最新的图片（只下载拍摄的张数的图）
        3、保存到本地，本地路径是~/Pictures/年_月_日_时_分_秒/  如果~/Pictures/ 不存在，则创建
        
        """
        selected_device = self.get_selected_device()
        if not selected_device:
            QMessageBox.warning(self, "设备错误", "请先选择有效的ADB设备！")
            return
        
        try:
            # 获取拍摄的张数
            shot_count = self.capture_count_spin.value()
            if shot_count <= 0:
                QMessageBox.warning(self, "参数错误", "拍摄张数必须大于0！")
                return
                
            # 创建本地保存路径
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
            pictures_dir = os.path.expanduser("~/Pictures")
            save_dir = os.path.join(pictures_dir, timestamp)
            
            # 确保目录存在
            os.makedirs(save_dir, exist_ok=True)
            
            # 获取远程文件列表
            remote_dir = "/sdcard/scim/camera/"
            startupinfo = None
            if hasattr(subprocess, 'STARTUPINFO'):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            
            # 检查远程目录是否存在
            check_cmd = f"adb -s {selected_device} shell ls -la {remote_dir}"
            result = subprocess.run(
                check_cmd,
                shell=True,
                capture_output=True,
                text=True,
                encoding='gbk' if sys.platform == "win32" else 'utf-8',  # Windows使用GBK编码
                errors='replace',  # 处理编码错误
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            
            if "No such file or directory" in result.stderr or result.returncode != 0:
                # 尝试其他可能的相机目录
                alternative_dirs = ["/sdcard/DCIM/Camera/"]
                found_dir = False
                
                for alt_dir in alternative_dirs:
                    check_cmd = f"adb -s {selected_device} shell ls -la {alt_dir}"
                    result = subprocess.run(
                        check_cmd,
                        shell=True,
                        capture_output=True,
                        text=True,
                        encoding='gbk' if sys.platform == "win32" else 'utf-8',  # Windows使用GBK编码
                        errors='replace',  # 处理编码错误
                        startupinfo=startupinfo,
                        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                    )
                    
                    if result.returncode == 0 and "No such file or directory" not in result.stderr:
                        remote_dir = alt_dir
                        found_dir = True
                        break
                
                if not found_dir:
                    # 如果找不到预设目录，尝试创建一个目录
                    try:
                        fallback_dir = "/sdcard/DCIM/Camera/"
                        mkdir_cmd = f"adb -s {selected_device} shell mkdir -p {fallback_dir}"
                        subprocess.run(
                            mkdir_cmd,
                            shell=True,
                            capture_output=True,
                            text=True,
                            encoding='gbk' if sys.platform == "win32" else 'utf-8',
                            errors='replace',
                            startupinfo=startupinfo,
                            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                        )
                        remote_dir = fallback_dir
                        print(f"创建并使用备用目录: {fallback_dir}")
                    except Exception as e:
                        print(f"创建备用目录失败: {e}")
                        QMessageBox.warning(self, "路径错误", "无法找到设备上的相机图片目录！")
                        return
            
            # 列出远程文件，不使用grep命令
            list_cmd = f"adb -s {selected_device} shell ls -la {remote_dir}"
            result = subprocess.run(
                list_cmd,
                shell=True,
                capture_output=True,
                text=True,
                encoding='gbk' if sys.platform == "win32" else 'utf-8',  # Windows使用GBK编码
                errors='replace',  # 处理编码错误
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            
            if result.returncode != 0:
                QMessageBox.warning(self, "命令执行失败", f"获取图片列表失败：{result.stderr}")
                return
            
            # 解析文件列表，获取最新的N张图片
            files = []
            for line in result.stdout.splitlines():
                try:
                    # 跳过目录项和非文件行
                    if "d" in line[:10] or line.startswith("total ") or not line.strip():
                        continue
                        
                    parts = line.split()
                    if len(parts) >= 7:  # 至少需要7个部分（权限、链接数、用户、组、大小、日期、文件名）
                        # 获取文件名（可能在最后一个位置或之后的位置）
                        filename = parts[-1]
                        
                        # 检查是否是图片文件
                        if filename and (filename.lower().endswith('.jpg') or 
                                         filename.lower().endswith('.jpeg') or 
                                         filename.lower().endswith('.png')):
                            print(f"找到图片: {filename}")
                            files.append(filename)
                except Exception as e:
                    print(f"解析文件行出错: {line} - {e}")
                    continue
                    
            # 按文件名排序（通常包含时间戳）
            files.sort()
            
            # 取最新的shot_count张图片（文件列表已按时间排序，最新的在最后）
            files = files[-shot_count:] if len(files) >= shot_count else files
            
            if not files:
                QMessageBox.warning(self, "未找到图片", "设备上未找到任何图片文件！")
                return
            
            # 创建进度对话框
            from PyQt5.QtWidgets import QProgressDialog
            progress = QProgressDialog("正在下载图片...", "取消", 0, len(files), self)
            progress.setWindowTitle("保存图片")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.show()
            
            # 下载文件
            success_count = 0
            for i, filename in enumerate(files):
                if progress.wasCanceled():
                    break
                    
                progress.setValue(i)
                progress.setLabelText(f"正在下载 {i+1}/{len(files)}: {filename}")
                
                remote_path = f"{remote_dir}{filename}"
                local_path = os.path.join(save_dir, filename)
                
                pull_cmd = f"adb -s {selected_device} pull \"{remote_path}\" \"{local_path}\""
                result = subprocess.run(
                    pull_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    encoding='gbk' if sys.platform == "win32" else 'utf-8',  # Windows使用GBK编码
                    errors='replace',  # 处理编码错误
                    startupinfo=startupinfo,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                )
                
                if result.returncode == 0:
                    success_count += 1
                else:
                    print(f"下载失败: {filename} - {result.stderr}")
            
            progress.setValue(len(files))
            
            # 显示结果
            if success_count > 0:
                QMessageBox.information(self, "下载完成", 
                                     f"成功下载 {success_count}/{len(files)} 张图片到:\n{save_dir}")
                
                # 尝试打开保存目录
                try:
                    if sys.platform == "win32":
                        os.startfile(save_dir)
                    elif sys.platform == "darwin":  # macOS
                        subprocess.run(["open", save_dir])
                    else:  # Linux
                        subprocess.run(["xdg-open", save_dir])
                except Exception as e:
                    print(f"打开目录失败: {e}")
            else:
                QMessageBox.warning(self, "下载失败", "未能成功下载任何图片！")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存图片时出错: {str(e)}")
        
    def update_script_mask(self):
        """更新高通脚本复选框"""
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
        
        # 只处理高通固定页的脚本复选框
        qualcomm_checkboxes = self.tab_script_checkboxes.get("高通固定页", [])
        for i, checkbox in enumerate(qualcomm_checkboxes):
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
        """更新所有标签页的自定义脚本复选框"""
        commands = []
        current_text = self.mask_display.toPlainText().split("\n")
        current_text = [line for line in current_text if line.strip()]  # 移除空行
        
        # 遍历所有标签页的自定义脚本复选框
        for tab_name, checkboxes in self.tab_checkboxes.items():
            for checkbox in checkboxes:
                # 获取该脚本的命令列表
                tab_commands = self.specific_commands.get(tab_name, {})
                command_list = tab_commands.get(checkbox.text(), [])
                
                if checkbox.isChecked():
                    for command in command_list:
                        if command not in current_text:
                            commands.append(command)
                else:
                    for command in command_list:
                        if command in current_text:
                            current_text.remove(command)
        
        final_commands = current_text + commands
        self.mask_display.setText("\n".join(final_commands))

    @pyqtSlot()
    def show_success_message(self):
        self.show_auto_close_message("成功", "脚本执行成功！", QMessageBox.Information, 3000)

    def show_auto_close_message(self, title, text, icon=QMessageBox.Information, timeout_ms=3000):
        """显示可自动关闭的消息框（非阻塞）。"""
        try:
            msg = QMessageBox(self)
            msg.setWindowTitle(title)
            msg.setText(text)
            msg.setIcon(icon)
            msg.setStandardButtons(QMessageBox.Ok)
            QTimer.singleShot(timeout_ms, msg.accept)
            msg.show()
        except Exception:
            QMessageBox.information(self, title, text)

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
            for tab_name, checkboxes in self.tab_checkboxes.items():
                for checkbox in checkboxes:
                    if checkbox.isChecked():
                        tab_commands = self.specific_commands.get(tab_name, {})
                        command_list = tab_commands.get(checkbox.text(), [])
                        for cmd in command_list:
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
                    for tab_name, checkboxes in self.tab_checkboxes.items():
                        for checkbox in checkboxes:
                            if checkbox.isChecked():
                                tab_commands = self.specific_commands.get(tab_name, {})
                                command_list = tab_commands.get(checkbox.text(), [])
                                for cmd in command_list:
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
        # 批量执行结果3秒自动关闭
        self.show_auto_close_message("批量执行结果", message, QMessageBox.Information, 3000)

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
        # 查找脚本所在的标签页
        script_tab = None
        current_commands = []
        for tab_name, tab_commands in self.specific_commands.items():
            if command_key in tab_commands:
                script_tab = tab_name
                current_commands = tab_commands[command_key]
                break
        
        if script_tab is None:
            QMessageBox.warning(self, "错误", "未找到指定的脚本！")
            return
        
        if isinstance(current_commands, list):
            current_commands = "\n".join(current_commands)
        
        # 创建自定义编辑对话框
        dialog = ScriptEditDialog(self, command_key, current_commands, script_tab)
        if dialog.exec_() == QDialog.Accepted:
            new_commands = dialog.get_content()
            if new_commands:
                self.specific_commands[script_tab][command_key] = new_commands.split("\n")
                self.save_commands()

    def rename_command(self, checkbox):
        """重命名选中的命令复选框"""
        old_name = checkbox.text()
        new_name, ok = QInputDialog.getText(
            self, "重命名脚本", "输入新的脚本名称：", text=old_name
        )
        if ok and new_name:
            # 查找脚本所在的标签页
            script_tab = None
            for tab_name, tab_commands in self.specific_commands.items():
                if old_name in tab_commands:
                    script_tab = tab_name
                    break
            
            if script_tab is None:
                QMessageBox.warning(self, "错误", "未找到指定的脚本！")
                return
            
            # 检查新名称是否已存在
            for tab_name, tab_commands in self.specific_commands.items():
                if new_name in tab_commands:
                    QMessageBox.warning(self, "错误", f"脚本名称 '{new_name}' 已存在于 '{tab_name}' 标签页中！")
                    return
            
            # 更新 specific_commands 字典
            self.specific_commands[script_tab][new_name] = self.specific_commands[script_tab].pop(old_name)
            self.save_commands()
            
            # 重新创建标签页以显示更新
            self.recreate_tabs()

    def add_new_script(self):
        dialog = ScriptInputDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            script_name, script_content, selected_tab = dialog.get_inputs()
            if script_name and script_content:
                # 确保标签页存在
                if selected_tab not in self.specific_commands:
                    self.specific_commands[selected_tab] = {}
                
                # 检查脚本名称是否已存在
                for tab_name, tab_commands in self.specific_commands.items():
                    if script_name in tab_commands:
                        QMessageBox.warning(self, "错误", f"脚本名称 '{script_name}' 已存在于 '{tab_name}' 标签页中！")
                        return
                
                # 添加脚本到指定标签页
                self.specific_commands[selected_tab][script_name] = script_content.split("\n")
                self.save_commands()
                
                # 重新创建标签页以显示新脚本
                self.recreate_tabs()

    def recreate_tabs(self):
        """重新创建标签页"""
        # 清除现有标签页
        self.tab_widget.clear()
        
        # 重新初始化标签页复选框字典
        for tab_name in ["高通固定页", "高通", "MTK", "Unisoc", "Others"]:
            self.tab_checkboxes[tab_name] = []
            self.tab_script_checkboxes[tab_name] = []
        
        # 重新创建标签页
        self.create_tabs()

    def native_run_script(self):
        """原生运行：检查所有已连接设备，为每个设备生成bat脚本并同时执行"""
        # 检查所有已连接的设备
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
                
                if not devices:
                    QMessageBox.warning(self, "设备错误", "未检测到任何已连接的ADB设备！")
                    return
            else:
                QMessageBox.warning(self, "ADB错误", "无法获取设备列表，请检查ADB连接！")
                return
        except Exception as e:
            QMessageBox.warning(self, "ADB错误", f"检查设备状态时出错: {str(e)}")
            return

        # 显示确认对话框
        device_list = "\n".join([f"• {self.get_device_display_name(device)} ({device})" for device in devices])
        reply = QMessageBox.question(
            self, 
            "原生运行确认", 
            f"检测到 {len(devices)} 台设备:\n{device_list}\n\n确定要为所有设备生成并执行脚本吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return

        # 为每个设备生成bat脚本并同时执行
        generated_bat_files = []
        
        for i, device in enumerate(devices):
            try:
                # 收集所有要执行的命令
                all_commands = []

                # 只添加文本框中的命令（保持原有顺序）
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
                import datetime
                
                # 创建带时间戳的文件名
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                device_display_name = self.get_device_display_name(device)
                bat_filename = f"bat_script_{device_display_name}_{timestamp}.bat"
                
                # 确保缓存目录存在
                os.makedirs(APP_CACHE_DIR, exist_ok=True)
                bat_path = os.path.join(APP_CACHE_DIR, bat_filename)
                
                # 创建bat文件（使用GBK编码，避免中文乱码）
                with open(bat_path, "w", encoding="gbk") as f:
                    f.write("@echo off\n")
                    f.write("chcp 936 >nul\n")  # 设置GBK编码，支持中文显示
                    f.write(f"title Bat脚本执行 - {device_display_name}\n")  # 设置窗口标题
                    f.write("color 0A\n")  # 设置颜色：黑底绿字
                    f.write("echo ========================================\n")
                    f.write("echo            Bat脚本执行器\n")
                    f.write("echo ========================================\n")
                    f.write("echo.\n")
                    f.write(f"echo [INFO] 目标设备: {device}\n")
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
                    f.write("pause\n")  # 显示"请按任意键继续..."，确保窗口不会立即关闭

                generated_bat_files.append((bat_path, device_display_name))
                
            except Exception as e:
                QMessageBox.warning(self, "错误", f"为设备 {device} 生成脚本时出错：\n{str(e)}")
                continue

        if not generated_bat_files:
            QMessageBox.critical(self, "错误", "没有成功生成任何bat脚本！")
            return

        # 显示成功消息
        bat_files_info = "\n".join([f"• {device_name}: {bat_path}" for bat_path, device_name in generated_bat_files])
        QMessageBox.information(self, "脚本生成成功", 
                              f"已为 {len(generated_bat_files)} 台设备生成bat脚本：\n\n{bat_files_info}\n\n即将同时运行所有脚本...")

        # 同时运行所有bat文件（每个设备一个窗口）
        for bat_path, device_name in generated_bat_files:
            try:
                # 使用os.startfile直接打开bat文件，这是最原生的Windows方式
                os.startfile(bat_path)
                print(f"已启动设备 {device_name} 的脚本执行窗口")
            except Exception as e:
                print(f"无法自动运行设备 {device_name} 的bat脚本: {e}")
                QMessageBox.warning(self, "警告", f"无法自动运行设备 {device_name} 的bat脚本，请手动运行：\n{bat_path}")

    def delete_command(self, checkbox):
        command_key = checkbox.text()
        
        # 查找并移除命令
        for tab_name, tab_commands in self.specific_commands.items():
            if command_key in tab_commands:
                del self.specific_commands[tab_name][command_key]
                self.save_commands()
                break
        
        # 重新创建标签页以显示更新
        self.recreate_tabs()



    def on_device_changed(self):
        """设备变化回调函数"""
        # 在主线程中发送信号
        self.device_changed.emit()

    def open_download_window(self):
        """打开文件下载窗口"""
        self.download_dialog = FileDownloadDialog(self)
        self.download_dialog.show()

    def open_adb_interface(self):
        """调用 adb.py 中的接口 - 支持多设备同时投屏"""
        try:
            # 获取选中的设备
            selected_device = self.get_selected_device()
            if not selected_device:
                QMessageBox.warning(self, "设备错误", "请先选择有效的ADB设备！")
                return
            
            scrcpy_path = os.path.join(os.path.dirname(__file__), "scrcpy", "scrcpy.exe")
            if not os.path.exists(scrcpy_path):
                print(f"错误: 找不到 scrcpy.exe 路径: {scrcpy_path}")
                return
            
            # 检查当前设备是否已有投屏进程在运行
            if (selected_device in self.scrcpy_processes and 
                self.scrcpy_processes[selected_device] is not None and 
                self.scrcpy_processes[selected_device].poll() is None):
                print(f"设备 {selected_device} 的投屏已在运行中。")
                return
            
            # 构建scrcpy命令参数
            scrcpy_args = [
                scrcpy_path,
                "-s", selected_device
            ]
            
            # 启动新设备的投屏进程
            process = subprocess.Popen(
                scrcpy_args, 
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE
            )
            
            # 记录该设备的投屏进程
            self.scrcpy_processes[selected_device] = process
            print(f"已启动 adb 投屏 - 设备: {selected_device}")
            
            # 显示当前运行的投屏设备数量
            running_count = sum(1 for p in self.scrcpy_processes.values() 
                              if p is not None and p.poll() is None)
            print(f"当前共有 {running_count} 个设备正在投屏")
            
        except Exception as e:
            print(f"启动 adb 投屏失败: {str(e)}")

    def closeEvent(self, event):
        """窗口关闭事件处理"""
        # 停止USB监控
        if hasattr(self, 'usb_monitor'):
            self.usb_monitor.stop()
        
        # 停止定时器
        if hasattr(self, 'refresh_timer'):
            self.refresh_timer.stop()
        
        # 关闭重命名工具窗口
        if hasattr(self, 'file_organizer') and self.file_organizer is not None:
            self.file_organizer.close()
        
        # 关闭下载对话框
        if hasattr(self, 'download_dialog') and self.download_dialog is not None:
            self.download_dialog.close()
        
        # 停止所有投屏进程
        if hasattr(self, 'scrcpy_processes'):
            for device_id, process in self.scrcpy_processes.items():
                if process is not None and process.poll() is None:
                    print(f"正在停止设备 {device_id} 的投屏...")
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
        
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

        # 创建标签页选择区域
        tab_label = QLabel("选择标签页:")
        layout.addWidget(tab_label)
        
        # 创建单选按钮组
        self.tab_button_group = QButtonGroup(self)
        tab_names = ["高通", "MTK", "Unisoc", "Others"]
        
        tab_layout = QHBoxLayout()
        for i, tab_name in enumerate(tab_names):
            radio_button = QRadioButton(tab_name)
            radio_button.setChecked(i == 0)  # 默认选择高通
            self.tab_button_group.addButton(radio_button, i)
            tab_layout.addWidget(radio_button)
        
        layout.addLayout(tab_layout)

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
        script_name = self.script_name_input.text()
        script_content = self.script_content_input.toPlainText()
        selected_tab = self.tab_button_group.checkedButton().text()
        return script_name, script_content, selected_tab


class ScriptEditDialog(QDialog):
    def __init__(self, parent=None, script_name="", script_content="", script_tab=""):
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

        # 创建标签页信息标签（只读显示）
        if script_tab:
            tab_label = QLabel(f"所属标签页: {script_tab}")
            tab_label.setStyleSheet("color: #7f8c8d; font-size: 12px;")
            layout.addWidget(tab_label)

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
        self.setWindowTitle("从设备下载照片")
        self.resize(1200, 800)
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
        self.previously_selected_devices = set()  # 之前选中的设备
        self.previously_selected_folders = {}  # 之前选中的文件夹 {device_id: {folder_path: True}}
        
        # 初始化重命名工具窗口变量
        self.file_organizer = None
        
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
            
            # 若其他设备已使用相同名称，则覆盖：移除其他设备上的该名称
            for other_device_id, other_name in list(self.device_name_mapping.items()):
                if other_device_id != device_id and other_name == new_name:
                    self.device_name_mapping.pop(other_device_id, None)
            
            # 更新映射
            if new_name == device_id:
                # 如果名称与原始ID相同，删除映射
                self.device_name_mapping.pop(device_id, None)
            else:
                # 否则保存新名称
                self.device_name_mapping[device_id] = new_name
            
            # 保存到INI文件
            self.save_device_names()
            
            # 同步到主界面的设备名称映射
            if hasattr(self.parent, 'device_name_mapping'):
                self.parent.device_name_mapping.update(self.device_name_mapping)
                # 刷新主界面的设备列表
                if hasattr(self.parent, 'refresh_devices'):
                    self.parent.refresh_devices()
            
            # 刷新下载界面的设备显示
            self.update_device_checkboxes()

    def load_fixed_source_paths(self):
        """读取固定路径与配置文件。优先从 [source] 节读取。
        支持三种格式：
        1) INI: [source] 下 paths= 多行；或 path1=, path2= ...
        2) 新格式: [source] 下 path=自定义名称 格式
        3) 旧格式: [source] 下直接逐行列出路径
        4) 若文件不存在或解析失败，返回默认列表
        返回: Dict[str, str] - {路径: 自定义名称}
        """
        ini_path = os.path.join(APP_CACHE_DIR, "bat_filepath.ini")
        default_paths = {
            "sdcard/dcim/camera/": "camera",
            "data/vendor/camera/": "vendor_camera"
        }
        default_target = os.path.expanduser("~/Pictures")

        try:
            os.makedirs(APP_CACHE_DIR, exist_ok=True)
            config = configparser.ConfigParser()

            if not os.path.exists(ini_path):
                # 初始化新格式 INI
                config["source"] = {}
                for path, name in default_paths.items():
                    config["source"][path] = name
                config["target"] = {"path": default_target}
                with open(ini_path, "w", encoding="utf-8") as f:
                    config.write(f)
                return default_paths

            # 读取现有文件内容
            with open(ini_path, "r", encoding="utf-8") as f:
                content = f.read()

            path_name_dict = {}
            try:
                # 优先尝试标准 INI 解析
                config.read_string(content)
                if config.has_section("source"):
                    # 检查是否有新格式的路径=名称配置
                    for key, val in config.items("source"):
                        key = key.strip()
                        val = val.strip()
                        if key and val:
                            # 检查是否是路径格式（包含/）
                            if "/" in key:
                                path_name_dict[key] = val
                            elif key.lower().startswith("path"):
                                # 旧格式的path1=, path2=等
                                if val:
                                    path_name_dict[val.lstrip("/")] = val.lstrip("/")
                    
                    # 检查是否有paths多行配置
                    if config.has_option("source", "paths"):
                        raw = config.get("source", "paths")
                        for line in raw.splitlines():
                            line = line.strip()
                            if line:
                                if "=" in line:
                                    # 新格式：路径=名称
                                    path, name = line.split("=", 1)
                                    path = path.strip().lstrip("/")
                                    name = name.strip()
                                    if path and name:
                                        path_name_dict[path] = name
                                else:
                                    # 旧格式：只有路径
                                    path = line.lstrip("/")
                                    if path:
                                        path_name_dict[path] = path
            except configparser.Error:
                # 标准解析失败则走旧格式解析
                pass

            if not path_name_dict:
                # 旧格式: 读取 [source] 节中的逐行内容
                legacy_paths = self._read_legacy_section_lines("source")
                for path in legacy_paths:
                    if path:
                        path_name_dict[path.lstrip("/")] = path.lstrip("/")

            return path_name_dict if path_name_dict else default_paths
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
        # 设置对话框的边距为0
        self.setContentsMargins(0, 0, 0, 0)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(2)  # 进一步减少间距
        layout.setContentsMargins(4, 2, 4, 4)  # 进一步减少边距，特别是顶部边距
        layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)  # 设置主布局顶部左对齐

        # 设备标题 - 直接添加到主布局，不包装在额外的widget中
        device_title = QLabel("选择目标设备和文件夹:")
        device_title.setStyleSheet("font-weight: bold; font-size: 14px; color: #2c3e50; margin: 0; padding: 0;")
        device_title.setAlignment(Qt.AlignTop | Qt.AlignLeft)  # 置顶左对齐
        device_title.setContentsMargins(0, 0, 0, 0)  # 移除标题边距
        layout.addWidget(device_title)
        
        # 设备选择区域（包含文件夹选择）
        device_group = QWidget()
        device_layout = QVBoxLayout(device_group)
        device_layout.setContentsMargins(0, 0, 0, 0)  # 移除边距
        device_layout.setSpacing(1)  # 最小间距
        device_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)  # 设置设备布局顶部左对齐
        
        # 创建滚动区域来容纳设备选择
        self.device_scroll = QScrollArea()
        self.device_scroll.setWidgetResizable(True)
        self.device_scroll.setMaximumHeight(400)  # 限制最大高度
        self.device_scroll.setMinimumHeight(150)  # 减少最小高度
        self.device_scroll.setFrameStyle(0)  # 移除边框
        self.device_scroll.setAlignment(Qt.AlignTop | Qt.AlignLeft)  # 设置滚动区域顶部左对齐
        self.device_scroll.setContentsMargins(0, 0, 0, 0)  # 移除滚动区域边距
        self.device_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # 只在需要时显示滚动条
        
        # 创建容器widget来放置设备选择
        self.device_container = QWidget()
        self.device_layout = QVBoxLayout(self.device_container)
        self.device_layout.setContentsMargins(0, 0, 0, 0)  # 完全移除内边距
        self.device_layout.setSpacing(1)  # 最小间距
        self.device_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)  # 设置布局顶部左对齐
        
        # 设置滚动区域的widget
        self.device_scroll.setWidget(self.device_container)
        device_layout.addWidget(self.device_scroll)
        
        # 存储设备文件夹选择的字典 {device_id: {folder_name: checkbox}}
        self.device_folder_checkboxes = {}
        # 存储设备文件夹容器的字典 {device_id: widget}
        self.device_folder_containers = {}
        
        layout.addWidget(device_group)
        
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
        self.open_dest_btn.setToolTip("打开目标文件夹")        # 添加重命名功能按钮
        rename_btn = QPushButton("重命名")
        rename_btn.setToolTip("启动文件重命名工具")
        rename_btn.clicked.connect(self.open_rename_tool)
        self.open_dest_btn.clicked.connect(self.open_target_folder)
        self.browse_dest_btn.clicked.connect(self.browse_destination)
        
        dest_location_layout.addWidget(dest_location_label)
        dest_location_layout.addWidget(self.dest_location_input)
        dest_location_layout.addWidget(self.browse_dest_btn)
        dest_location_layout.addWidget(self.open_dest_btn)
        dest_location_layout.addWidget(rename_btn)
        dest_layout.addLayout(dest_location_layout)
        
        # 子文件夹创建选项
        subfolder_layout = QHBoxLayout()
        
        # 下拉列表和示例
        subfolder_label = QLabel("子文件夹命名:")
        self.subfolder_combo = QComboBox()
        self.subfolder_combo.addItems(["年\\日", "年\\月\\日", "年\\月\\日\\时", "年\\月\\日\\时分", "年\\月\\日\\时分秒"])
        # self.subfolder_combo.setCurrentText("年\\月\\日\\时分秒")
        self.subfolder_combo.setCurrentIndex(1)
        
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
                example = now.strftime("YYYY-MM-DD")
            else:
                example = now.strftime("YYYY-MM-DD")
            self.subfolder_example.setText(f"示例: {example}")
        self.subfolder_combo.currentTextChanged.connect(update_subfolder_example)
        update_subfolder_example()
        subfolder_example = self.subfolder_example
        subfolder_example.setStyleSheet("color: #7f8c8d; font-size: 12px;")
        
        # 自定义输入框（改为可编辑下拉列表）
        custom_label = QLabel("自定义名称:")
        self.custom_subfolder_input = QComboBox()
        self.custom_subfolder_input.setEditable(True)  # 允许用户输入
        self.custom_subfolder_input.setPlaceholderText("留空使用日期格式，请输入自定义文件名如:第一轮FT")
        self.custom_subfolder_input.setToolTip("留空使用日期格式，请输入自定义文件名如:第一轮FT")
        self.custom_subfolder_input.setMinimumWidth(500)  # 设置最小宽度确保文本显示完整
        
        # 添加默认选项
        default_options = [
            "自测",
            "回归", 
            "FT1",
            "FT2",
            "小数包",
            "整数包"
        ]
        self.custom_subfolder_input.addItems(default_options)
        self.custom_subfolder_input.setCurrentIndex(1)
        
        # 将所有控件添加到水平布局中
        subfolder_layout.addWidget(subfolder_label)
        subfolder_layout.addWidget(self.subfolder_combo)
        subfolder_layout.addWidget(subfolder_example)
        subfolder_layout.addWidget(custom_label)
        subfolder_layout.addWidget(self.custom_subfolder_input)
        subfolder_layout.addStretch()
        
        dest_layout.addLayout(subfolder_layout)
        
        layout.addWidget(dest_group)
        
        # 进度显示区域
        progress_group = QWidget()
        progress_layout = QVBoxLayout(progress_group)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建滚动区域来容纳多个进度条

        self.progress_scroll_area = QScrollArea()
        self.progress_scroll_area.setWidgetResizable(True)
        # 自适应窗口大小：不限制高度，并设置扩展的尺寸策略
        self.progress_scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 让内容贴顶贴左，避免顶部空白
        self.progress_scroll_area.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        # 移除边框和额外边距，减少视觉空白
        self.progress_scroll_area.setFrameStyle(0)
        self.progress_scroll_area.setContentsMargins(0, 0, 0, 0)
        # 仅在需要时显示垂直滚动条，禁用水平滚动条
        self.progress_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.progress_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # 创建容器widget来放置进度条（两列网格布局）
        self.progress_container = QWidget()
        from PyQt5.QtWidgets import QGridLayout
        self.progress_bars_layout = QGridLayout(self.progress_container)
        self.progress_bars_layout.setContentsMargins(0, 0, 0, 0)
        self.progress_bars_layout.setHorizontalSpacing(10)
        self.progress_bars_layout.setVerticalSpacing(5)
        self.progress_bars_layout.setColumnStretch(0, 1)
        self.progress_bars_layout.setColumnStretch(1, 1)
        self.progress_bars_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        
        # 设置滚动区域的widget
        self.progress_scroll_area.setWidget(self.progress_container)
        progress_layout.addWidget(self.progress_scroll_area)
        
        # 存储进度条的字典 {device_id:folder_name -> (progress_bar, label)}
        self.progress_bars_dict = {}
        
        layout.addWidget(progress_group)
        
        # 操作按钮区域（移到最下面）
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

    def refresh_devices(self):
        """刷新ADB设备列表"""
        try:
            # 在刷新前记录当前已选中的设备和文件夹状态
            selected_devices_before = set()
            selected_folders_before = {}  # {device_id: {folder_path: True}}
            
            for device_id, checkbox in self.device_checkboxes.items():
                if checkbox.isChecked():
                    selected_devices_before.add(device_id)
                    # 记录该设备选中的文件夹
                    if device_id in self.device_folder_checkboxes:
                        selected_folders_before[device_id] = {}
                        for folder_path, folder_checkbox in self.device_folder_checkboxes[device_id].items():
                            if folder_checkbox.isChecked():
                                selected_folders_before[device_id][folder_path] = True

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
                new_devices = []
                for line in lines:
                    if line.strip() and '\t' in line:
                        device_id, status = line.strip().split('\t')
                        if status == 'device':
                            new_devices.append(device_id)
                
                # 检查设备列表是否有变化
                devices_changed = set(self.devices) != set(new_devices)
                self.devices = new_devices
                
                # 只有在设备列表变化时才重新创建UI
                if devices_changed:
                    # 保留仍然存在的、之前已被选中的设备
                    self.previously_selected_devices = {d for d in selected_devices_before if d in self.devices}
                    self.previously_selected_folders = {}
                    for device_id, folders in selected_folders_before.items():
                        if device_id in self.devices:
                            self.previously_selected_folders[device_id] = folders
                    
                    self.update_device_checkboxes()
                
                self.update_download_button_state()
            else:
                self.devices = []
                self.previously_selected_devices = set()
                self.previously_selected_folders = {}
                self.update_device_checkboxes()
                
        except Exception as e:
            self.devices = []
            self.previously_selected_devices = set()
            self.previously_selected_folders = {}
            self.update_device_checkboxes()

    def update_device_checkboxes(self):
        """更新设备复选框"""
        # 清除现有的设备复选框和映射
        for i in reversed(range(self.device_layout.count())):
            widget = self.device_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        
        self.device_checkboxes.clear()
        self.device_folder_checkboxes.clear()
        self.device_folder_containers.clear()
        
        if not self.devices:
            no_device_label = QLabel("未检测到设备")
            no_device_label.setStyleSheet("color: #e74c3c; font-style: italic;")
            self.device_layout.addWidget(no_device_label)
        else:
            previously_selected = getattr(self, 'previously_selected_devices', set())
            # 获取固定的文件夹列表（现在是字典格式：{路径: 自定义名称}）
            fixed_folders_dict = self.load_fixed_source_paths()
            
            for device in self.devices:
                # 创建设备主容器
                device_main_container = QWidget()
                device_main_layout = QVBoxLayout(device_main_container)
                device_main_layout.setContentsMargins(0, 0, 0, 0)  # 完全移除边距
                device_main_layout.setSpacing(6)  # 增加设备之间的间距
                device_main_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)  # 设置顶部左对齐
                
                # 创建设备选择行
                device_row_container = QWidget()
                device_row_layout = QHBoxLayout(device_row_container)
                device_row_layout.setContentsMargins(0, 0, 0, 0)
                device_row_layout.setSpacing(5)
                
                # 创建复选框，显示自定义名称或原始ID
                display_name = self.get_device_display_name(device)
                checkbox = QCheckBox(display_name)
                checkbox.stateChanged.connect(self.on_device_selection_changed)
                
                # 保存复选框引用
                self.device_checkboxes[device] = checkbox
                
                # 如果之前被选中，恢复选中状态
                if device in previously_selected:
                    checkbox.setChecked(True)
                
                # 创建编辑按钮
                edit_btn = QPushButton("编辑")
                edit_btn.clicked.connect(lambda checked, d=device: self.edit_device_name(d))
                
                # 添加到设备行布局
                device_row_layout.addWidget(checkbox)
                device_row_layout.addWidget(edit_btn)
                device_row_layout.addStretch()
                
                # 添加到主容器
                device_main_layout.addWidget(device_row_container)
                
                # 创建设备文件夹选择区域（初始隐藏）
                if fixed_folders_dict:
                    folder_container = QWidget()
                    folder_layout = QVBoxLayout(folder_container)
                    folder_layout.setContentsMargins(8, 4, 0, 0)  # 增加顶部间距
                    folder_layout.setSpacing(4)  # 增加垂直间距
                    folder_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)  # 设置顶部左对齐
                    
                    # 文件夹标题
                    folder_title = QLabel("选择文件夹:")
                    folder_title.setStyleSheet("color: #7f8c8d; font-size: 11px; font-weight: bold; margin: 0; padding: 0;")
                    folder_layout.addWidget(folder_title)
                    
                    # 创建文件夹复选框网格
                    folders_grid = QWidget()
                    folders_grid_layout = QGridLayout(folders_grid)
                    folders_grid_layout.setContentsMargins(0, 0, 0, 0)
                    folders_grid_layout.setSpacing(8)  # 增加网格间距，让复选框不那么拥挤
                    
                    # 初始化设备文件夹复选框字典
                    self.device_folder_checkboxes[device] = {}
                    
                    columns = 9  # 每行显示9个复选框
                    for idx, (folder_path, custom_name) in enumerate(fixed_folders_dict.items()):
                        folder_checkbox = QCheckBox(custom_name)
                        # 设置鼠标悬浮提示，显示完整路径
                        folder_checkbox.setToolTip(f"路径: {folder_path}\n自定义名称: {custom_name}")
                        folder_checkbox.stateChanged.connect(self.update_download_button_state)
                        
                        # 恢复文件夹选择状态
                        if (device in getattr(self, 'previously_selected_folders', {}) and 
                            folder_path in getattr(self, 'previously_selected_folders', {}).get(device, {})):
                            folder_checkbox.setChecked(True)
                        
                        row = idx // columns
                        col = idx % columns
                        folders_grid_layout.addWidget(folder_checkbox, row, col)
                        
                        # 保存复选框引用，使用路径作为键
                        self.device_folder_checkboxes[device][folder_path] = folder_checkbox
                    
                    folder_layout.addWidget(folders_grid)
                    
                    # 保存文件夹容器引用
                    self.device_folder_containers[device] = folder_container
                    
                    # 添加到主容器
                    device_main_layout.addWidget(folder_container)
                    
                    # 根据设备选择状态显示/隐藏文件夹选择
                    folder_container.setVisible(checkbox.isChecked())
                
                # 将设备主容器添加到主布局
                self.device_layout.addWidget(device_main_container)
            
            # 更新设备文件夹显示状态
            self.update_device_folders_visibility()

    def on_device_selection_changed(self, state):
        """设备选择状态改变时的处理"""
        # 更新设备文件夹显示状态
        self.update_device_folders_visibility()
        # 更新下载按钮状态
        self.update_download_button_state()

    def update_device_folders_visibility(self):
        """更新设备文件夹显示状态"""
        for device_id, checkbox in self.device_checkboxes.items():
            if device_id in self.device_folder_containers:
                folder_container = self.device_folder_containers[device_id]
                folder_container.setVisible(checkbox.isChecked())

    def get_device_folders(self, device_id):
        """获取指定设备的文件夹列表（使用INI文件中定义的固定路径）"""
        # 直接使用INI文件中定义的固定路径，不进行动态检测
        return self.load_fixed_source_paths()

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



    def update_download_button_state(self):
        """更新下载按钮状态"""
        # 检查是否有选中的设备
        has_selected_device = False
        for device_id, checkbox in self.device_checkboxes.items():
            if checkbox.isChecked():
                has_selected_device = True
                break
        
        # 检查是否有选中的设备文件夹
        has_selected_folders = False
        if has_selected_device:
            for device_id, folder_checkboxes in self.device_folder_checkboxes.items():
                if device_id in self.device_checkboxes and self.device_checkboxes[device_id].isChecked():
                    for folder_name, checkbox in folder_checkboxes.items():
                        if checkbox.isChecked():
                            has_selected_folders = True
                            break
                if has_selected_folders:
                    break
        
        # 检查是否有目标路径
        has_destination = bool(self.dest_location_input.text().strip())
        
        self.download_btn.setEnabled(has_selected_device and has_selected_folders and has_destination)

    def start_download(self):
        """开始下载"""
        
        # 获取选中的设备和文件夹组合
        device_folder_combinations = []
        # 获取路径到自定义名称的映射
        path_name_dict = self.load_fixed_source_paths()
        
        for device_id, checkbox in self.device_checkboxes.items():
            if checkbox.isChecked():
                device_display_name = self.get_device_display_name(device_id)
                if device_id in self.device_folder_checkboxes:
                    for folder_path, folder_checkbox in self.device_folder_checkboxes[device_id].items():
                        if folder_checkbox.isChecked():
                            # 获取自定义名称，如果没有则使用路径
                            custom_name = path_name_dict.get(folder_path, folder_path)
                            device_folder_combinations.append({
                                'device_id': device_id,
                                'device_display_name': device_display_name,
                                'folder_path': folder_path,
                                'custom_name': custom_name
                            })
        
        if not device_folder_combinations:
            QMessageBox.warning(self, "警告", "请选择至少一个设备和文件夹组合！")
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
        
        # 创建个体进度条
        self.create_individual_progress_bars(device_folder_combinations)
        
        # 创建下载线程
        self.download_thread = DownloadThread(
            device_folder_combinations, 
            dest_path, 
            self.subfolder_combo.currentText(),
            self.device_name_mapping,  # 传递设备名称映射
            self.custom_subfolder_input.currentText().strip()  # 传递自定义子文件夹名称
        )
        self.download_thread.download_finished.connect(self.download_finished)
        self.download_thread.folder_not_found.connect(self.handle_folder_not_found)  # 连接新信号
        
        # 连接新的进度信号
        self.download_thread.task_progress_updated.connect(self.update_individual_progress)
        
        self.download_thread.start()
        
        # 禁用下载按钮
        self.download_btn.setEnabled(False)



    def create_individual_progress_bars(self, device_folder_combinations):
        """为选中的设备和文件夹组合创建进度条"""
        # 清除现有的进度条
        self.clear_progress_bars()
        
        # 为每个设备-文件夹组合创建进度条（两列显示）
        for idx, combination in enumerate(device_folder_combinations):
            device_id = combination['device_id']
            device_display_name = combination['device_display_name']
            folder_path = combination['folder_path']
            custom_name = combination['custom_name']
            
            # 创建进度条容器
            progress_container = QWidget()
            progress_layout = QHBoxLayout(progress_container)
            progress_layout.setContentsMargins(0, 0, 0, 0)
            progress_layout.setSpacing(5)
            # 让容器在水平方向尽量填满
            progress_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            
            # 创建标签，显示自定义名称
            label = QLabel(f"{device_display_name} - {custom_name}")
            label.setStyleSheet("color: #2c3e50; font-weight: bold; min-width: 150px;")
            label.setWordWrap(True)
            # 设置鼠标悬浮提示，显示完整路径
            label.setToolTip(f"路径: {folder_path}")
            
            # 创建进度条
            progress_bar = QProgressBar()
            progress_bar.setRange(0, 100)
            progress_bar.setValue(0)
            progress_bar.setFormat("")  # 不显示内置百分比
            progress_bar.setMinimumWidth(100)
            progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            
            # 创建百分比标签
            percentage_label = QLabel("0%")
            percentage_label.setStyleSheet("color: #2c3e50; font-weight: bold; min-width: 40px;")
            percentage_label.setAlignment(Qt.AlignCenter)
            
            # 添加到布局（设置伸展因子，使进度条占据剩余空间）
            progress_layout.addWidget(label)
            progress_layout.addWidget(progress_bar)
            progress_layout.addWidget(percentage_label)
            progress_layout.setStretch(0, 0)  # label
            progress_layout.setStretch(1, 1)  # progress bar
            progress_layout.setStretch(2, 0)  # percent label
            
            # 添加到网格布局（两列）
            row = idx // 2
            col = idx % 2
            self.progress_bars_layout.addWidget(progress_container, row, col)
            
            # 存储引用，使用路径作为键（因为task_progress_updated信号使用路径）
            key = f"{device_id}:{folder_path}"
            self.progress_bars_dict[key] = (progress_bar, label, percentage_label)
        
        # 如果没有进度条，显示提示信息
        if not self.progress_bars_dict:
            no_tasks_label = QLabel("没有选中的下载任务")
            no_tasks_label.setStyleSheet("color: #7f8c8d; font-style: italic; text-align: center;")
            # 跨两列显示
            self.progress_bars_layout.addWidget(no_tasks_label, 0, 0, 1, 2)

    def clear_progress_bars(self):
        """清除所有进度条"""
        # 清除字典
        self.progress_bars_dict.clear()
        
        # 清除布局中的所有widget
        for i in reversed(range(self.progress_bars_layout.count())):
            widget = self.progress_bars_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()

    def update_individual_progress(self, device_id, folder_path, progress):
        """更新指定设备-文件夹的进度条"""
        key = f"{device_id}:{folder_path}"
        if key in self.progress_bars_dict:
            progress_bar, label, percentage_label = self.progress_bars_dict[key]
            progress_bar.setValue(progress)
            percentage_label.setText(f"{progress}%")
            
            # 更新进度信息
            device_display_name = self.device_name_mapping.get(device_id, device_id)



    def download_finished(self, success_count, total_count, failed_devices):
        """下载完成处理"""
        self.download_btn.setEnabled(True)


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
            
            # 更新下载按钮状态（确保按钮状态正确）
            self.update_download_button_state()
        else:
            # 用户取消了选择
            self.download_btn.setEnabled(True)
            
            # 更新下载按钮状态
            self.update_download_button_state()

    def open_rename_tool(self):
        """打开文件重命名工具"""
        try:
            # 获取当前设置的目标路径
            target_path = self.dest_location_input.text().strip()
            if not target_path or not os.path.exists(target_path):
                QMessageBox.warning(self, "路径错误", "请先设置有效的目标路径！")
                return
            
            # 启动FileOrganizer重命名工具，并传入目标路径
            self.file_organizer = FileOrganizer()
            # 设置文件夹路径（不再需要folder_input，直接使用set_folder_path）
            self.file_organizer.set_folder_path(target_path)
            self.file_organizer.show()
            print(f"已启动文件重命名工具，路径: {target_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动重命名工具失败: {str(e)}")
            print(f"启动重命名工具失败: {str(e)}")

    def closeEvent(self, event):
        """窗口关闭事件"""
        if hasattr(self, 'refresh_timer'):
            self.refresh_timer.stop()
        if hasattr(self, 'download_thread') and self.download_thread.isRunning():
            self.download_thread.terminate()
            self.download_thread.wait()
        
        # 关闭重命名工具窗口
        if hasattr(self, 'file_organizer') and self.file_organizer is not None:
            self.file_organizer.close()
        
        event.accept()


class DownloadThread(QThread):
    """下载线程"""
    
    progress_updated = pyqtSignal(str)
    download_finished = pyqtSignal(int, int, list)
    folder_not_found = pyqtSignal(str)  # 新增信号：当目标文件夹不存在时发送
    
    # 新增进度相关信号
    task_progress_updated = pyqtSignal(str, str, int)  # 设备ID, 文件夹名, 进度百分比
    
    def __init__(self, device_folder_combinations, dest_path, subfolder_format, device_name_mapping=None, custom_subfolder_name=None):
        super().__init__()
        self.device_folder_combinations = device_folder_combinations
        self.dest_path = dest_path
        self.subfolder_format = subfolder_format
        self.device_name_mapping = device_name_mapping or {}
        self.custom_subfolder_name = custom_subfolder_name or ""
        
        # 计算总任务数
        self.total_tasks = len(device_folder_combinations)
        self.completed_tasks = 0
    
    def run(self):
        """执行下载"""
        import datetime
        import tempfile
        
        # 初始化进度
        self.completed_tasks = 0
        
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
        failed_combinations = []
        
        for combination in self.device_folder_combinations:
            try:
                device_id = combination['device_id']
                device_display_name = combination['device_display_name']
                folder_path = combination['folder_path']
                custom_name = combination['custom_name']
                
                self.progress_updated.emit(f"正在处理设备: {device_display_name}, 文件夹: {custom_name}")
                
                # 发送任务开始信号
                self.task_progress_updated.emit(device_id, folder_path, 0)
                
                # 规范化源路径
                if folder_path.startswith("sdcard/") or folder_path.startswith("data/"):
                    source_path = f"/{folder_path}"
                else:
                    source_path = f"/sdcard/{folder_path}"
                
                # 目标目录: <dest>/<timestamp>/<device_display_name>/<custom_name>
                # 先按设备分组，再按自定义名称创建子文件夹
                device_folder = os.path.join(timestamp_folder, custom_name)
                custom_folder = os.path.join(device_folder, device_display_name)
                try:
                    os.makedirs(custom_folder, exist_ok=True)
                except Exception as e:
                    self.progress_updated.emit(f"无法创建文件夹 '{custom_folder}': {str(e)}")
                    failed_combinations.append(combination)
                    continue
                
                # 仅拉取目录内容，避免嵌套一层同名目录
                result = self.execute_adb_pull(device_id, source_path, custom_folder, folder_path)
                
                if result:
                    self.progress_updated.emit(f"✓ 设备 {device_display_name} 文件夹 {custom_name} 下载成功")
                    self.task_progress_updated.emit(device_id, folder_path, 100)
                    success_count += 1
                else:
                    self.progress_updated.emit(f"✗ 设备 {device_display_name} 文件夹 {custom_name} 下载失败")
                    self.task_progress_updated.emit(device_id, folder_path, 0)
                    failed_combinations.append(combination)
                
                # 更新任务完成数
                self.completed_tasks += 1
                
            except Exception as e:
                device_display_name = combination.get('device_display_name', 'Unknown')
                custom_name = combination.get('custom_name', 'Unknown')
                self.progress_updated.emit(f"设备 {device_display_name} 文件夹 {custom_name} 处理失败: {str(e)}")
                failed_combinations.append(combination)
        
        # 只有在正常完成下载时才发送完成信号
        failed_devices = list(set([combo['device_id'] for combo in failed_combinations]))
        self.download_finished.emit(success_count, len(self.device_folder_combinations), failed_devices)
    

    def format_timestamp(self, timestamp):
        """格式化时间戳"""
        # 获取时间戳格式，拼接传入的自定义名称
        timesramp_str = ""
        if "年\\月\\日\\时分秒" in self.subfolder_format:
            timesramp_str = timestamp.strftime("%Y-%m-%d-%H-%M-%S")
        elif "年\\月\\日\\时分" in self.subfolder_format:
            timesramp_str = timestamp.strftime("%Y-%m-%d-%H-%M")
        elif "年\\月\\日\\时" in self.subfolder_format:
            timesramp_str = timestamp.strftime("%Y-%m-%d-%H")
        elif "年\\月\\日" in self.subfolder_format:
            timesramp_str = timestamp.strftime("%Y-%m-%d")
        elif "年\\日" in self.subfolder_format:
            timesramp_str = timestamp.strftime("%Y-%m-%d")
        else:
            timesramp_str = timestamp.strftime("%Y-%m-%d")

        # 如果用户输入了自定义名称，直接使用自定义名称
        if self.custom_subfolder_name and self.custom_subfolder_name.strip():
            timesramp_str += self.custom_subfolder_name.strip()

        return timesramp_str
        

    
    def execute_adb_pull(self, device, source_path, dest_path, folder_name):
        """执行adb pull命令并实时显示进度"""
        try:
            startupinfo = None
            if hasattr(subprocess, 'STARTUPINFO'):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            
            # 首先获取源文件夹中的文件数量，用于计算进度
            remote_file_count = self.get_file_count(device, source_path)
            if remote_file_count == 0:
                self.progress_updated.emit(f"源路径 {source_path} 中没有文件，下载已完成")
                # 设置当前任务进度为100%（因为没有文件需要下载）
                self.task_progress_updated.emit(device, folder_name, 100)
                return True
            
            self.progress_updated.emit(f"开始下载 {remote_file_count} 个文件...")
            print(f"[调试] 远程路径 {source_path} 中有 {remote_file_count} 个文件")
            
            # 目标路径设为设备目录，直接将源目录内容拉入，避免多一层同名目录
            local_download_path = dest_path
            
            # 使用实时输出方式执行adb pull（使用/.: 仅复制目录内容）
            # 确保目标路径使用正确的路径分隔符
            dest_path_normalized = dest_path.replace('\\', '/')
            command = f'adb -s {device} pull "{source_path}/." "{dest_path_normalized}"'
            print(f"[调试] 执行命令: {command}")
            print(f"[调试] 目标本地路径: {local_download_path}")
            print(f"[调试] 规范化目标路径: {dest_path_normalized}")
            
            # 创建进程，实时获取输出
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            print(f"[调试] 进程已启动，PID: {process.pid}")
            
            # 实时读取输出并监控本地文件数量
            transferred_files = 0
            last_progress = 0
            last_local_count = 0
            
            # 使用定时器检查本地文件数量
            import threading
            import time
            
            def check_local_files():
                """定时检查本地文件数量的函数"""
                nonlocal last_progress, last_local_count
                while process.poll() is None:  # 进程还在运行时
                    try:
                        local_file_count = self.get_local_file_count(local_download_path)
                        print(f"[调试] 定时器检查本地文件数量: {local_file_count}")
                        
                        # 计算进度百分比，但不超过99%（避免在下载完成前显示100%）
                        if remote_file_count > 0:
                            progress = min(99, int((local_file_count / remote_file_count) * 100))
                            
                            # 更新进度（即使没有变化也要更新，确保UI同步）
                            if progress != last_progress or local_file_count != last_local_count:
                                self.task_progress_updated.emit(device, folder_name, progress)
                                last_progress = progress
                                last_local_count = local_file_count
                                
                                # 显示详细进度信息
                                self.progress_updated.emit(f"下载进度: {local_file_count}/{remote_file_count} 文件 ({progress}%)")
                                print(f"[调试] 定时器进度更新: 本地 {local_file_count}/{remote_file_count} 文件 ({progress}%)")
                            else:
                                print(f"[调试] 定时器进度无变化: 本地 {local_file_count}/{remote_file_count} 文件 ({progress}%)")
                        else:
                            # 如果远程文件数为0，显示100%进度（因为没有文件需要下载就意味着已完成）
                            if last_progress != 100:
                                self.task_progress_updated.emit(device, folder_name, 100)
                                last_progress = 100
                                self.progress_updated.emit("下载进度: 0/0 文件 (100%)")
                                print(f"[调试] 定时器: 远程文件数为0，设置进度为100%")
                    except Exception as e:
                        print(f"[调试] 定时器检查文件数量时出错: {e}")
                    
                    # 每0.5秒检查一次
                    time.sleep(0.5)
                
                # 进程结束后，再检查一次最终的文件数量
                print(f"[调试] 进程已结束，进行最终检查...")
                try:
                    final_local_count = self.get_local_file_count(local_download_path)
                    print(f"[调试] 最终本地文件数量: {final_local_count}")
                    
                    # 如果远程文件数为0，则直接显示100%完成
                    if remote_file_count == 0:
                        self.task_progress_updated.emit(device, folder_name, 100)
                        self.progress_updated.emit(f"下载完成: 源文件夹中没有文件 (100%)")
                        print(f"[调试] 定时器: 源文件夹中没有文件，显示100%进度")
                    # 如果文件数量达到或接近目标，显示100%
                    elif remote_file_count > 0 and final_local_count >= remote_file_count * 0.95:  # 95%以上认为完成
                        self.task_progress_updated.emit(device, folder_name, 100)
                        self.progress_updated.emit(f"下载完成: {final_local_count}/{remote_file_count} 文件 (100%)")
                        print(f"[调试] 定时器: 下载完成，显示100%进度")
                    else:
                        # 否则显示实际进度
                        final_progress = min(99, int((final_local_count / remote_file_count) * 100)) if remote_file_count > 0 else 100
                        self.task_progress_updated.emit(device, folder_name, final_progress)
                        self.progress_updated.emit(f"下载进度: {final_local_count}/{remote_file_count} 文件 ({final_progress}%)")
                        print(f"[调试] 定时器: 最终进度 {final_progress}%")
                except Exception as e:
                    print(f"[调试] 定时器最终检查时出错: {e}")
            
            # 启动定时器线程
            timer_thread = threading.Thread(target=check_local_files, daemon=True)
            timer_thread.start()
            print(f"[调试] 定时器线程已启动")
            
            # 使用非阻塞方式读取输出
            import select
            
            loop_count = 0
            while True:
                loop_count += 1
                # 检查进程是否结束
                if process.poll() is not None:
                    print(f"[调试] 进程已结束，返回码: {process.returncode}")
                    break
                
                # 检查是否有输出可读
                if hasattr(select, 'select'):
                    # Unix/Linux系统
                    ready, _, _ = select.select([process.stdout, process.stderr], [], [], 0.1)
                    if ready:
                        # 读取stdout
                        if process.stdout in ready:
                            output = process.stdout.readline()
                            if output:
                                output = output.strip()
                                print(f"[调试] 收到adb输出: {output}")
                                
                                # 解析adb pull的输出，查找文件传输信息
                                if output.endswith(' files pulled') or 'files pulled' in output:
                                    # 提取传输的文件数量
                                    try:
                                        parts = output.split()
                                        if len(parts) >= 2:
                                            transferred_files = int(parts[0])
                                            progress = min(99, int((transferred_files / remote_file_count) * 100))
                                            self.task_progress_updated.emit(device, folder_name, progress)
                                            self.progress_updated.emit(f"下载进度: {transferred_files}/{remote_file_count} 文件 ({progress}%)")
                                    except (ValueError, IndexError):
                                        pass
                                elif 'pulled' in output and 'files' in output:
                                    # 另一种输出格式
                                    try:
                                        parts = output.split()
                                        if len(parts) >= 2:
                                            transferred_files = int(parts[0])
                                            progress = min(99, int((transferred_files / remote_file_count) * 100))
                                            self.task_progress_updated.emit(device, folder_name, progress)
                                            self.progress_updated.emit(f"下载进度: {transferred_files}/{remote_file_count} 文件 ({progress}%)")
                                    except (ValueError, IndexError):
                                        pass
                        
                        # 读取stderr
                        if process.stderr in ready:
                            error_output = process.stderr.readline()
                            if error_output:
                                error_output = error_output.strip()
                                print(f"[调试] 收到adb错误输出: {error_output}")
                                self.progress_updated.emit(f"警告: {error_output}")
                else:
                    # Windows系统，使用简单的非阻塞读取
                    try:
                        # 读取stdout
                        output = process.stdout.readline()
                        if output:
                            output = output.strip()
                            print(f"[调试] 收到adb输出(Windows): {output}")
                            
                            # 解析adb pull的输出，查找文件传输信息
                            if output.endswith(' files pulled') or 'files pulled' in output:
                                # 提取传输的文件数量
                                try:
                                    parts = output.split()
                                    if len(parts) >= 2:
                                        transferred_files = int(parts[0])
                                        progress = min(99, int((transferred_files / remote_file_count) * 100))
                                        self.task_progress_updated.emit(device, folder_name, progress)
                                        self.progress_updated.emit(f"下载进度: {transferred_files}/{remote_file_count} 文件 ({progress}%)")
                                except (ValueError, IndexError):
                                    pass
                            elif 'pulled' in output and 'files' in output:
                                # 另一种输出格式
                                try:
                                    parts = output.split()
                                    if len(parts) >= 2:
                                        transferred_files = int(parts[0])
                                        progress = min(99, int((transferred_files / remote_file_count) * 100))
                                        self.task_progress_updated.emit(device, folder_name, progress)
                                        self.progress_updated.emit(f"下载进度: {transferred_files}/{remote_file_count} 文件 ({progress}%)")
                                except (ValueError, IndexError):
                                    pass
                        
                        # 读取stderr
                        error_output = process.stderr.readline()
                        if error_output:
                            error_output = error_output.strip()
                            print(f"[调试] 收到adb错误输出(Windows): {error_output}")
                            self.progress_updated.emit(f"警告: {error_output}")
                    except:
                        pass
                
                # 短暂休眠，避免CPU占用过高
                time.sleep(0.1)
            
            # 等待进程完成
            print(f"[调试] 等待进程完成...")
            return_code = process.wait()
            print(f"[调试] 进程完成，返回码: {return_code}")
            
            # 等待定时器线程完成最终检查
            print(f"[调试] 等待定时器线程完成最终检查...")
            timer_thread.join(timeout=2)  # 等待最多2秒
            
            # 最终检查本地文件数量
            final_local_count = self.get_local_file_count(local_download_path)
            print(f"[调试] 主线程最终检查，本地文件数量: {final_local_count}")
            
            if return_code == 0:
                # 如果远程文件数为0，则直接返回成功
                if remote_file_count == 0:
                    self.task_progress_updated.emit(device, folder_name, 100)
                    self.progress_updated.emit(f"✓ 下载完成，源文件夹中没有文件")
                    return True
                # 检查是否真的有文件被下载
                elif final_local_count > 0:
                    # 只有在定时器没有设置100%的情况下才设置
                    if final_local_count >= remote_file_count * 0.95:  # 95%以上认为完成
                        self.task_progress_updated.emit(device, folder_name, 100)
                        self.progress_updated.emit(f"✓ 下载完成，远程 {remote_file_count} 个文件，本地 {final_local_count} 个文件")
                    else:
                        final_progress = int((final_local_count / remote_file_count) * 100)
                        self.task_progress_updated.emit(device, folder_name, final_progress)
                        self.progress_updated.emit(f"下载进度: {final_local_count}/{remote_file_count} 文件 ({final_progress}%)")
                    return True
                else:
                    # 返回码是0但没有文件，可能是路径问题
                    error_output = process.stderr.read()
                    print(f"[调试] 下载完成但无文件，错误输出: {error_output}")
                    self.progress_updated.emit(f"✗ 下载完成但无文件，可能路径错误: {error_output}")
                    return False
            else:
                error_output = process.stderr.read()
                print(f"[调试] 下载失败，返回码: {return_code}, 错误输出: {error_output}")
                self.progress_updated.emit(f"✗ 下载失败 (返回码: {return_code}): {error_output}")
                return False
                
        except Exception as e:
            self.progress_updated.emit(f"✗ 执行adb pull命令时出错: {e}")
            return False
    
    def get_file_count(self, device, source_path):
        """获取源路径中的文件数量"""
        try:
            startupinfo = None
            if hasattr(subprocess, 'STARTUPINFO'):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            
            # 使用adb shell find命令统计文件数量，只统计非空文件
            command = f'adb -s {device} shell "find {source_path} -type f -size +0c | wc -l"'
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
                try:
                    count = int(result.stdout.strip())
                    return count if count > 0 else 0
                except ValueError:
                    return 0
            else:
                # 如果上面的命令失败，尝试简单的find命令
                command = f'adb -s {device} shell "find {source_path} -type f | wc -l"'
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
                    try:
                        return int(result.stdout.strip())
                    except ValueError:
                        return 0
                else:
                    return 0
                
        except Exception:
            return 0
    
    def get_local_file_count(self, local_path):
        """获取本地文件夹中的文件数量"""
        try:
            if not os.path.exists(local_path):
                print(f"[调试] 本地路径不存在: {local_path}")
                return 0
            
            file_count = 0
            total_files = 0
            for root, dirs, files in os.walk(local_path):
                total_files += len(files)
                # 只统计文件，不包括目录
                for file in files:
                    file_path = os.path.join(root, file)
                    # 检查文件是否存在且不为空（避免统计正在写入的文件）
                    if os.path.isfile(file_path) and os.path.getsize(file_path) > 0:
                        file_count += 1
            
            if file_count != total_files:
                print(f"[调试] 本地路径 {local_path}: 总文件数 {total_files}, 有效文件数 {file_count}")
            
            return file_count
        except Exception as e:
            print(f"[调试] 统计本地文件数量时出错: {e}")
            return 0
    

class InstallApkThread(QThread):
    """后台安装APK线程，支持进度与取消"""
    progress_changed = pyqtSignal(int, int, str)  # 当前序号, 总数, 当前文件
    install_finished = pyqtSignal(list, list, bool)  # 成功列表, 失败列表, 是否取消

    def __init__(self, device_id, apk_files):
        super().__init__()
        self.device_id = device_id
        self.apk_files = list(apk_files)
        self._cancel_requested = False

    def request_cancel(self):
        self._cancel_requested = True

    def run(self):
        success_list = []
        failed_list = []
        total = len(self.apk_files)

        startupinfo = None
        if hasattr(subprocess, 'STARTUPINFO'):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        for idx, apk_path in enumerate(self.apk_files, start=1):
            if self._cancel_requested:
                self.install_finished.emit(success_list, failed_list, True)
                return

            # 更新进度（开始安装当前APK前）
            self.progress_changed.emit(idx - 1, total, apk_path)
            command = f"adb -s {self.device_id} install -r \"{apk_path}\""
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    startupinfo=startupinfo
                )
                if result.returncode == 0 and ("Success" in (result.stdout or "") or not result.stderr):
                    success_list.append(os.path.basename(apk_path))
                else:
                    reason = (result.stderr or result.stdout or '').strip()
                    failed_list.append(f"{os.path.basename(apk_path)} -> {reason[:160]}")
            except Exception as e:
                failed_list.append(f"{os.path.basename(apk_path)} -> {str(e)}")

        # 进度设置为完成
        self.progress_changed.emit(total, total, "")
        self.install_finished.emit(success_list, failed_list, False)



if __name__ == "__main__":
    app = QApplication(sys.argv)
    apply_stylesheet(app, theme='light_blue.xml', extra={'font_size': 16})
    ex = LogVerboseMaskApp()
    ex.show()
    sys.exit(app.exec_())

