import sys
import os
import tempfile
import re
import shlex
import datetime
try:
    import winreg
except Exception:
    winreg = None
# 可选：从资源管理器读取选中项所需
try:
    import win32com.client  # type: ignore
    import pythoncom  # type: ignore
except Exception:
    win32com = None
try:
    import ctypes
    from ctypes import wintypes
except Exception:
    ctypes = None
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QMessageBox,
    QFileDialog,
    QLabel,
    QDialog,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QHeaderView,
    QCheckBox,
    QMenu,
    QAction,
    QTreeView,
    QGroupBox,
    QSplitter,
    QFrame,
    QScrollArea,
    QStatusBar,
    QSystemTrayIcon,
)
from PyQt5.QtCore import QSettings, Qt, pyqtSignal, QDir, QModelIndex, QAbstractNativeEventFilter
from PyQt5.QtGui import QKeySequence, QIcon, QFont
from PyQt5.QtWidgets import QShortcut, QFileSystemModel
from PyQt5.QtCore import QSortFilterProxyModel
from qt_material import apply_stylesheet

class ExcludeFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.excluded_paths = set()
        self.hide_all = False
        self.included_paths = set()

    def set_excluded(self, paths):
        self.excluded_paths = set(paths or [])
        self.invalidateFilter()

    def clear_excluded(self):
        self.excluded_paths.clear()
        self.invalidateFilter()

    def set_hide_all(self, flag: bool):
        self.hide_all = bool(flag)
        self.invalidateFilter()

    def set_included(self, paths):
        # 归一化路径，避免分隔符大小写差异
        normed = set()
        for p in (paths or []):
            try:
                normed.add(os.path.normcase(os.path.normpath(p)))
            except Exception:
                normed.add(p)
        self.included_paths = normed
        self.invalidateFilter()

    def clear_included(self):
        self.included_paths.clear()
        self.invalidateFilter()

    def remove_from_included(self, paths):
        changed = False
        for p in (paths or []):
            try:
                key = os.path.normcase(os.path.normpath(p))
            except Exception:
                key = p
            if key in self.included_paths:
                self.included_paths.discard(key)
                changed = True
        if changed:
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if self.hide_all:
            return False
        source_index = self.sourceModel().index(source_row, 0, source_parent)
        if not source_index.isValid():
            return True
        model = self.sourceModel()
        try:
            file_path = model.filePath(source_index)
        except Exception:
            return True
        # 统一规范化
        try:
            file_path_norm = os.path.normcase(os.path.normpath(file_path))
        except Exception:
            file_path_norm = file_path
        # 先应用排除规则（排除优先于包含）
        for p in self.excluded_paths:
            if file_path_norm == p or file_path_norm.startswith(p + os.sep):
                return False
        # 如果设置了包含白名单，仅显示白名单文件与其祖先目录
        if self.included_paths:
            for p in self.included_paths:
                if file_path_norm == p:
                    return True
                # file_path 是 p 的祖先（目录）→ 显示祖先链以便展开到白名单项
                if p.startswith(file_path_norm + os.sep):
                    return True
                # file_path 是 p 的后代（当 p 为目录时）→ 显示所选目录的所有子项
                if file_path_norm.startswith(p + os.sep):
                    return True
            return False
        return True



class PowerRenameDialog(QWidget):
    # 定义信号
    window_closed = pyqtSignal()
    
    def __init__(self, file_list, parent=None):
        super().__init__(parent)
        self.file_list = file_list
        self.preview_data = []
        self.updating_preview = False  # 添加标志位防止递归调用
        self.initUI()
        
    def _natural_sort_key(self, path_or_name):
        """返回用于自然排序的键，使 '1' < '2' < '10'。

        仅对末级文件名进行分段；非数字段使用小写比较以稳定排序。
        """
        try:
            name = os.path.basename(path_or_name)
        except Exception:
            name = str(path_or_name)
        try:
            parts = re.split(r"(\d+)", name)
            return [int(p) if p.isdigit() else p.lower() for p in parts]
        except Exception:
            return [name.lower()]

    def initUI(self):
        self.setWindowTitle("PowerRename")
        self.resize(1200, 700)
        self.setMinimumSize(800, 600)
        
        # 设置窗口置顶
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        
        # 设置图标
        icon_path = os.path.join(os.path.dirname(__file__), "icon", "rename.ico")
        self.setWindowIcon(QIcon(icon_path))
        
        # 主布局
        main_layout = QVBoxLayout()
        
        # 创建分割器
        splitter = QSplitter(Qt.Horizontal)
        
        # 左侧控制面板
        left_panel = self.create_control_panel()
        splitter.addWidget(left_panel)
        
        # 右侧预览面板
        right_panel = self.create_preview_panel()
        splitter.addWidget(right_panel)
        
        # 设置分割器比例
        splitter.setSizes([400, 600])
        
        main_layout.addWidget(splitter)
        self.setLayout(main_layout)
        
        # 初始化预览 - 默认显示原始文件
        self.show_original_files()
        
    def create_control_panel(self):
        """创建左侧控制面板"""
        panel = QFrame()
        panel.setFrameStyle(QFrame.StyledPanel)
        layout = QVBoxLayout()
        
        # 查找字段
        search_group = QGroupBox("查找")
        search_layout = QVBoxLayout()
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入要查找的文本")
        self.search_input.textChanged.connect(self.update_preview)
        search_layout.addWidget(self.search_input)
        
        # 选项复选框
        options_layout = QVBoxLayout()
        self.regex_checkbox = QCheckBox("使用正则表达式")
        self.regex_checkbox.stateChanged.connect(self.update_preview)
        self.match_all_checkbox = QCheckBox("匹配所有出现的对象")
        self.match_all_checkbox.stateChanged.connect(self.update_preview)
        self.case_sensitive_checkbox = QCheckBox("区分大小写")
        self.case_sensitive_checkbox.stateChanged.connect(self.update_preview)
        
        options_layout.addWidget(self.regex_checkbox)
        options_layout.addWidget(self.match_all_checkbox)
        options_layout.addWidget(self.case_sensitive_checkbox)
        search_layout.addLayout(options_layout)
        
        search_group.setLayout(search_layout)
        layout.addWidget(search_group)
        
        # 替换字段
        replace_group = QGroupBox("替换")
        replace_layout = QVBoxLayout()
        
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("# 数字, $p 文件夹名, $$p两级文件夹")
        self.replace_input.textChanged.connect(self.update_preview)
        replace_layout.addWidget(self.replace_input)
        
        # 应用于选项 - 改为复选框，水平布局
        apply_group = QGroupBox("应用于")
        apply_layout = QHBoxLayout()
        
        self.include_files_checkbox = QCheckBox("包含文件")
        self.include_files_checkbox.setChecked(True)  # 默认勾选
        self.include_files_checkbox.stateChanged.connect(self.update_preview)
        
        self.include_folders_checkbox = QCheckBox("包含文件夹")
        self.include_folders_checkbox.stateChanged.connect(self.update_preview)
        
        self.include_subfolders_checkbox = QCheckBox("包含子文件夹")
        self.include_subfolders_checkbox.stateChanged.connect(self.update_preview)
        
        apply_layout.addWidget(self.include_files_checkbox)
        apply_layout.addWidget(self.include_folders_checkbox)
        apply_layout.addWidget(self.include_subfolders_checkbox)
        
        apply_group.setLayout(apply_layout)
        replace_layout.addWidget(apply_group)
        
        replace_group.setLayout(replace_layout)
        layout.addWidget(replace_group)
        
        # 文本格式 - 改为单选框，水平布局
        format_group = QGroupBox("文本格式")
        format_layout = QHBoxLayout()
        
        # 创建按钮组用于单选框
        from PyQt5.QtWidgets import QButtonGroup
        self.format_button_group = QButtonGroup()
        
        self.lowercase_radio = QPushButton("aa")
        self.lowercase_radio.setCheckable(True)
        self.lowercase_radio.setToolTip("小写")
        self.lowercase_radio.clicked.connect(self.apply_text_format)
        
        self.uppercase_radio = QPushButton("AA")
        self.uppercase_radio.setCheckable(True)
        self.uppercase_radio.setToolTip("大写")
        self.uppercase_radio.clicked.connect(self.apply_text_format)
        
        self.capitalize_radio = QPushButton("Aa")
        self.capitalize_radio.setCheckable(True)
        self.capitalize_radio.setToolTip("首字母大写")
        self.capitalize_radio.clicked.connect(self.apply_text_format)
        
        self.title_radio = QPushButton("Aa Aa")
        self.title_radio.setCheckable(True)
        self.title_radio.setToolTip("每个单词首字母大写")
        self.title_radio.clicked.connect(self.apply_text_format)
        
        # 添加到按钮组
        self.format_button_group.addButton(self.lowercase_radio, 0)
        self.format_button_group.addButton(self.uppercase_radio, 1)
        self.format_button_group.addButton(self.capitalize_radio, 2)
        self.format_button_group.addButton(self.title_radio, 3)
        
        format_layout.addWidget(self.lowercase_radio)
        format_layout.addWidget(self.uppercase_radio)
        format_layout.addWidget(self.capitalize_radio)
        format_layout.addWidget(self.title_radio)
        
        format_group.setLayout(format_layout)
        layout.addWidget(format_group)
        
        # 底部按钮 - 将应用按钮放到右下角
        button_layout = QHBoxLayout()
        button_layout.addStretch()  # 添加弹性空间，将按钮推到右边
        self.apply_btn = QPushButton("应用")
        self.apply_btn.clicked.connect(self.apply_rename)
        self.apply_btn.setMinimumWidth(80)  # 设置按钮最小宽度
        
        button_layout.addWidget(self.apply_btn)
        
        layout.addLayout(button_layout)
        
        panel.setLayout(layout)
        return panel
        
    def create_preview_panel(self):
        """创建右侧预览面板"""
        panel = QFrame()
        panel.setFrameStyle(QFrame.StyledPanel)
        layout = QVBoxLayout()
        
        # 预览标题 - 使用网格布局确保对齐
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        
        # 全选复选框
        self.select_all_checkbox = QCheckBox()
        self.select_all_checkbox.setChecked(True)  # 默认全选
        self.select_all_checkbox.stateChanged.connect(self.toggle_select_all)
        
        self.original_label = QLabel("原始 (0)")
        self.original_label.setFont(QFont("Arial", 10, QFont.Bold))
        self.renamed_label = QLabel("已重命名 (0)")
        self.renamed_label.setFont(QFont("Arial", 10, QFont.Bold))
        
        # 设置标签样式，确保与表格列对齐
        self.original_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.renamed_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        # 添加弹性空间，使标签与表格列对齐
        title_layout.addWidget(self.select_all_checkbox)
        title_layout.addWidget(self.original_label)
        title_layout.addStretch(1)
        title_layout.addWidget(self.renamed_label)
        title_layout.addStretch(1)
        
        layout.addLayout(title_layout)
        
        # 预览表格
        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(3)
        self.preview_table.setHorizontalHeaderLabels(["", "原始文件名", "重命名后"])
        
        # 隐藏行号索引
        self.preview_table.verticalHeader().hide()
        
        # 设置表格属性
        header = self.preview_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)  # 复选框列固定宽度
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # 原始文件名列拉伸
        header.setSectionResizeMode(2, QHeaderView.Stretch)  # 重命名后列拉伸
        header.resizeSection(0, 30)  # 设置复选框列宽度
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setSelectionBehavior(QTableWidget.SelectRows)
        
        # 设置表格边距，确保与标题对齐
        self.preview_table.setContentsMargins(0, 0, 0, 0)
        self.preview_table.setShowGrid(True)
        
        layout.addWidget(self.preview_table)
        
        panel.setLayout(layout)
        return panel
        
    def update_preview(self):
        """更新预览"""
        search_text = self.search_input.text()
        replace_text = self.replace_input.text()
        
        # 始终显示所有原始文件，但根据查找/替换条件更新重命名预览
        self.preview_data = []
        
        # 按文件夹分组文件，用于生成序号
        from collections import defaultdict
        folder_to_files = defaultdict(list)
        for file_path in sorted(self.file_list, key=self._natural_sort_key):
            if os.path.isfile(file_path):
                folder_path = os.path.dirname(file_path)
                folder_to_files[folder_path].append(file_path)
        
        for folder_path, files in folder_to_files.items():
            # 按文件夹内的文件顺序生成序号
            for index, file_path in enumerate(files):
                original_name = os.path.basename(file_path)
                
                # 如果没有查找文本，重命名列为空
                if not search_text:
                    self.preview_data.append((folder_path, original_name, original_name))
                    continue
                
                # 根据"应用于"复选框确定处理范围
                if self.include_files_checkbox.isChecked():
                    # 处理文件名
                    name_part = os.path.splitext(original_name)[0]
                    ext_part = os.path.splitext(original_name)[1]
                    new_name_part = self.perform_replace_with_special_chars(
                        name_part, search_text, replace_text, folder_path, index
                    )
                    new_name = new_name_part + ext_part
                else:
                    new_name = original_name
                
                # 添加所有文件到预览数据中，包括不修改的文件
                self.preview_data.append((folder_path, original_name, new_name))
        
        self.update_preview_table()
        
    def show_original_files(self):
        """显示原始文件列表"""
        self.preview_data = []
        
        # 显示所有原始文件，包括重命名后的文件
        for file_path in sorted(self.file_list, key=self._natural_sort_key):
            if not os.path.isfile(file_path):
                continue
                
            original_name = os.path.basename(file_path)
            folder_path = os.path.dirname(file_path)
            
            # 显示原始文件名，用于程序启动时显示
            self.preview_data.append((folder_path, original_name, original_name))
        
        print(f"显示原始文件: {len(self.preview_data)} 个文件")
        self.update_preview_table()
        
    def apply_text_format(self):
        """应用文本格式 - 触发预览更新"""
        # 文本格式改变时，重新计算预览
        self.update_preview()
        
    def format_text(self, text, button):
        """根据选中的按钮格式化文本"""
        if button == self.lowercase_radio:
            return text.lower()
        elif button == self.uppercase_radio:
            return text.upper()
        elif button == self.capitalize_radio:
            return text.capitalize()
        elif button == self.title_radio:
            return text.title()
        return text
        
    def perform_replace(self, text, search_text, replace_text):
        """执行替换操作"""
        if not search_text:
            return text
            
        try:
            if self.regex_checkbox.isChecked():
                # 使用正则表达式
                flags = 0 if self.case_sensitive_checkbox.isChecked() else re.IGNORECASE
                if self.match_all_checkbox.isChecked():
                    new_text = re.sub(search_text, replace_text, text, flags=flags)
                else:
                    new_text = re.sub(search_text, replace_text, text, count=1, flags=flags)
            else:
                # 普通文本替换
                if self.case_sensitive_checkbox.isChecked():
                    if self.match_all_checkbox.isChecked():
                        new_text = text.replace(search_text, replace_text)
                    else:
                        new_text = text.replace(search_text, replace_text, 1)
                else:
                    # 不区分大小写 - 使用简单的不区分大小写替换
                    new_text = self.case_insensitive_replace(text, search_text, replace_text, self.match_all_checkbox.isChecked())
        except Exception as e:
            print(f"替换错误: {e}")
            print(f"查找文本: '{search_text}'")
            print(f"替换文本: '{replace_text}'")
            print(f"原文本: '{text}'")
            print(f"使用正则表达式: {self.regex_checkbox.isChecked()}")
            print(f"区分大小写: {self.case_sensitive_checkbox.isChecked()}")
            print(f"匹配所有: {self.match_all_checkbox.isChecked()}")
            
            # 如果正则表达式失败，回退到普通字符串替换
            try:
                if self.case_sensitive_checkbox.isChecked():
                    new_text = text.replace(search_text, replace_text)
                else:
                    # 不区分大小写的简单替换
                    new_text = text.replace(search_text.lower(), replace_text.lower())
                    # 如果小写替换没有效果，尝试原样替换
                    if new_text == text:
                        new_text = text.replace(search_text, replace_text)
            except Exception as e2:
                print(f"回退替换也失败: {e2}")
                return text
        
        # 应用文本格式到替换后的文本
        new_text = self.apply_text_format_to_result(new_text)
        return new_text

    def perform_replace_with_special_chars(self, text, search_text, replace_text, folder_path, index):
        """执行带有特殊字符的替换操作"""
        if not search_text:
            return text
            
        # 首先进行普通的查找替换
        new_text = self.perform_replace(text, search_text, replace_text)
        
        # 然后处理替换文本中的特殊字符
        if replace_text:
            # 获取文件夹信息
            folder_name = os.path.basename(folder_path)
            parent_folder_name = os.path.basename(os.path.dirname(folder_path))
            
            # 获取当前日期
            now = datetime.datetime.now()
            
            # 处理日期格式
            new_text = new_text.replace("$YYYY", str(now.year))  # 年，如 2025
            new_text = new_text.replace("$MM", f"{now.month:02d}")  # 月，如 02
            new_text = new_text.replace("$DD", f"{now.day:02d}")  # 日，如 02
            new_text = new_text.replace("$yyyy", str(now.year))  # 年，如 2025
            new_text = new_text.replace("$mm", f"{now.month:02d}")  # 月，如 02
            new_text = new_text.replace("$dd", f"{now.day:02d}")  # 日，如 02
            
            # 处理 # 字符 - 数字序号（支持新的格式）
            import re
            
            # 先处理带等号的格式，如 #=1, ##=1, ###=21
            # 匹配 # 后跟 = 再跟数字的模式，如 #=1, ##=1, ###=21
            hash_equals_number_pattern = r'#+=(\d+)'
            matches = re.finditer(hash_equals_number_pattern, new_text)
            
            # 从后往前替换，避免位置偏移问题
            for match in reversed(list(matches)):
                full_match = match.group()
                start_number = int(match.group(1))
                # 计算 # 的数量：总长度 - = 的长度 - 数字的长度
                hash_count = len(full_match) - 1 - len(match.group(1))
                
                # 计算实际数字：index + start_number
                actual_number = index + start_number
                number_format = f"{{:0{hash_count}d}}"
                formatted_number = number_format.format(actual_number)
                
                # 替换匹配的部分
                new_text = new_text[:match.start()] + formatted_number + new_text[match.end():]
            
            # 处理纯 # 字符 - 数字序号（原有功能，不包含等号和数字的）
            # 只处理不包含等号和数字的纯 # 序列
            pure_hash_pattern = r'#+(?![=0-9])'
            pure_matches = re.finditer(pure_hash_pattern, new_text)
            
            for match in reversed(list(pure_matches)):
                hash_group = match.group()
                number_format = f"{{:0{len(hash_group)}d}}"
                formatted_number = number_format.format(index)
                new_text = new_text[:match.start()] + formatted_number + new_text[match.end():]
            
            # 处理 $p 和 $$p - 文件夹名
            new_text = new_text.replace("$$p", f"{parent_folder_name}_{folder_name}")
            new_text = new_text.replace("$$P", f"{parent_folder_name}_{folder_name}")
            new_text = new_text.replace("$p", folder_name)
        
        return new_text
        
    def apply_text_format_to_result(self, text):
        """对重命名结果应用文本格式"""
        # 获取当前选中的格式按钮
        selected_button = self.format_button_group.checkedButton()
        if not selected_button:
            return text
            
        return self.format_text(text, selected_button)
        
    def case_insensitive_replace(self, text, search_text, replace_text, replace_all=True):
        """不区分大小写的字符串替换"""
        if not search_text:
            return text
            
        result = text
        search_lower = search_text.lower()
        text_lower = text.lower()
        
        if replace_all:
            # 替换所有匹配项
            start = 0
            while True:
                pos = text_lower.find(search_lower, start)
                if pos == -1:
                    break
                # 找到匹配位置，进行替换
                result = result[:pos] + replace_text + result[pos + len(search_text):]
                text_lower = result.lower()  # 更新小写版本
                start = pos + len(replace_text)
        else:
            # 只替换第一个匹配项
            pos = text_lower.find(search_lower)
            if pos != -1:
                result = result[:pos] + replace_text + result[pos + len(search_text):]
                
        return result
        
    def on_checkbox_changed(self):
        """复选框状态变化时的处理"""
        # 防止递归调用
        if self.updating_preview:
            return
            
        # 更新全选复选框状态
        self.update_select_all_checkbox_state()
        # 无论是否有查找文本，都需要更新预览表格以反映复选框状态
        self.update_preview_table()
    
    def toggle_select_all(self, state):
        """全选/取消全选所有复选框"""
        # 防止递归调用
        if self.updating_preview:
            return
            
        is_checked = state == Qt.Checked
        for row in range(self.preview_table.rowCount()):
            checkbox = self.preview_table.cellWidget(row, 0)
            if checkbox:
                # 阻止信号，避免在设置状态时触发信号
                checkbox.blockSignals(True)
                checkbox.setChecked(is_checked)
                checkbox.blockSignals(False)
        
        # 全选/取消全选后，更新预览显示
        self.update_rename_column_display()
        # 更新标题统计
        self.update_title_counts()
    
    def update_select_all_checkbox_state(self):
        """更新全选复选框的状态"""
        if self.preview_table.rowCount() == 0:
            # 阻止信号，避免在设置状态时触发信号
            self.select_all_checkbox.blockSignals(True)
            self.select_all_checkbox.setChecked(False)
            self.select_all_checkbox.blockSignals(False)
            return
            
        checked_count = 0
        for row in range(self.preview_table.rowCount()):
            checkbox = self.preview_table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked():
                checked_count += 1
        
        # 阻止信号，避免在设置状态时触发信号
        self.select_all_checkbox.blockSignals(True)
        # 根据选中状态更新全选复选框
        if checked_count == 0:
            self.select_all_checkbox.setChecked(False)
        elif checked_count == self.preview_table.rowCount():
            self.select_all_checkbox.setChecked(True)
        else:
            # 部分选中状态，可以设置为三态复选框
            self.select_all_checkbox.setChecked(False)
        self.select_all_checkbox.blockSignals(False)
        
    def update_preview_table(self):
        """更新预览表格"""
        # 设置标志位，防止递归调用
        self.updating_preview = True
        
        try:
            # 保存当前复选框状态
            checkbox_states = {}
            for row in range(self.preview_table.rowCount()):
                checkbox = self.preview_table.cellWidget(row, 0)
                if checkbox:
                    checkbox_states[row] = checkbox.isChecked()
            
            self.preview_table.setRowCount(len(self.preview_data))
            
            for row, (folder, old_name, new_name) in enumerate(self.preview_data):
                # 第一列：复选框
                checkbox = QCheckBox()
                # 阻止信号，避免在设置状态时触发信号
                checkbox.blockSignals(True)
                # 恢复之前的选中状态，如果没有则默认选中
                checkbox.setChecked(checkbox_states.get(row, True))
                # 重新启用信号
                checkbox.blockSignals(False)
                # 连接复选框状态变化信号，实时更新预览
                checkbox.stateChanged.connect(self.on_checkbox_changed)
                self.preview_table.setCellWidget(row, 0, checkbox)
                
                # 第二列：原始文件名
                self.preview_table.setItem(row, 1, QTableWidgetItem(old_name))
                
                # 第三列：重命名后 - 根据复选框状态和修改情况显示
                # 注意：这里需要在复选框创建之后才能获取其状态
                # 所以先设置一个占位符，稍后更新
                self.preview_table.setItem(row, 2, QTableWidgetItem(""))
            
            # 更新全选复选框状态
            self.update_select_all_checkbox_state()
            
            # 更新"重命名后"列的显示
            self.update_rename_column_display()
            
            # 更新标题统计
            self.update_title_counts()
            
        finally:
            # 重置标志位
            self.updating_preview = False
    
    def update_rename_column_display(self):
        """更新"重命名后"列的显示，根据复选框状态和修改情况"""
        for row in range(self.preview_table.rowCount()):
            if row < len(self.preview_data):
                folder, old_name, new_name = self.preview_data[row]
                checkbox = self.preview_table.cellWidget(row, 0)
                
                if checkbox and checkbox.isChecked() and new_name != old_name:
                    # 只有被勾选且会被修改的文件才显示新名称
                    self.preview_table.setItem(row, 2, QTableWidgetItem(new_name))
                else:
                    # 未勾选或不会被修改的文件显示空
                    self.preview_table.setItem(row, 2, QTableWidgetItem(""))
    
    def update_title_counts(self):
        """更新标题统计信息"""
        total_files = len(self.file_list)
        # 计算被勾选且会被重命名的文件数量
        rename_files = 0
        for row in range(self.preview_table.rowCount()):
            checkbox = self.preview_table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked() and row < len(self.preview_data):
                folder, old_name, new_name = self.preview_data[row]
                if new_name != old_name:
                    rename_files += 1
        self.original_label.setText(f"原始 ({total_files})")
        self.renamed_label.setText(f"已重命名 ({rename_files})")
        
    def get_current_selected_files(self):
        """获取当前被勾选的文件路径列表"""
        selected_files = []
        for row in range(self.preview_table.rowCount()):
            checkbox = self.preview_table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked():
                if row < len(self.preview_data):
                    folder, old_name, new_name = self.preview_data[row]
                    file_path = os.path.join(folder, old_name)
                    selected_files.append(file_path)
        return selected_files

    def get_selected_files(self):
        """获取被勾选的文件列表"""
        selected_files = []
        for row in range(self.preview_table.rowCount()):
            checkbox = self.preview_table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked():
                if row < len(self.preview_data):
                    selected_files.append(self.preview_data[row])
        return selected_files

    def apply_rename(self):
        """应用重命名"""
        # 获取被勾选的文件
        selected_files = self.get_selected_files()
        if not selected_files:
            QMessageBox.information(self, "提示", "没有选中要重命名的文件")
            return
            
        try:
            success_count = 0
            failed_files = []
            actual_rename_count = 0
            
            print(f"开始重命名，共 {len(selected_files)} 个选中文件")
            
            for folder, old_name, new_name in selected_files:
                # 跳过文件名相同的文件（不需要重命名）
                if old_name == new_name:
                    print(f"跳过相同文件名: {old_name}")
                    continue
                    
                actual_rename_count += 1
                old_path = os.path.join(folder, old_name)
                new_path = os.path.join(folder, new_name)
                
                print(f"尝试重命名: {old_path} -> {new_path}")
                print(f"原文件存在: {os.path.exists(old_path)}")
                print(f"新文件存在: {os.path.exists(new_path)}")
                
                if os.path.exists(old_path):
                    if not os.path.exists(new_path):
                        try:
                            os.rename(old_path, new_path)
                            success_count += 1
                            print(f"重命名成功: {old_name} -> {new_name}")
                        except Exception as e:
                            print(f"重命名失败: {e}")
                            failed_files.append(f"{old_name}: {str(e)}")
                    else:
                        # 目标文件已存在，直接提示失败
                        print(f"目标文件已存在: {new_path}")
                        failed_files.append(f"{old_name}: 目标文件已存在")
                else:
                    print(f"原文件不存在: {old_path}")
                    failed_files.append(f"{old_name}: 原文件不存在")
                    
            # 显示重命名结果
            if failed_files:
                QMessageBox.warning(self, "重命名完成", f"选中 {len(selected_files)} 个文件\n实际需要重命名 {actual_rename_count} 个文件\n成功重命名 {success_count} 个文件\n失败 {len(failed_files)} 个文件")
            else:
                pass
            
            print(f"重命名完成: 选中 {len(selected_files)} 个，实际重命名 {actual_rename_count} 个，成功 {success_count} 个，失败 {len(failed_files)} 个")
                
            # 重命名完成后重新获取文件列表并显示
            self.refresh_file_list_after_rename()
            self.update_preview()  # 使用update_preview而不是show_original_files
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"重命名失败: {str(e)}")
            print(f"重命名异常: {e}")
            
    def update_file_list(self):
        """更新文件列表，只更新重命名后的文件路径"""
        # 不重新扫描整个目录，只更新已重命名的文件路径
        updated_files = []
        for file_path in self.file_list:
            if os.path.exists(file_path):
                updated_files.append(file_path)
            else:
                # 如果原文件不存在，可能是被重命名了，尝试找到新文件
                folder = os.path.dirname(file_path)
                original_name = os.path.basename(file_path)
                
                # 在同一个目录下查找可能的匹配文件
                if os.path.exists(folder):
                    for filename in os.listdir(folder):
                        full_path = os.path.join(folder, filename)
                        if os.path.isfile(full_path):
                            # 检查是否是重命名后的文件（通过时间戳等判断）
                            # 这里简化处理，直接添加找到的文件
                            updated_files.append(full_path)
        
        # 限制文件数量，避免扫描过多文件
        if len(updated_files) > 1000:
            updated_files = updated_files[:1000]
            
        self.file_list = updated_files
        
    def refresh_file_list_after_rename(self):
        """重命名后刷新文件列表"""
        # 重新扫描完整文件夹内容
        new_file_list = []
        
        # 从原始文件列表中获取所有目录
        folders = set()
        for file_path in self.file_list:
            folder = os.path.dirname(file_path)
            folders.add(folder)
        
        # 扫描每个目录中的所有文件
        for folder in folders:
            if os.path.exists(folder):
                for filename in os.listdir(folder):
                    full_path = os.path.join(folder, filename)
                    if os.path.isfile(full_path):
                        new_file_list.append(full_path)
        
        self.file_list = new_file_list
        print(f"重命名后刷新文件列表: {len(self.file_list)} 个文件")
        
    def closeEvent(self, event):
        """窗口关闭事件"""
        self.window_closed.emit()
        super().closeEvent(event)


class PreviewDialog(QDialog):
    def __init__(self, rename_data):
        super().__init__()
        self.setWindowTitle("重命名预览")
        icon_path = os.path.join(os.path.dirname(__file__), "icon", "rename.ico")
        self.setWindowIcon(QIcon(icon_path))

        self.resize(1200, 800)

        layout = QVBoxLayout()
        self.table = QTableWidget(self)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["文件夹", "旧文件名", "新文件名"])
        self.table.setRowCount(len(rename_data))

        for row, (folder, old_name, new_name) in enumerate(rename_data):
            self.table.setItem(row, 0, QTableWidgetItem(folder))
            self.table.setItem(row, 1, QTableWidgetItem(old_name))
            self.table.setItem(row, 2, QTableWidgetItem(new_name))

        # 设置表格列宽自适应
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)

        layout.addWidget(self.table)
        self.setLayout(layout)


class FileOrganizer(QWidget):
    imagesRenamed = pyqtSignal()  # 添加信号

    def __init__(self):
        super().__init__()

        self.settings = QSettings("MyApp", "FileOrganizer")
        self.tray_icon = None
        self.tray_menu = None
        self._balloon_shown = False
        self._hotkey_filter = None
        self.power_rename_window = None  # 添加PowerRename窗口实例管理
        self.initUI()

        # 设置图标路径
        icon_path = os.path.join(os.path.dirname(__file__), "icon", "rename.ico")
        self.setWindowIcon(QIcon(icon_path))

    def log(self, message):
        try:
            print(f"[FileOrganizer] {message}")
        except Exception:
            pass

    def _get_app_base_dir(self):
        """返回应用运行目录（支持打包为 exe 的情况）。"""
        candidates = []
        try:
            exe_path = getattr(sys, 'executable', '') or ''
            if exe_path and os.path.exists(exe_path):
                exe_dir = os.path.normcase(os.path.abspath(os.path.dirname(exe_path)))
                candidates.append(exe_dir)
                # 兼容 Nuitka/pyinstaller dist 目录
                candidates.append(os.path.normcase(os.path.abspath(os.path.dirname(exe_dir))))
        except Exception:
            pass
        try:
            file_dir = os.path.normcase(os.path.abspath(os.path.dirname(__file__)))
            candidates.append(file_dir)
            candidates.append(os.path.normcase(os.path.abspath(os.path.dirname(file_dir))))
        except Exception:
            pass
        try:
            cwd_dir = os.path.normcase(os.path.abspath(os.getcwd()))
            candidates.append(cwd_dir)
            candidates.append(os.path.normcase(os.path.abspath(os.path.dirname(cwd_dir))))
        except Exception:
            pass
        # 去重并返回集合字符串（用于匹配）
        uniq = []
        seen = set()
        for d in candidates:
            if d and d not in seen:
                seen.add(d)
                uniq.append(d)
        try:
            print(f"[_get_app_base_dir] candidates: {uniq}")
        except Exception:
            pass
        return uniq

    def initUI(self):
        # 设置窗口初始大小
        self.resize(1200, 800)

        # 主布局
        main_layout = QVBoxLayout()

        # 文件夹选择布局
        folder_layout = QHBoxLayout()

        # 左侧布局
        left_layout = QVBoxLayout()
        # self.folder_count_label = QLabel("文件夹数量: 0", self)
        
        # 使用QTreeView和QFileSystemModel实现文件预览
        self.left_tree = QTreeView(self)
        self.left_model = QFileSystemModel()
        self.left_model.setRootPath("")
        self.left_model.setFilter(QDir.Dirs | QDir.Files | QDir.NoDotAndDotDot)
        self.left_tree.setModel(self.left_model)
        self.left_tree.setSelectionMode(QTreeView.ExtendedSelection)
        self.left_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.left_tree.customContextMenuRequested.connect(self.open_context_menu)
        self.left_tree.setAlternatingRowColors(True)
        self.left_tree.setRootIsDecorated(True)
        
        # 只显示名称列，隐藏其他列
        self.left_tree.hideColumn(1)  # 大小
        self.left_tree.hideColumn(2)  # 类型
        self.left_tree.hideColumn(3)  # 修改日期
        
        # 隐藏列标题
        self.left_tree.header().hide()
        
        # 连接选择变化信号
        self.left_tree.selectionModel().selectionChanged.connect(self.on_left_tree_selection_changed)
        
        # left_layout.addWidget(self.folder_count_label)
        left_layout.addWidget(self.left_tree)

        # 右侧布局
        right_layout = QVBoxLayout()
        # self.file_count_label = QLabel("文件总数: 0", self)
        
        # 右侧使用QTreeView和QFileSystemModel来显示选中的文件
        self.right_tree = QTreeView(self)
        self.right_model = QFileSystemModel()
        self.right_model.setRootPath("")
        self.right_model.setFilter(QDir.Dirs | QDir.Files | QDir.NoDotAndDotDot)
        # 右侧使用过滤代理模型，以支持移除选中（隐藏选中项）
        self.right_proxy = ExcludeFilterProxyModel(self)
        self.right_proxy.setSourceModel(self.right_model)
        self.right_tree.setModel(self.right_proxy)
        # 用于显示空视图的临时目录
        self._empty_dir = None
        # 启动时设置为空目录，避免显示盘符
        try:
            import tempfile as _tmp
            self._empty_dir = _tmp.mkdtemp(prefix="rename_empty_")
            empty_index = self.right_proxy.mapFromSource(self.right_model.index(self._empty_dir))
            self.right_tree.setRootIndex(empty_index)
            try:
                print(f"[Startup] right_tree set to empty dir: {self._empty_dir}")
            except Exception:
                pass
        except Exception:
            self.right_tree.setRootIndex(QModelIndex())
        self.right_tree.setSelectionMode(QTreeView.ExtendedSelection)
        self.right_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        # self.right_tree.customContextMenuRequested.connect(self.open_context_menu_right)
        self.right_tree.setAlternatingRowColors(True)
        self.right_tree.setRootIsDecorated(True)
        
        # 只显示名称列，隐藏其他列
        self.right_tree.hideColumn(1)  # 大小
        self.right_tree.hideColumn(2)  # 类型
        self.right_tree.hideColumn(3)  # 修改日期
        
        # 隐藏列标题
        self.right_tree.header().hide()
        
        # right_layout.addWidget(self.file_count_label)
        right_layout.addWidget(self.right_tree)

        # 右侧下方布局（已不再直接显示在右侧，而是移到状态栏）
        right_bottom_layout = QHBoxLayout()

        # 输入框
        self.line_edit = QComboBox(self)
        self.line_edit.setEditable(True)  # 设置 QComboBox 为可编辑状态
        self.line_edit.addItem("$p_*")
        self.line_edit.addItem("$$p_*")
        self.line_edit.addItem("#_*")
        self.line_edit.setMinimumWidth(150)  # 设置宽度

        # self.replace_line_edit = QComboBox(self)
        # self.replace_line_edit.setEditable(True)  # 设置 QComboBox 为可编辑状态
        # # 设置输入框提示文本
        # self.replace_line_edit.lineEdit().setPlaceholderText("请输入替换内容")

        # # 默认隐藏
        # self.replace_line_edit.setVisible(False)
        # self.replace_line_edit.setFixedWidth(self.replace_line_edit.width())  # 设置宽度

        # 开始按钮
        self.start_button = QPushButton("开始", self)
        self.start_button.clicked.connect(self.rename_files)
        # 预览按钮
        self.preview_button = QPushButton("预览", self)
        self.preview_button.clicked.connect(self.preview_rename)

        # 新增帮助按钮
        self.help_button = QPushButton("帮助", self)
        self.help_button.clicked.connect(self.show_help)
        
        # 新增PowerRename按钮
        self.power_rename_button = QPushButton("PowerRename", self)
        self.power_rename_button.clicked.connect(self.open_power_rename)

        # 这些控件将被添加到状态栏右侧
        right_bottom_layout.addWidget(self.line_edit)
        # right_bottom_layout.addWidget(self.replace_line_edit)
        right_bottom_layout.addWidget(self.start_button)
        right_bottom_layout.addWidget(self.preview_button)
        right_bottom_layout.addWidget(self.power_rename_button)
        right_bottom_layout.addWidget(self.help_button)

        # 移除文件类型复选框（jpg/txt/xml），不再做扩展名筛选

        # 不再将底部布局添加到右侧布局，改为使用状态栏承载

        # 中间按钮组件布局
        middle_button_layout = QVBoxLayout()
        self.add_button = QPushButton("增加", self)
        self.add_button.clicked.connect(self.add_to_right)
        # self.add_all_button = QPushButton("增加全部", self)
        # self.add_all_button.clicked.connect(self.add_all_to_right)
        self.remove_button = QPushButton("移除", self)
        self.remove_button.clicked.connect(self.remove_from_right)

        # # 新增"移除全部"按钮
        # self.remove_all_button = QPushButton("移除全部", self)
        # self.remove_all_button.clicked.connect(self.remove_all_from_right)

        middle_button_layout.addWidget(self.add_button)
        # middle_button_layout.addWidget(self.add_all_button)
        middle_button_layout.addWidget(self.remove_button)
        # middle_button_layout.addWidget(self.remove_all_button)  # 添加"移除全部"按钮

        # 将左侧(含中间按钮)与右侧分别打包为两个容器，使用分隔条可调整大小
        left_container = QFrame()
        left_container.setFrameStyle(QFrame.NoFrame)
        left_container_layout = QHBoxLayout()
        left_container_layout.setContentsMargins(0, 0, 0, 0)
        left_container_layout.setSpacing(0)
        left_container_layout.addLayout(left_layout)
        left_container_layout.addLayout(middle_button_layout)
        left_container.setLayout(left_container_layout)

        right_container = QFrame()
        right_container.setFrameStyle(QFrame.NoFrame)
        right_container_layout = QVBoxLayout()
        right_container_layout.setContentsMargins(0, 0, 0, 0)
        right_container_layout.setSpacing(0)
        right_container_layout.addLayout(right_layout)
        right_container.setLayout(right_container_layout)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_container)
        splitter.addWidget(right_container)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)
        # 设置伸缩因子为 1:1
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        # 按当前窗口宽度初始化尺寸为 1:1
        try:
            total_w = max(self.width(), 1)
            left_w = int(total_w * 1 / 2)
            right_w = max(total_w - left_w, 1)
            splitter.setSizes([left_w, right_w])
        except Exception:
            splitter.setSizes([400, 600])

        # 整个界面主体布局设置，添加文件夹选择布局、列表布局，上下分布
        main_layout.addLayout(folder_layout)
        main_layout.addWidget(splitter)

        # 添加状态栏并将控件右对齐显示
        self.status_bar = QStatusBar(self)
        self.status_bar.setSizeGripEnabled(False)
        # 固定状态栏高度
        self.status_bar.setFixedHeight(40)
        # 将控件作为永久部件添加（自动靠右对齐）
        self.status_bar.addPermanentWidget(self.line_edit)
        # self.status_bar.addPermanentWidget(self.replace_line_edit)
        self.status_bar.addPermanentWidget(self.start_button)
        self.status_bar.addPermanentWidget(self.preview_button)
        self.status_bar.addPermanentWidget(self.power_rename_button)
        self.status_bar.addPermanentWidget(self.help_button)
        main_layout.addWidget(self.status_bar)

        self.setLayout(main_layout)
        self.setWindowTitle("重命名")

        # 是否在启动时恢复上次文件夹（默认不恢复，避免固定打开某目录）
        self.restore_on_startup = bool(self.settings.value("restoreOnStartup", False, type=bool))
        if self.restore_on_startup:
            last_folder = self.settings.value("lastFolder", "")
            self.log(f"startup restore enabled, lastFolder='{last_folder}'")
            if last_folder:
                self.set_folder_path(last_folder)
        else:
            self.log("startup restore disabled; no folder auto-opened")

        # 添加ESC键退出快捷键
        self.shortcut_esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.shortcut_esc.activated.connect(self.close)

        # 添加 Ctrl+M：优先使用资源管理器选中路径传入 PowerRename
        self.shortcut_powerrename = QShortcut(QKeySequence("Ctrl+M"), self)
        try:
            self.shortcut_powerrename.setContext(Qt.ApplicationShortcut)
        except Exception:
            pass
        def _hotkey_trigger():
            try:
                # 仅弹出 PowerRename，不激活主窗口
                self.open_power_rename_from_explorer_or_fallback()
            except Exception as e:
                print(f"Ctrl+M trigger error: {e}")
        self.shortcut_powerrename.activated.connect(_hotkey_trigger)
        
        # 添加 Ctrl+N：优先使用资源管理器选中路径传入主窗口
        self.shortcut_main_window = QShortcut(QKeySequence("Ctrl+N"), self)
        try:
            self.shortcut_main_window.setContext(Qt.ApplicationShortcut)
        except Exception:
            pass
        def _hotkey_main_trigger():
            try:
                # 将路径传给主窗口并打开主窗口
                self.open_main_window_from_explorer_or_fallback()
            except Exception as e:
                print(f"Ctrl+N trigger error: {e}")
        self.shortcut_main_window.activated.connect(_hotkey_main_trigger)
        # self.show()
        # 初始化系统托盘
        self.setup_tray_icon()
        # 全局热键（Ctrl+M）
        self.setup_global_hotkey()
        # 启动时默认驻留托盘，不显示主窗口，避免闪烁
        try:
            self.hide()
        except Exception:
            pass
        # 启动时仅驻托盘，不显示主窗口
        self.hide()

    def format_file_size(self, size_bytes):
        """格式化文件大小"""
        if size_bytes == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        return f"{size_bytes:.1f} {size_names[i]}"

    def format_time(self, timestamp):
        """格式化时间戳"""
        import time
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


    def add_to_right(self):
        """将左侧当前选中内容加入右侧。
        规则：
        - 若选中多个条目：
          - 若包含文件，右侧根设为这些文件的共同父目录；
          - 若全是文件夹，若只有一个则设为该文件夹；多个则设为这些文件夹的共同父目录；
        - 若仅选中一个文件夹，则右侧根=该文件夹。
        """
        selected = [idx for idx in self.left_tree.selectedIndexes() if idx.column() == 0]
        if not selected:
            return
        # 转为真实路径
        paths = [self.left_model.filePath(idx) for idx in selected]
        # 如果有文件，使用其父目录
        normalized_dirs = []
        for p in paths:
            if os.path.isfile(p):
                normalized_dirs.append(os.path.dirname(p))
            else:
                normalized_dirs.append(p)
        # 计算共同父目录
        def common_parent(dir_list):
            parts = [os.path.abspath(d).split(os.sep) for d in dir_list if os.path.isdir(d)]
            if not parts:
                return None
            min_len = min(len(x) for x in parts)
            prefix = []
            for i in range(min_len):
                token = parts[0][i]
                if all(x[i] == token for x in parts):
                    prefix.append(token)
                else:
                    break
            return os.sep.join(prefix) if prefix else os.path.dirname(os.path.abspath(dir_list[0]))
        target_dir = None
        unique_dirs = list(dict.fromkeys(normalized_dirs))
        if len(unique_dirs) == 1:
            target_dir = unique_dirs[0]
        else:
            target_dir = common_parent(unique_dirs)
        if target_dir and os.path.isdir(target_dir):
            # 清空之前的过滤状态并准备新的过滤
            self._right_excluded_paths = []
            self.right_proxy.clear_excluded()
            self.right_proxy.set_hide_all(False)
            # 根据选择内容设置白名单：
            # - 若选择了文件：仅显示这些文件（及其祖先目录）
            # - 否则若选择了文件夹：仅显示这些文件夹及其所有子项
            selected_files = []
            selected_dirs = []
            for p in paths:
                if os.path.isfile(p):
                    selected_files.append(p)
                elif os.path.isdir(p):
                    selected_dirs.append(p)
            if selected_files:
                self.right_proxy.set_included(set(selected_files))
            elif selected_dirs:
                self.right_proxy.set_included(set(selected_dirs))
            else:
                self.right_proxy.clear_included()
            # 最后再设置右侧根到共同父目录（确保过滤状态已生效）
            self.right_tree.setRootIndex(self.right_proxy.mapFromSource(self.right_model.index(target_dir)))
            # 取消空目录根
            self._empty_dir = None
            # 强制刷新与计数
            self.right_proxy.invalidate()
            # self.update_file_count()


    def remove_from_right(self):
        # 只移除右侧选中的条目（通过过滤器隐藏选中的路径）
        selected_indexes = self.right_tree.selectionModel().selectedIndexes()
        if not selected_indexes:
            return
        # 收集选中项对应的源模型路径
        excluded = list(getattr(self, "_right_excluded_paths", []))
        removed_files = []
        for proxy_index in selected_indexes:
            if proxy_index.column() != 0:
                continue
            source_index = self.right_proxy.mapToSource(proxy_index)
            if not source_index.isValid():
                continue
            file_path = self.right_model.filePath(source_index)
            if file_path:
                excluded.append(file_path)
                removed_files.append(file_path)
        # 去重并设置过滤
        self._right_excluded_paths = [os.path.normcase(os.path.normpath(p)) for p in dict.fromkeys(excluded)]
        self.right_proxy.set_excluded(self._right_excluded_paths)
        # 若当前处于白名单模式（白名单非空），同步从白名单删除被移除的文件
        if hasattr(self, 'right_proxy') and getattr(self.right_proxy, 'included_paths', None):
            if len(self.right_proxy.included_paths) > 0:
                self.right_proxy.remove_from_included(removed_files)
                # 如果白名单被清空，则右侧显示为空目录（避免回退到整个文件夹视图）
                if len(self.right_proxy.included_paths) == 0:
                    try:
                        if not self._empty_dir or not os.path.exists(self._empty_dir):
                            self._empty_dir = tempfile.mkdtemp(prefix="rename_empty_")
                        empty_index = self.right_proxy.mapFromSource(self.right_model.index(self._empty_dir))
                        self.right_tree.setRootIndex(empty_index)
                    except Exception:
                        self.right_tree.setRootIndex(QModelIndex())
        # 同步更新计数
        # self.update_file_count()

    def remove_all_from_right(self):
        # 清空右侧视图（重置过滤并置空根索引）
        self._right_excluded_paths = []
        if hasattr(self, 'right_proxy'):
            self.right_proxy.clear_excluded()
            self.right_proxy.clear_included()
            # 直接隐藏全部内容，避免显示驱动器列表
            self.right_proxy.set_hide_all(False)
        # 将右侧根设置为一个临时空目录，确保界面为空
        try:
            if not self._empty_dir or not os.path.exists(self._empty_dir):
                self._empty_dir = tempfile.mkdtemp(prefix="rename_empty_")
            empty_index = self.right_proxy.mapFromSource(self.right_model.index(self._empty_dir))
            self.right_tree.setRootIndex(empty_index)
        except Exception:
            # 兜底：设置无效索引
            self.right_tree.setRootIndex(QModelIndex())
        # self.update_file_count()

    # def update_file_count(self):
    #     """统计右侧当前可见（未被过滤）的文件数量"""
    #     file_count = 0
    #     root_proxy_index = self.right_tree.rootIndex()
    #     if root_proxy_index.isValid():
    #         file_count = self.count_visible_files(root_proxy_index)
    #     self.file_count_label.setText(f"文件总数: {file_count}")

    def count_visible_files(self, dir_proxy_index):
        """递归统计代理模型下可见文件数量（包含子目录）。"""
        count = 0
        rows = self.right_proxy.rowCount(dir_proxy_index)
        for i in range(rows):
            child_proxy = self.right_proxy.index(i, 0, dir_proxy_index)
            source_idx = self.right_proxy.mapToSource(child_proxy)
            if self.right_model.isDir(source_idx):
                count += self.count_visible_files(child_proxy)
            else:
                count += 1
        return count

    def rename_files_recursive(self, parent_index, prefix, replace_text, hash_count):
        """递归重命名文件"""
        for i in range(self.right_model.rowCount(parent_index)):
            child_index = self.right_model.index(i, 0, parent_index)
            file_path = self.right_model.filePath(child_index)
            
            if self.right_model.isDir(child_index):
                # 如果是文件夹，递归处理
                self.rename_files_recursive(child_index, prefix, replace_text, hash_count)
            else:
                # 如果是文件，进行重命名
                original_name = os.path.basename(file_path)
                folder_path = os.path.dirname(file_path)
                parent_folder_name = os.path.basename(os.path.dirname(folder_path))
                
                if self.should_rename_file(original_name):
                    new_name = self.generate_new_name(
                        original_name,
                        prefix,
                        replace_text,
                        parent_folder_name,
                        os.path.basename(folder_path),
                        i,
                        hash_count,
                    )
                    new_path = os.path.join(folder_path, new_name)
                    self.perform_rename(file_path, new_path)

    def preview_rename_recursive(self, parent_index, prefix, replace_text, hash_count, rename_data):
        """递归预览重命名"""
        for i in range(self.right_model.rowCount(parent_index)):
            child_index = self.right_model.index(i, 0, parent_index)
            file_path = self.right_model.filePath(child_index)
            
            if self.right_model.isDir(child_index):
                # 如果是文件夹，递归处理
                self.preview_rename_recursive(child_index, prefix, replace_text, hash_count, rename_data)
            else:
                # 如果是文件，添加到预览数据
                original_name = os.path.basename(file_path)
                folder_path = os.path.dirname(file_path)
                parent_folder_name = os.path.basename(os.path.dirname(folder_path))
                
                if self.should_rename_file(original_name):
                    new_name = self.generate_new_name(
                        original_name,
                        prefix,
                        replace_text,
                        parent_folder_name,
                        os.path.basename(folder_path),
                        i,
                        hash_count,
                    )
                    rename_data.append((folder_path, original_name, new_name))

    def rename_files(self):
        prefix = self.line_edit.currentText()
        replace_text = (
            # self.replace_line_edit.currentText()
            # if self.replace_checkbox.isChecked()
            # else None
        )
        hash_count = prefix.count("#")
        try:
            root_index = self.right_tree.rootIndex()
            if not root_index.isValid():
                QMessageBox.information(self, "提示", "右侧没有可重命名的文件")
                return
            # 基于代理模型获取当前可见文件
            visible_files = self.get_visible_files()
            if not visible_files:
                QMessageBox.information(self, "提示", "右侧没有可重命名的文件")
                return
            # 用可见文件列表进行重命名
            # 将右侧根作为范围，但实际操作基于visible_files路径
            # 逐个文件应用新名称
            # 将可见文件按照其父目录分组，组内从0开始编号
            from collections import defaultdict
            folder_to_files = defaultdict(list)
            for fp in visible_files:
                folder_to_files[os.path.dirname(fp)].append(fp)
            for folder_path, files in folder_to_files.items():
                files.sort(key=self._natural_sort_key)
                index_counter = 0
                for file_path in files:
                    original_name = os.path.basename(file_path)
                    parent_folder_name = self.get_actual_cased_basename(os.path.dirname(folder_path))
                    if self.should_rename_file(original_name):
                        new_name = self.generate_new_name(
                            original_name,
                            prefix,
                            replace_text,
                            parent_folder_name,
                            self.get_actual_cased_basename(folder_path),
                            index_counter,
                            hash_count,
                        )
                        index_counter += 1
                        new_path = os.path.join(folder_path, new_name)
                        self.perform_rename(file_path, new_path)

            # 重命名完成信息提示框
            QMessageBox.information(self, "提示", "重命名完成")
            self.imagesRenamed.emit()  # 发送信号，通知 aebox 刷新图片列表
        except Exception as e:
            # 重命名失败信息提示框
            QMessageBox.information(self, "提示", "重命名失败,请检查报错信息")
            print(f"Error renaming files: {e}")
        finally:
            pass

    def generate_new_name(
        self,
        original_name,
        prefix,
        replace_text,
        parent_folder_name,
        folder_name,
        index,
        hash_count,
    ):
        if not prefix:
            new_name = original_name
        else:
            if hash_count > 0:
                number_format = f"{{:0{hash_count}d}}"
                new_name = prefix.replace("#" * hash_count, number_format.format(index))
            else:
                new_name = prefix

            new_name = new_name.replace("$$p", f"{parent_folder_name}_{folder_name}")
            new_name = new_name.replace("$p", folder_name)

            file_extension = os.path.splitext(original_name)[1]

            if "*" in prefix:
                new_name += original_name
            else:
                new_name += file_extension

            new_name = new_name.replace("*", "")

            if replace_text:
                new_name = original_name.replace(prefix, replace_text)

        return new_name

    def perform_rename(self, original_path, new_path):
        print(f"Trying to rename: {original_path} to {new_path}")
        if not os.path.exists(original_path):
            print(f"File does not exist: {original_path}")
            return

        try:
            os.rename(original_path, new_path)
            print(
                f"Renamed {os.path.basename(original_path)} to {os.path.basename(new_path)}"
            )
        except Exception as e:
            print(f"Error renaming {os.path.basename(original_path)}: {e}")


    def _natural_sort_key(self, path_or_name):
        """返回用于自然排序的键，使 '1' < '2' < '10'。

        仅对末级文件名进行分段；非数字段使用小写比较以稳定排序。
        """
        try:
            name = os.path.basename(path_or_name)
        except Exception:
            name = str(path_or_name)
        try:
            parts = re.split(r"(\d+)", name)
            return [int(p) if p.isdigit() else p.lower() for p in parts]
        except Exception:
            return [name.lower()]

    def preview_rename(self):
        rename_data = []
        prefix = self.line_edit.currentText()
        replace_text = (
            # self.replace_line_edit.currentText()
            # if self.replace_checkbox.isChecked()
            # else None
        )

        hash_count = prefix.count("#")

        # 基于代理模型的可见文件进行分组预览（支持不同父目录下的多个子目录）
        from collections import defaultdict
        visible_files = self.get_visible_files()
        folder_to_files = defaultdict(list)
        for fp in visible_files:
            folder_to_files[os.path.dirname(fp)].append(fp)
        for folder_path, files in folder_to_files.items():
            files.sort(key=self._natural_sort_key)
            local_idx = 0
            for file_path in files:
                original_name = os.path.basename(file_path)
                parent_folder_name = self.get_actual_cased_basename(os.path.dirname(folder_path))
                if self.should_rename_file(original_name):
                    new_name = self.generate_new_name(
                        original_name,
                        prefix,
                        replace_text,
                        parent_folder_name,
                        self.get_actual_cased_basename(folder_path),
                        local_idx,
                        hash_count,
                    )
                    rename_data.append((folder_path, original_name, new_name))
                    local_idx += 1

        if rename_data:
            dialog = PreviewDialog(rename_data)
            dialog.exec_()
        else:
            print("没有可预览的重命名数据")

    def should_rename_file(self, filename):
        # 不再根据扩展名筛选，全部参与重命名
        return True

    def open_power_rename(self):
        """打开PowerRename窗口"""
        # 获取右侧可见的文件列表
        visible_files = self.get_visible_files()
        
        if not visible_files:
            QMessageBox.information(self, "提示", "右侧没有可重命名的文件")
            return
        
        # 检查是否已经存在PowerRename窗口
        if self.power_rename_window is not None and not self.power_rename_window.isHidden():
            # 如果窗口已存在且可见，只更新文件列表
            self.power_rename_window.file_list = visible_files
            self.power_rename_window.show_original_files()
            self.power_rename_window.raise_()
            self.power_rename_window.activateWindow()
            return
            
        # 打开PowerRename窗口
        # 以无父窗口显示，避免带出主窗口
        self.power_rename_window = PowerRenameDialog(visible_files, None)
        self.power_rename_window.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.power_rename_window.show()
        
        # 连接窗口关闭信号
        self.power_rename_window.window_closed.connect(self.on_power_rename_closed)

    def _collect_files_recursive(self, paths):
        files = []
        for p in paths:
            if os.path.isfile(p):
                files.append(p)
            elif os.path.isdir(p):
                for dirpath, dirnames, filenames in os.walk(p):
                    for name in filenames:
                        fp = os.path.join(dirpath, name)
                        if os.path.isfile(fp):
                            files.append(fp)
        return files

    def _get_explorer_selected_paths(self):
        """使用 oleacc(MSAA) 为主方案获取资源管理器选中项；失败回退 COM。"""
        if os.name != 'nt' or ctypes is None:
            return []

        def _get_active_explorer_root_hwnd():
            user32 = ctypes.windll.user32
            GetAncestor = user32.GetAncestor
            GetAncestor.restype = wintypes.HWND
            GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            GA_ROOT = 2
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return 0
            return GetAncestor(hwnd, GA_ROOT) or hwnd

        def _find_syslistview32(hwnd_root):
            user32 = ctypes.windll.user32
            FindWindowExW = user32.FindWindowExW
            FindWindowExW.restype = wintypes.HWND
            FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]

            def _find_defview(start):
                # 常见层级：ShellTabWindowClass -> SHELLDLL_DefView -> SysListView32
                shelltab = FindWindowExW(start, 0, "ShellTabWindowClass", None)
                if shelltab:
                    defview = FindWindowExW(shelltab, 0, "SHELLDLL_DefView", None)
                    if defview:
                        return defview
                defview = FindWindowExW(start, 0, "SHELLDLL_DefView", None)
                if defview:
                    return defview
                # 广度搜索一层子窗体
                child = FindWindowExW(start, 0, None, None)
                while child:
                    shelltab = FindWindowExW(child, 0, "ShellTabWindowClass", None)
                    if shelltab:
                        defview = FindWindowExW(shelltab, 0, "SHELLDLL_DefView", None)
                        if defview:
                            return defview
                    defview = FindWindowExW(child, 0, "SHELLDLL_DefView", None)
                    if defview:
                        return defview
                    child = FindWindowExW(start, child, None, None)
                return 0

            defview = _find_defview(hwnd_root)
            if not defview:
                return 0
            listview = FindWindowExW(defview, 0, "SysListView32", None)
            return listview or 0

        def _enum_selected_names_from_listview(listview_hwnd):
            user32 = ctypes.windll.user32
            LVM_FIRST = 0x1000
            LVM_GETNEXTITEM = LVM_FIRST + 12
            LVM_GETITEMTEXTW = LVM_FIRST + 115
            LVNI_SELECTED = 0x0002

            class LVITEMW(ctypes.Structure):
                _fields_ = [
                    ("mask", wintypes.UINT),
                    ("iItem", wintypes.INT),
                    ("iSubItem", wintypes.INT),
                    ("state", wintypes.UINT),
                    ("stateMask", wintypes.UINT),
                    ("pszText", wintypes.LPWSTR),
                    ("cchTextMax", wintypes.INT),
                    ("iImage", wintypes.INT),
                    ("lParam", wintypes.LPARAM),
                    ("iIndent", wintypes.INT),
                    ("iGroupId", wintypes.INT),
                    ("cColumns", wintypes.UINT),
                    ("puColumns", ctypes.POINTER(wintypes.UINT)),
                    ("piColFmt", ctypes.POINTER(wintypes.INT)),
                    ("iGroup", wintypes.INT),
                ]

            SendMessageW = user32.SendMessageW
            SendMessageW.restype = wintypes.LRESULT
            SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

            names = []
            idx = -1
            while True:
                idx = SendMessageW(listview_hwnd, LVM_GETNEXTITEM, idx, LVNI_SELECTED)
                if idx == -1 or idx > 100000:
                    break
                buf = ctypes.create_unicode_buffer(1024)
                lvitem = LVITEMW()
                lvitem.iSubItem = 0
                lvitem.cchTextMax = 1024
                lvitem.pszText = ctypes.cast(buf, wintypes.LPWSTR)
                SendMessageW(listview_hwnd, LVM_GETITEMTEXTW, idx, ctypes.byref(lvitem))
                text = buf.value.strip()
                if text:
                    names.append(text)
            return names

        try:
            hwnd_root = _get_active_explorer_root_hwnd()
            if hwnd_root:
                listview = _find_syslistview32(hwnd_root)
                if listview:
                    names = _enum_selected_names_from_listview(listview)
                    if names:
                        # 用 COM 仅获取当前文件夹路径（不读取选中项），保持 oleacc 为主
                        folder_path = None
                        try:
                            if win32com is not None:
                                pythoncom.CoInitialize()
                                shell = win32com.client.Dispatch("Shell.Application")
                                windows = shell.Windows()
                                for w in windows:
                                    try:
                                        fullname = str(getattr(w, 'FullName', '')).lower()
                                        if not fullname.endswith('explorer.exe'):
                                            continue
                                        if int(getattr(w, 'HWND', 0)) == int(hwnd_root):
                                            doc = getattr(w, 'Document', None)
                                            if doc and getattr(doc, 'Folder', None) and getattr(doc.Folder, 'Self', None):
                                                folder_path = str(doc.Folder.Self.Path)
                                            break
                                    except Exception:
                                        continue
                        except Exception:
                            folder_path = None

                        # 如果没拿到，直接返回名字列表（由上层自行处理）；否则拼接为完整路径
                        if folder_path and os.path.isdir(folder_path):
                            full_paths = []
                            for nm in names:
                                p = os.path.join(folder_path, nm)
                                # 可能包含文件夹与文件，均保留
                                if os.path.exists(p):
                                    full_paths.append(p)
                                else:
                                    # 某些视图显示的名称可能是实际大小写不同，尝试不区分大小写匹配一次
                                    try:
                                        for entry in os.listdir(folder_path):
                                            if entry.lower() == nm.lower():
                                                q = os.path.join(folder_path, entry)
                                                if os.path.exists(q):
                                                    full_paths.append(q)
                                                    break
                                    except Exception:
                                        pass
                            # 过滤自身程序目录
                            app_base_dirs = self._get_app_base_dir()
                            normed = [os.path.normcase(os.path.abspath(x)) for x in full_paths]
                            def _is_under_any_app_dir(p):
                                for base in (app_base_dirs or []):
                                    try:
                                        if p == base or p.startswith(base + os.sep):
                                            return True
                                    except Exception:
                                        continue
                                if p.endswith('.dist') or p.endswith('.onefile-temp'):
                                    return True
                                return False
                            filtered = [x for x in normed if not _is_under_any_app_dir(x)]
                            # 将原值映射回去
                            out = []
                            for x in full_paths:
                                try:
                                    n = os.path.normcase(os.path.abspath(x))
                                except Exception:
                                    n = x
                                if n in filtered:
                                    out.append(x)
                            if out:
                                try:
                                    print(f"[_get_explorer_selected_paths][oleacc] hwnd={hwnd_root}, items={len(out)}")
                                except Exception:
                                    pass
                                return out
                        else:
                            # 仅返回名称，供上层回退逻辑处理
                            try:
                                print("[_get_explorer_selected_paths][oleacc] got names but no folder path")
                            except Exception:
                                pass
        except Exception as e:
            try:
                print(f"[_get_explorer_selected_paths][oleacc] error: {e}")
            except Exception:
                pass

        # 回退：COM 直接取 SelectedItems（原实现）
        if win32com is None:
            return []
        try:
            pythoncom.CoInitialize()
            shell = win32com.client.Dispatch("Shell.Application")
            windows = shell.Windows()
            user32 = ctypes.windll.user32
            active_hwnd = user32.GetForegroundWindow()
            candidates = []
            for w in windows:
                try:
                    fullname = str(getattr(w, 'FullName', '')).lower()
                    if not fullname.endswith('explorer.exe'):
                        continue
                    hwnd = int(getattr(w, 'HWND', 0))
                    candidates.append((0 if hwnd == active_hwnd else 1, hwnd, w))
                except Exception:
                    continue
            candidates.sort(key=lambda t: t[0])
            app_base_dirs = self._get_app_base_dir()
            for _, hwnd, w in candidates:
                try:
                    doc = getattr(w, 'Document', None)
                    if not doc:
                        continue
                    sel = getattr(doc, 'SelectedItems', None)
                    if not sel:
                        continue
                    selected = sel()
                    paths = []
                    for it in selected:
                        p = getattr(it, 'Path', None)
                        if isinstance(p, str) and os.path.exists(p):
                            paths.append(p)
                    if paths:
                        normed = [os.path.normcase(os.path.abspath(x)) for x in paths]
                        def _is_under_any_app_dir(p):
                            for base in (app_base_dirs or []):
                                try:
                                    if p == base or p.startswith(base + os.sep):
                                        return True
                                except Exception:
                                    continue
                            if p.endswith('.dist') or p.endswith('.onefile-temp'):
                                return True
                            return False
                        filtered = [p for p in normed if not _is_under_any_app_dir(p)]
                        # 映射回原值
                        out = []
                        for x in paths:
                            try:
                                n = os.path.normcase(os.path.abspath(x))
                            except Exception:
                                n = x
                            if n in filtered:
                                out.append(x)
                        if out:
                            try:
                                print(f"[_get_explorer_selected_paths][COM] hwnd={hwnd}, items={len(out)}")
                            except Exception:
                                pass
                            return out
                except Exception:
                    continue
        except Exception:
            return []
        return []

    def open_power_rename_from_explorer_or_fallback(self):
        """优先使用资源管理器选中项；否则回退左侧选择；再否则用右侧可见文件。"""
        try:
            paths = self._get_explorer_selected_paths()
            files = []
            if paths:
                try:
                    print(f"[Ctrl+M] explorer selected paths: {len(paths)}")
                except Exception:
                    pass
                files = self._collect_files_recursive(paths)
                # 同步把资源管理器选择应用到主程序右侧视图
                self._apply_paths_to_right(paths)
                # 同步定位左侧文件树到传入的文件夹
                self._sync_left_tree_to_paths(paths)
            if not files:
                # 回退：左侧选择
                selected = [idx for idx in self.left_tree.selectedIndexes() if idx.column() == 0]
                if selected:
                    left_paths = [self.left_model.filePath(idx) for idx in selected]
                    try:
                        print(f"[Ctrl+M] fallback left selection count: {len(left_paths)}")
                    except Exception:
                        pass
                    files = self._collect_files_recursive(left_paths)
                    self._apply_paths_to_right(left_paths)
                    # 同步定位左侧文件树到传入的文件夹
                    self._sync_left_tree_to_paths(left_paths)
            if not files:
                # 再回退：右侧可见
                files = self.get_visible_files()
                try:
                    print(f"[Ctrl+M] fallback visible files count: {len(files)}")
                except Exception:
                    pass
            if not files:
                QMessageBox.information(self, "提示", "没有可重命名的文件")
                return
            files = sorted(list(dict.fromkeys(files)), key=self._natural_sort_key)
            try:
                print(f"[Ctrl+M] final files count opened in PowerRename: {len(files)}")
            except Exception:
                pass
            
            # 检查是否已经存在PowerRename窗口
            if self.power_rename_window is not None and not self.power_rename_window.isHidden():
                # 如果窗口已存在且可见，只更新文件列表
                self.power_rename_window.file_list = files
                self.power_rename_window.show_original_files()
                self.power_rename_window.raise_()
                self.power_rename_window.activateWindow()
                return
            
            # 创建新的PowerRename窗口
            self.power_rename_window = PowerRenameDialog(files, None)
            self.power_rename_window.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
            self.power_rename_window.show()
            self.power_rename_window.window_closed.connect(self.on_power_rename_closed)
        except Exception as e:
            print(f"open_power_rename_from_explorer_or_fallback error: {e}")

    def open_main_window_from_explorer_or_fallback(self):
        """优先使用资源管理器选中项；否则回退左侧选择；再否则用右侧可见文件。将路径传给主窗口并打开主窗口。"""
        try:
            paths = self._get_explorer_selected_paths()
            if not paths:
                # 回退：左侧选择
                selected = [idx for idx in self.left_tree.selectedIndexes() if idx.column() == 0]
                if selected:
                    paths = [self.left_model.filePath(idx) for idx in selected]
                else:
                    # 再回退：右侧可见
                    visible_files = self.get_visible_files()
                    if visible_files:
                        # 从可见文件获取路径
                        paths = []
                        for file_path in visible_files:
                            parent_dir = os.path.dirname(file_path)
                            if parent_dir not in paths:
                                paths.append(parent_dir)
            
            if not paths:
                QMessageBox.information(self, "提示", "没有可传入的路径")
                return
                
            try:
                print(f"[Ctrl+N] 传入路径: {len(paths)} 个")
            except Exception:
                pass
            
            # 将路径应用到右侧视图
            self._apply_paths_to_right(paths)
            # 同步定位左侧文件树到传入的文件夹
            self._sync_left_tree_to_paths(paths)
            
            # 显示并激活主窗口
            self.show()
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
            self.raise_()
            self.activateWindow()
            
        except Exception as e:
            print(f"open_main_window_from_explorer_or_fallback error: {e}")

    def open_power_rename_from_left_selection(self):
        """将左侧选中的路径直接展开为文件列表并打开 PowerRename"""
        try:
            selected = [idx for idx in self.left_tree.selectedIndexes() if idx.column() == 0]
            if not selected:
                QMessageBox.information(self, "提示", "请在左侧选择文件或文件夹")
                return
            paths = [self.left_model.filePath(idx) for idx in selected]
            files = []
            for p in paths:
                if os.path.isfile(p):
                    files.append(p)
                elif os.path.isdir(p):
                    for dirpath, dirnames, filenames in os.walk(p):
                        for name in filenames:
                            fp = os.path.join(dirpath, name)
                            if os.path.isfile(fp):
                                files.append(fp)
            if not files:
                QMessageBox.information(self, "提示", "所选路径下没有可重命名的文件")
                return
            # 去重并自然排序
            files = sorted(list(dict.fromkeys(files)), key=self._natural_sort_key)
            
            # 检查是否已经存在PowerRename窗口
            if self.power_rename_window is not None and not self.power_rename_window.isHidden():
                # 如果窗口已存在且可见，只更新文件列表
                self.power_rename_window.file_list = files
                self.power_rename_window.show_original_files()
                self.power_rename_window.raise_()
                self.power_rename_window.activateWindow()
                return
            
            self.power_rename_window = PowerRenameDialog(files, self)
            self.power_rename_window.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
            self.power_rename_window.show()
            self.power_rename_window.window_closed.connect(self.on_power_rename_closed)
        except Exception as e:
            print(f"open_power_rename_from_left_selection error: {e}")
        
    def on_power_rename_closed(self):
        """PowerRename窗口关闭时的处理"""
        self.power_rename_window = None  # 清空窗口引用
        self.imagesRenamed.emit()  # 发送信号，通知刷新图片列表
            
    def get_visible_files(self):
        """获取右侧可见的文件列表"""
        visible_files = []
        # 优先基于白名单直接遍历文件系统，避免必须点击展开目录才加载
        included_paths = getattr(self.right_proxy, "included_paths", set())
        excluded_paths = set(getattr(self, "_right_excluded_paths", []))

        def is_excluded(path):
            try:
                norm = os.path.normcase(os.path.normpath(path))
            except Exception:
                norm = path
            for p in excluded_paths:
                if norm == p or norm.startswith(p + os.sep):
                    return True
            return False

        if included_paths:
            # 将代理模型保存的规范化路径还原为实际路径进行遍历
            for p in list(included_paths):
                try:
                    # included_paths 已是规范化过的大小写无关路径，这里尽量获取真实存在的路径
                    path = p
                    if os.path.isfile(path):
                        if not is_excluded(path):
                            visible_files.append(path)
                    elif os.path.isdir(path):
                        for dirpath, dirnames, filenames in os.walk(path):
                            # 应用排除规则到目录层级（剪枝）
                            if is_excluded(dirpath):
                                # 跳过该目录的后代
                                dirnames[:] = []
                                continue
                            for name in filenames:
                                fp = os.path.join(dirpath, name)
                                if not is_excluded(fp) and os.path.isfile(fp):
                                    visible_files.append(fp)
                except Exception:
                    continue
            return visible_files

        # 回退：无白名单时，按当前树可见范围遍历（保持原行为）
        root_index = self.right_tree.rootIndex()
        if not root_index.isValid():
            return visible_files

        def collect_files(proxy_index):
            rows = self.right_proxy.rowCount(proxy_index)
            for i in range(rows):
                child_proxy = self.right_proxy.index(i, 0, proxy_index)
                source_idx = self.right_proxy.mapToSource(child_proxy)
                if self.right_model.isDir(source_idx):
                    collect_files(child_proxy)
                else:
                    file_path = self.right_model.filePath(source_idx)
                    if os.path.isfile(file_path) and not is_excluded(file_path):
                        visible_files.append(file_path)

        collect_files(root_index)
        return visible_files

    def get_actual_cased_basename(self, path):
        """在 Windows 上返回路径末级名称的实际大小写；其他平台直接返回 basename。

        通过枚举父目录，对比不区分大小写名称以获取真实的条目名称。
        """
        try:
            parent_dir = os.path.dirname(path)
            target = os.path.basename(path)
            if not parent_dir or not target:
                return target
            if not os.path.isdir(parent_dir):
                return target
            try:
                for entry in os.listdir(parent_dir):
                    if entry.lower() == target.lower():
                        return entry
            except Exception:
                return target
            return target
        except Exception:
            return os.path.basename(path)

    def show_help(self):
        help_text = (
            "整体的使用方法类似于faststoneview\n"
            "# 是数字\n"
            "* 表示保存原始文件名\n"
            "$p 表示文件夹名\n"
            "$$p 表示两级文件夹名"
        )
        help_dialog = QDialog(self)
        help_dialog.setWindowTitle("帮助")
        layout = QVBoxLayout()
        label = QLabel(help_text, help_dialog)
        layout.addWidget(label)
        help_dialog.setLayout(layout)
        help_dialog.exec_()

    def open_context_menu(self, position):
        menu = QMenu()
        open_folder_action = QAction("在文件资源管理器中打开", self)
        open_folder_action.triggered.connect(self.open_folder_in_explorer)
        menu.addAction(open_folder_action)
        menu.exec_(self.left_tree.viewport().mapToGlobal(position))


    def open_folder_in_explorer(self):
        selected_indexes = self.left_tree.selectedIndexes()
        if selected_indexes:
            index = selected_indexes[0]
            file_path = self.left_model.filePath(index)
            if os.path.isdir(file_path):
                os.startfile(file_path)
            else:
                # 如果不是文件夹，打开文件所在的文件夹
                os.startfile(os.path.dirname(file_path))

    def expand_to_path(self, folder_path):
        """自动展开文件树到指定路径"""
        if not os.path.isdir(folder_path):
            return
            
        # 获取路径的索引
        path_index = self.left_model.index(folder_path)
        if not path_index.isValid():
            return
            
        # 展开路径上的所有父级目录
        current_path = folder_path
        while current_path and current_path != os.path.dirname(current_path):
            parent_index = self.left_model.index(current_path)
            if parent_index.isValid():
                self.left_tree.expand(parent_index)
            current_path = os.path.dirname(current_path)
            
        # 滚动到目标路径
        self.left_tree.scrollTo(path_index, QTreeView.PositionAtCenter)
        # 选中目标路径
        self.left_tree.setCurrentIndex(path_index)

    def set_folder_path(self, folder_path):
        """设置文件夹路径到文件模型"""
        if os.path.isdir(folder_path):
            try:
                print(f"[set_folder_path] set: {folder_path}")
            except Exception:
                pass
            # 不再限制根路径，显示完整的文件系统结构
            # 自动展开到指定路径
            self.expand_to_path(folder_path)
            # 不自动更新右侧，由“增加/增加全部”按钮控制
            
            # 计算指定文件夹内的文件夹数量
            folder_count = 0
            try:
                for item in os.listdir(folder_path):
                    item_path = os.path.join(folder_path, item)
                    if os.path.isdir(item_path):
                        folder_count += 1
            except PermissionError:
                folder_count = "无权限访问"
            
            # 显示当前选中文件夹的信息
            # folder_name = os.path.basename(folder_path) or folder_path
            # self.folder_count_label.setText(f"当前文件夹: {folder_name} (子文件夹: {folder_count})")
            # self.update_file_count()

    def open_powerrename_for_path(self, target_path):
        """将目标路径加入右侧并直接打开 PowerRename 窗口"""
        try:
            if not target_path:
                return
            # 归一化
            target_path = os.path.normpath(target_path)
            # 设置右侧根和白名单
            self._right_excluded_paths = []
            self.right_proxy.clear_excluded()
            self.right_proxy.set_hide_all(False)
            if os.path.isfile(target_path):
                include_set = {target_path}
                root_dir = os.path.dirname(target_path)
            else:
                include_set = {target_path}
                root_dir = target_path
            self.right_proxy.set_included(include_set)
            self.right_tree.setRootIndex(self.right_proxy.mapFromSource(self.right_model.index(root_dir)))
            # 打开 PowerRename
            self.open_power_rename()
        except Exception as e:
            print(f"open_powerrename_for_path error: {e}")

    def _apply_paths_to_right(self, paths):
        """将多个路径应用到右侧视图：设置白名单并定位到共同父目录。"""
        try:
            if not paths:
                return
            norm_paths = [os.path.normpath(p) for p in paths if p]
            include = set()
            for p in norm_paths:
                if os.path.exists(p):
                    include.add(p)
            if not include:
                return
            # 计算共同父目录
            def _common_parent(dir_list):
                parts = [os.path.abspath(d).split(os.sep) for d in dir_list]
                if not parts:
                    return None
                min_len = min(len(x) for x in parts)
                prefix = []
                for i in range(min_len):
                    token = parts[0][i]
                    if all(x[i] == token for x in parts):
                        prefix.append(token)
                    else:
                        break
                return os.sep.join(prefix) if prefix else os.path.dirname(os.path.abspath(dir_list[0]))
            roots = [os.path.dirname(p) if os.path.isfile(p) else p for p in include]
            root_dir = _common_parent(roots) or (roots[0] if roots else "")
            try:
                print(f"[_apply_paths_to_right] include={len(include)}, root={root_dir}")
            except Exception:
                pass
            # 应用到右侧代理
            self._right_excluded_paths = []
            self.right_proxy.clear_excluded()
            self.right_proxy.set_hide_all(False)
            self.right_proxy.set_included(include)
            if root_dir:
                self.right_tree.setRootIndex(self.right_proxy.mapFromSource(self.right_model.index(root_dir)))
            self.right_proxy.invalidate()
        except Exception as e:
            print(f"_apply_paths_to_right error: {e}")

    def _sync_left_tree_to_paths(self, paths):
        """同步左侧文件树定位到传入的路径"""
        try:
            if not paths:
                return
            
            # 计算共同父目录
            def _common_parent(dir_list):
                parts = [os.path.abspath(d).split(os.sep) for d in dir_list]
                if not parts:
                    return None
                min_len = min(len(x) for x in parts)
                prefix = []
                for i in range(min_len):
                    token = parts[0][i]
                    if all(x[i] == token for x in parts):
                        prefix.append(token)
                    else:
                        break
                return os.sep.join(prefix) if prefix else os.path.dirname(os.path.abspath(dir_list[0]))
            
            # 获取所有路径的父目录
            parent_dirs = []
            for path in paths:
                if os.path.isfile(path):
                    parent_dirs.append(os.path.dirname(path))
                elif os.path.isdir(path):
                    parent_dirs.append(path)
            
            if not parent_dirs:
                return
                
            # 计算共同父目录
            common_parent = _common_parent(parent_dirs)
            if not common_parent or not os.path.exists(common_parent):
                return
                
            try:
                print(f"[_sync_left_tree_to_paths] 定位到: {common_parent}")
            except Exception:
                pass
            
            # 展开并定位到共同父目录
            self.expand_to_path(common_parent)
            
            # 如果有多个路径，尝试选中第一个路径
            if len(paths) == 1:
                target_path = paths[0]
                if os.path.exists(target_path):
                    # 定位到具体文件或文件夹
                    target_index = self.left_model.index(target_path)
                    if target_index.isValid():
                        self.left_tree.setCurrentIndex(target_index)
                        self.left_tree.scrollTo(target_index, QTreeView.PositionAtCenter)
            else:
                # 多个路径时，定位到共同父目录
                parent_index = self.left_model.index(common_parent)
                if parent_index.isValid():
                    self.left_tree.setCurrentIndex(parent_index)
                    self.left_tree.scrollTo(parent_index, QTreeView.PositionAtCenter)
                    
        except Exception as e:
            print(f"_sync_left_tree_to_paths error: {e}")

    def on_left_tree_selection_changed(self, selected, deselected):
        """处理左侧文件树选择变化"""
        indexes = selected.indexes()
        if indexes:
            index = indexes[0]
            file_path = self.left_model.filePath(index)
            if os.path.isdir(file_path):
                # 更新文件夹输入框，仅更新统计，不自动添加到右侧
                self.update_folder_count_for_path(file_path)
            else:
                # 如果选择的是文件，仅更新输入框为其父目录
                parent_dir = os.path.dirname(file_path)
                if os.path.isdir(parent_dir):
                    self.update_folder_count_for_path(parent_dir)

    def update_folder_count_for_path(self, folder_path):
        """更新指定路径的文件夹数量统计"""
        if not os.path.isdir(folder_path):
            return
            
        folder_count = 0
        try:
            for item in os.listdir(folder_path):
                item_path = os.path.join(folder_path, item)
                if os.path.isdir(item_path):
                    folder_count += 1
        except PermissionError:
            folder_count = "无权限访问"
        

    def setup_tray_icon(self):
        """初始化系统托盘图标与菜单"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon_path = os.path.join(os.path.dirname(__file__), "icon", "rename.ico")
        tray_icon = QSystemTrayIcon(QIcon(icon_path), self)
        
        # 设置托盘提示信息
        tooltip_text = (
            "Ctrl+M - 打开PowerRename窗口\n"
            "Ctrl+N - 打开主窗口\n"
            "#数字, $p文件夹名, $$p两级文件夹"
        )
        tray_icon.setToolTip(tooltip_text)
        
        menu = QMenu()
        action_show = QAction("显示窗口", self)
        action_exit = QAction("退出", self)
        action_show.triggered.connect(self.restore_from_tray)
        action_exit.triggered.connect(self.exit_app)
        menu.addAction(action_show)
        menu.addSeparator()
        menu.addAction(action_exit)
        tray_icon.setContextMenu(menu)
        tray_icon.activated.connect(self.on_tray_activated)
        tray_icon.show()
        self.tray_icon = tray_icon
        self.tray_menu = menu

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.restore_from_tray()

    def restore_from_tray(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    def exit_app(self):
        try:
            self.unregister_global_hotkey()
        except Exception:
            pass
        QApplication.quit()

    def closeEvent(self, event):
        """关闭时直接最小化到托盘并弹出气泡提示"""
        if self.tray_icon and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
            try:
                if not self._balloon_shown:
                    self.tray_icon.showMessage(
                        "仍在运行",
                        "程序已最小化到系统托盘，双击托盘图标可恢复窗口。",
                        QSystemTrayIcon.Information,
                        3000,
                    )
                    self._balloon_shown = True
            except Exception:
                pass
            return
        # 无托盘环境，按默认关闭
        try:
            self.unregister_global_hotkey()
        except Exception:
            pass
        super().closeEvent(event)

    # ---------------- 全局热键 Ctrl+M 和 Ctrl+N ----------------
    def setup_global_hotkey(self):
        """注册 Windows 全局热键 Ctrl+M 和 Ctrl+N 并安装原生事件过滤器"""
        if os.name != 'nt' or ctypes is None:
            return
        try:
            MOD_CONTROL = 0x0002
            VK_M = 0x4D
            VK_N = 0x4E
            self._HOTKEY_ID_M = 0xBEEF
            self._HOTKEY_ID_N = 0xBEEF + 1

            user32 = ctypes.windll.user32
            hwnd = int(self.winId())
            
            # 注册 Ctrl+M 热键
            if not user32.RegisterHotKey(hwnd, self._HOTKEY_ID_M, MOD_CONTROL, VK_M):
                print("RegisterHotKey Ctrl+M 失败，可能被占用或无权限")
            else:
                print("注册全局热键 Ctrl+M 成功")
                
            # 注册 Ctrl+N 热键
            if not user32.RegisterHotKey(hwnd, self._HOTKEY_ID_N, MOD_CONTROL, VK_N):
                print("RegisterHotKey Ctrl+N 失败，可能被占用或无权限")
            else:
                print("注册全局热键 Ctrl+N 成功")

            class _HotkeyFilter(QAbstractNativeEventFilter):
                def __init__(self, outer):
                    super().__init__()
                    self.outer = outer
                def nativeEventFilter(self, eventType, message):
                    try:
                        if eventType == b'windows_generic_MSG' or eventType == 'windows_generic_MSG':
                            msg = ctypes.wintypes.MSG.from_address(int(message))
                            if msg.message == 0x0312:  # WM_HOTKEY
                                if msg.wParam == self.outer._HOTKEY_ID_M:
                                    # 触发：仅显示 PowerRename，不唤起主窗口
                                    self.outer.open_power_rename_from_explorer_or_fallback()
                                    return True, 0
                                elif msg.wParam == self.outer._HOTKEY_ID_N:
                                    # 触发：将路径传给主窗口并打开主窗口
                                    self.outer.open_main_window_from_explorer_or_fallback()
                                    return True, 0
                    except Exception:
                        pass
                    return False, 0

            self._hotkey_filter = _HotkeyFilter(self)
            QApplication.instance().installNativeEventFilter(self._hotkey_filter)
        except Exception as e:
            print(f"设置全局热键失败: {e}")

    def unregister_global_hotkey(self):
        if os.name != 'nt' or ctypes is None:
            return
        try:
            if hasattr(self, '_HOTKEY_ID_M'):
                ctypes.windll.user32.UnregisterHotKey(int(self.winId()), self._HOTKEY_ID_M)
            if hasattr(self, '_HOTKEY_ID_N'):
                ctypes.windll.user32.UnregisterHotKey(int(self.winId()), self._HOTKEY_ID_N)
        except Exception:
            pass



if __name__ == "__main__":
    app = QApplication(sys.argv)
    apply_stylesheet(app, theme='light_blue.xml', extra={'font_size': 16})
    # 关闭所有窗口时不退出，确保关闭 PowerRename 后程序仍常驻（托盘可用）
    try:
        app.setQuitOnLastWindowClosed(False)
    except Exception:
        pass
    ex = FileOrganizer()
    # 程序启动即驻留托盘，不显示主窗口
    try:
        ex.hide()
    except Exception:
        pass
    sys.exit(app.exec_())
