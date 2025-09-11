import sys
import os
import tempfile
import re
import datetime
from collections import defaultdict
from pathlib import Path

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *



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
        # 使用Path对象进行路径规范化
        self.included_paths = {str(Path(p).resolve()) for p in (paths or []) if p}
        self.invalidateFilter()

    def clear_included(self):
        self.included_paths.clear()
        self.invalidateFilter()

    def remove_from_included(self, paths):
        if not paths:
            return
        to_remove = {str(Path(p).resolve()) for p in paths if p}
        if self.included_paths & to_remove:
            self.included_paths -= to_remove
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if self.hide_all:
            return False
        
        source_index = self.sourceModel().index(source_row, 0, source_parent)
        if not source_index.isValid():
            return True
            
        try:
            file_path = str(Path(self.sourceModel().filePath(source_index)).resolve())
        except Exception:
            return True
            
        # 检查排除列表
        for excluded in self.excluded_paths:
            if file_path == excluded or file_path.startswith(excluded + os.sep):
                return False
                
        # 检查包含列表
        if self.included_paths:
            for included in self.included_paths:
                if (file_path == included or 
                    included.startswith(file_path + os.sep) or 
                    file_path.startswith(included + os.sep)):
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
        """自然排序键，使用Path对象简化处理"""
        name = Path(path_or_name).name
        parts = re.split(r'(\d+)', name)
        return [int(p) if p.isdigit() else p.lower() for p in parts]

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
        
        self.include_files_checkbox = QCheckBox("包含文件+拓展名")
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
        folder_to_files = defaultdict(list)
        for file_path in sorted(self.file_list, key=self._natural_sort_key):
            if Path(file_path).is_file():
                folder_path = str(Path(file_path).parent)
                folder_to_files[folder_path].append(file_path)
        
        for folder_path, files in folder_to_files.items():
            # 按文件夹内的文件顺序生成序号
            for index, file_path in enumerate(files):
                path_obj = Path(file_path)
                original_name = path_obj.name
                
                # 如果没有查找文本，重命名列为空
                if not search_text:
                    self.preview_data.append((folder_path, original_name, original_name))
                    continue
                
                # 根据"应用于"复选框确定处理范围
                if self.include_files_checkbox.isChecked():
                    # 使用Path对象处理文件名和扩展名
                    name_part = path_obj.stem
                    ext_part = path_obj.suffix
                    new_name_part = self.perform_replace_with_special_chars(
                        name_part, search_text, replace_text, folder_path, index
                    )
                    # 扩展名允许参与查找/替换，但不参与特殊占位符（避免意外改变.及格式）
                    new_ext_part = self.perform_replace(ext_part, search_text, replace_text)
                    new_name = new_name_part + new_ext_part
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
            path_obj = Path(file_path)
            if not path_obj.is_file():
                continue
                
            original_name = path_obj.name
            folder_path = str(path_obj.parent)
            
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
            # 对于首字母大写，我们需要确保每个单词的首字母都大写
            # 而不仅仅是整个字符串的第一个字符
            return text.capitalize()
        elif button == self.title_radio:
            return text.title()
        return text
        
    def perform_replace(self, text, search_text, replace_text):
        """执行替换操作"""
        if not search_text:
            return text
            
        # 首先对替换文本应用格式化
        formatted_replace_text = self.apply_text_format_to_result(replace_text)
        
        try:
            if self.regex_checkbox.isChecked():
                # 使用正则表达式
                flags = 0 if self.case_sensitive_checkbox.isChecked() else re.IGNORECASE
                if self.match_all_checkbox.isChecked():
                    new_text = re.sub(search_text, formatted_replace_text, text, flags=flags)
                else:
                    new_text = re.sub(search_text, formatted_replace_text, text, count=1, flags=flags)
            else:
                # 普通文本替换
                if self.case_sensitive_checkbox.isChecked():
                    if self.match_all_checkbox.isChecked():
                        new_text = text.replace(search_text, formatted_replace_text)
                    else:
                        new_text = text.replace(search_text, formatted_replace_text, 1)
                else:
                    # 不区分大小写 - 使用简单的不区分大小写替换
                    new_text = self.case_insensitive_replace(text, search_text, formatted_replace_text, self.match_all_checkbox.isChecked())
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
                    if self.match_all_checkbox.isChecked():
                        new_text = text.replace(search_text, formatted_replace_text)
                    else:
                        new_text = text.replace(search_text, formatted_replace_text, 1)
                else:
                    # 使用改进的不区分大小写替换
                    new_text = self.case_insensitive_replace(text, search_text, formatted_replace_text, self.match_all_checkbox.isChecked())
            except Exception as e2:
                print(f"回退替换也失败: {e2}")
                return text
        
        return new_text

    def perform_replace_with_special_chars(self, text, search_text, replace_text, folder_path, index):
        """执行带有特殊字符的替换操作"""
        if not search_text:
            return text
            
        # 首先进行普通的查找替换
        new_text = self.perform_replace(text, search_text, replace_text)
        
        # 然后处理替换文本中的特殊字符
        if replace_text:
            # 使用Path对象获取文件夹信息
            folder_path_obj = Path(folder_path)
            folder_name = folder_path_obj.name
            parent_folder_name = folder_path_obj.parent.name
            
            # 获取当前日期
            now = datetime.datetime.now()
            
            # 处理日期格式 - 使用字典简化替换
            date_replacements = {
                "$YYYY": str(now.year),
                "$MM": f"{now.month:02d}",
                "$DD": f"{now.day:02d}",
                "$yyyy": str(now.year),
                "$mm": f"{now.month:02d}",
                "$dd": f"{now.day:02d}"
            }
            
            for old, new in date_replacements.items():
                new_text = new_text.replace(old, new)
            
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
    
    def _should_rename_file(self, old_name, new_name):
        """判断是否需要重命名文件，考虑文件系统的大小写敏感性"""
        if old_name == new_name:
            return False
        
        # 在Windows等不区分大小写的文件系统上，如果只是大小写不同，也需要重命名
        # 但需要特殊处理以避免冲突
        if old_name.lower() == new_name.lower():
            # 只有大小写不同，在不区分大小写的文件系统上仍然需要重命名
            return True
        
        # 检查新文件名是否有效（避免 Windows 保留名称等）
        if self._is_invalid_filename(new_name):
            print(f"无效的文件名: {new_name}")
            return False
        
        return True
    
    def _is_invalid_filename(self, filename):
        """检查文件名是否在 Windows 上无效"""
        if not filename or filename.strip() == "":
            return True
            
        # Windows 保留名称
        reserved_names = {
            'CON', 'PRN', 'AUX', 'NUL',
            'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
            'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
        }
        
        # 获取文件名（不包含扩展名）进行检查
        name_without_ext = Path(filename).stem.upper()
        if name_without_ext in reserved_names:
            return True
            
        # Windows 不允许的字符
        invalid_chars = '<>:"|?*'
        if any(char in filename for char in invalid_chars):
            return True
            
        # 文件名不能以点或空格结尾
        if filename.endswith('.') or filename.endswith(' '):
            return True
            
        # 文件名长度限制（Windows 路径总长度限制为 260 字符）
        if len(filename) > 255:
            return True
            
        return False
    
    def _is_case_sensitive_filesystem(self):
        """检查当前文件系统是否区分大小写"""
        try:
            # 在 Windows 上，文件系统通常不区分大小写
            import platform
            if platform.system().lower() == 'windows':
                return False
            
            # 对于其他系统，可以通过创建测试文件来检查
            # 这里简化处理，假设非 Windows 系统区分大小写
            return True
        except:
            # 默认假设不区分大小写（更安全）
            return False
    
    def _safe_rename_file(self, old_path, new_path, old_name, new_name):
        """安全地重命名文件，处理大小写敏感的情况"""
        if not old_path.exists():
            print(f"原文件不存在: {old_path}")
            return False
        
        # 检查是否只是大小写不同
        if old_name.lower() == new_name.lower() and old_name != new_name:
            # 只有大小写不同，需要使用临时文件名避免冲突
            return self._rename_case_only(old_path, new_path, old_name, new_name)
        
        # 检查目标文件是否已存在（在 Windows 上不区分大小写）
        if new_path.exists():
            # 在 Windows 上，即使大小写不同，如果文件已存在也不能重命名
            if old_path.resolve() != new_path.resolve():
                print(f"目标文件已存在: {new_path}")
                return False
        
        # 普通重命名
        try:
            old_path.rename(new_path)
            return True
        except OSError as e:
            # 处理 Windows 特有的错误
            if "already exists" in str(e).lower() or "cannot create" in str(e).lower():
                print(f"文件已存在或无法创建: {new_path}")
            else:
                print(f"重命名失败: {e}")
            return False
        except Exception as e:
            print(f"重命名失败: {e}")
            return False
    
    def _rename_case_only(self, old_path, new_path, old_name, new_name):
        """处理只有大小写不同的重命名"""
        try:
            # 使用临时文件名避免冲突
            temp_name = f"_temp_rename_{old_name}_{datetime.datetime.now().microsecond}"
            temp_path = old_path.parent / temp_name
            
            # 先重命名到临时文件
            old_path.rename(temp_path)
            
            # 再重命名到目标文件
            temp_path.rename(new_path)
            
            print(f"大小写重命名成功: {old_name} -> {new_name}")
            return True
        except Exception as e:
            print(f"大小写重命名失败: {e}")
            # 尝试恢复原文件名
            try:
                if temp_path.exists():
                    temp_path.rename(old_path)
            except:
                pass
            return False

    def apply_text_format_to_result(self, text):
        """对重命名结果应用文本格式"""
        # 获取当前选中的格式按钮
        selected_button = self.format_button_group.checkedButton()
        if not selected_button:
            return text
            
        return self.format_text(text, selected_button)
        
    def case_insensitive_replace(self, text, search_text, replace_text, replace_all=True):
        """不区分大小写的字符串替换，使用正则表达式优化"""
        if not search_text:
            return text
            
        try:
            flags = re.IGNORECASE
            count = 0 if replace_all else 1
            # 转义特殊字符以避免正则表达式错误
            escaped_search = re.escape(search_text)
            return re.sub(escaped_search, replace_text, text, count=count, flags=flags)
        except Exception as e:
            print(f"不区分大小写替换失败: {e}")
            # 回退到简单的字符串替换
            try:
                if replace_all:
                    # 使用循环进行不区分大小写的全部替换
                    result = text
                    search_lower = search_text.lower()
                    while True:
                        pos = result.lower().find(search_lower)
                        if pos == -1:
                            break
                        result = result[:pos] + replace_text + result[pos + len(search_text):]
                    return result
                else:
                    # 只替换第一个匹配项
                    pos = text.lower().find(search_text.lower())
                    if pos != -1:
                        return text[:pos] + replace_text + text[pos + len(search_text):]
                    return text
            except Exception as e2:
                print(f"回退替换也失败: {e2}")
                return text
        
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
            invalid_files = []
            
            # 过滤出需要重命名的文件，考虑文件系统的大小写敏感性
            files_to_rename = []
            for folder, old_name, new_name in selected_files:
                # 检查新文件名是否有效
                if self._is_invalid_filename(new_name):
                    invalid_files.append(f"{old_name} -> {new_name}: 无效的文件名")
                    continue
                    
                if self._should_rename_file(old_name, new_name):
                    files_to_rename.append((folder, old_name, new_name))
            
            # 如果有无效文件名，先提示用户
            if invalid_files:
                invalid_msg = "\n".join(invalid_files[:10])  # 最多显示10个
                if len(invalid_files) > 10:
                    invalid_msg += f"\n... 还有 {len(invalid_files) - 10} 个无效文件名"
                
                reply = QMessageBox.question(self, "发现无效文件名", 
                    f"发现 {len(invalid_files)} 个无效文件名:\n\n{invalid_msg}\n\n是否继续重命名其他文件？",
                    QMessageBox.Yes | QMessageBox.No)
                
                if reply == QMessageBox.No:
                    return
            
            if not files_to_rename:
                QMessageBox.information(self, "提示", "没有需要重命名的文件")
                return
            
            print(f"开始重命名，共 {len(files_to_rename)} 个文件需要重命名")
            
            # 创建进度对话框
            progress = QProgressDialog("正在重命名文件...", "取消", 0, len(files_to_rename), self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            
            for i, (folder, old_name, new_name) in enumerate(files_to_rename):
                # 更新进度
                progress.setValue(i)
                progress.setLabelText(f"正在重命名: {old_name}")
                
                # 检查用户是否取消
                if progress.wasCanceled():
                    break
                
                old_path = Path(folder) / old_name
                new_path = Path(folder) / new_name
                
                print(f"尝试重命名: {old_path} -> {new_path}")
                
                try:
                    success = self._safe_rename_file(old_path, new_path, old_name, new_name)
                    if success:
                        success_count += 1
                        print(f"重命名成功: {old_name} -> {new_name}")
                    else:
                        failed_files.append(f"{old_name}: 重命名失败")
                except Exception as e:
                    print(f"重命名失败: {e}")
                    failed_files.append(f"{old_name}: {str(e)}")
            
            progress.setValue(len(files_to_rename))
            progress.close()
                    
            # 显示重命名结果
            result_msg = f"重命名完成!\n\n"
            result_msg += f"需要重命名: {len(files_to_rename)} 个文件\n"
            result_msg += f"成功重命名: {success_count} 个文件\n"
            
            if invalid_files:
                result_msg += f"无效文件名: {len(invalid_files)} 个文件\n"
            
            if failed_files:
                result_msg += f"重命名失败: {len(failed_files)} 个文件\n"
                
                # 如果有失败的文件，显示详细信息
                if len(failed_files) <= 5:
                    result_msg += "\n失败详情:\n" + "\n".join(failed_files)
                else:
                    result_msg += f"\n失败详情（前5个）:\n" + "\n".join(failed_files[:5])
                    result_msg += f"\n... 还有 {len(failed_files) - 5} 个失败"
                
                QMessageBox.warning(self, "重命名完成", result_msg)
            else:
                QMessageBox.information(self, "重命名完成", result_msg)
            
            print(f"重命名完成: 需要重命名 {len(files_to_rename)} 个，成功 {success_count} 个，失败 {len(failed_files)} 个")
                
            # 重命名完成后重新获取文件列表并显示
            self.refresh_file_list_after_rename()
            self.update_preview()  # 使用update_preview而不是show_original_files
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"重命名过程中发生错误: {str(e)}")
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
        # 使用Path对象重新扫描文件夹
        folders = {Path(file_path).parent for file_path in self.file_list}
        
        new_file_list = []
        for folder in folders:
            if folder.exists():
                new_file_list.extend([str(p) for p in folder.iterdir() if p.is_file()])
        
        self.file_list = new_file_list
        print(f"重命名后刷新文件列表: {len(self.file_list)} 个文件")
        


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
        self.initUI()

        # 设置图标路径
        icon_path = os.path.join(os.path.dirname(__file__), "icon", "rename.ico")
        self.setWindowIcon(QIcon(icon_path))

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

        # 监听目录加载完成，确保可以在异步加载后滚动定位
        try:
            self._pending_scroll_path = None
            self.left_model.directoryLoaded.connect(self._on_left_dir_loaded)
        except Exception:
            pass
        
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
        # 右侧支持拖放添加文件/文件夹
        try:
            self.right_tree.setAcceptDrops(True)
            self.right_tree.viewport().setAcceptDrops(True)
            self.right_tree.installEventFilter(self)
            self.right_tree.viewport().installEventFilter(self)
        except Exception:
            pass
        # 用于显示空视图的临时目录
        self._empty_dir = None
        # 启动时设置为空目录，避免显示盘符
        try:
            import tempfile as _tmp
            self._empty_dir = _tmp.mkdtemp(prefix="rename_empty_")
            empty_index = self.right_proxy.mapFromSource(self.right_model.index(self._empty_dir))
            self.right_tree.setRootIndex(empty_index)
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

        right_layout.addWidget(self.right_tree)

        # 右侧下方布局（已不再直接显示在右侧，而是移到状态栏）
        right_bottom_layout = QHBoxLayout()

        # 输入框
        self.line_edit = QComboBox(self)
        self.line_edit.setEditable(True)  # 设置 QComboBox 为可编辑状态
        self.line_edit.addItem("$p_*")
        self.line_edit.addItem("$$p_*")
        self.line_edit.addItem("#_*")
        self.line_edit.addItem("$yyyy$mm$dd_*")
        self.line_edit.addItem("$yyyy-$mm-$dd_#=1_*")
        self.line_edit.setFixedWidth(200)  # 设置宽度

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

        # 加载上次打开的文件夹
        if last_folder := self.settings.value("lastFolder", ""):
            self.set_folder_path(last_folder)

        # 添加ESC键退出快捷键
        self.shortcut_esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.shortcut_esc.activated.connect(self.close)
        
        # 添加Ctrl+D快捷键用于清空右侧视图
        self.shortcut_remove_all = QShortcut(QKeySequence("Ctrl+D"), self)
        self.shortcut_remove_all.activated.connect(self.remove_all_from_right)

        self.show()

    def eventFilter(self, obj, event):
        """拦截右侧视图的拖拽事件，支持拖入文件/文件夹。"""
        try:
            # 仅处理右侧树或其视口上的事件
            if obj in (getattr(self, 'right_tree', None), getattr(self.right_tree, 'viewport', lambda: None)()):
                if event.type() in (QEvent.DragEnter, QEvent.DragMove):
                    try:
                        mime = getattr(event, 'mimeData', lambda: None)()
                        if mime and mime.hasUrls():
                            event.acceptProposedAction()
                            return True
                    except Exception as e:
                        print(f"处理拖拽进入事件失败: {e}")
                        return False
                        
                elif event.type() == QEvent.Drop:
                    try:
                        mime = getattr(event, 'mimeData', lambda: None)()
                        if not mime or not mime.hasUrls():
                            return True
                            
                        urls = mime.urls()
                        paths = []
                        
                        for url in urls:
                            try:
                                if url.isLocalFile():
                                    p = url.toLocalFile()
                                    if p and (Path(p).exists()):  # 确保路径存在
                                        paths.append(p)
                            except Exception as e:
                                print(f"处理URL失败: {e}")
                                continue
                        
                        if paths:
                            # 异步处理拖拽的路径，避免阻塞UI
                            QTimer.singleShot(10, lambda: self._set_right_view_with_paths(paths))
                        
                        event.acceptProposedAction()
                        return True
                        
                    except Exception as e:
                        print(f"处理拖拽放下事件失败: {e}")
                        return False
                        
        except Exception as e:
            print(f"事件过滤器失败: {e}")
            
        return super().eventFilter(obj, event)

    def _set_right_view_with_paths(self, paths):
        """将右侧视图设置为显示指定路径（支持文件/文件夹），并建立白名单。"""
        try:
            if not paths:
                return
                
            # 使用Path对象归一化并区分文件与目录
            files = []
            dirs = []
            for p in dict.fromkeys(paths):
                try:
                    path_obj = Path(p)
                    if path_obj.is_file():
                        files.append(str(path_obj))
                    elif path_obj.is_dir():
                        dirs.append(str(path_obj))
                except Exception as e:
                    print(f"处理路径失败 {p}: {e}")
                    continue

            # 计算共同父目录
            def common_parent(dir_list):
                if not dir_list:
                    return None
                try:
                    paths = [Path(d).resolve() for d in dir_list]
                    common_path_str = os.path.commonpath([str(p) for p in paths])
                    return str(Path(common_path_str).resolve())
                except (ValueError, OSError) as e:
                    print(f"计算共同父目录失败: {e}")
                    return str(Path(dir_list[0]).parent) if dir_list else None

            candidate_dirs = list(dirs)
            # 若包含文件，以其父目录参与共同父目录计算
            candidate_dirs.extend([str(Path(f).parent) for f in files])
            target_dir = common_parent(candidate_dirs) if candidate_dirs else None

            if not target_dir or not Path(target_dir).is_dir():
                print(f"无效的目标目录: {target_dir}")
                return

            # 功能2：左侧同步定位到拖拽的文件夹位置（异步执行，避免阻塞）
            QTimer.singleShot(50, lambda: self._safe_expand_to_path(target_dir))

            # 重置右侧过滤状态
            self._right_excluded_paths = []
            self.right_proxy.clear_excluded()
            self.right_proxy.set_hide_all(False)

            # 设置白名单：优先文件，否则目录
            if files:
                self.right_proxy.set_included(set(files))
            elif dirs:
                self.right_proxy.set_included(set(dirs))
            else:
                self.right_proxy.clear_included()

            # 设置右侧根目录
            try:
                root_source_index = self.right_model.index(target_dir)
                if not root_source_index.isValid():
                    print(f"无效的源索引: {target_dir}")
                    return
                    
                proxy_root_index = self.right_proxy.mapFromSource(root_source_index)
                if not proxy_root_index.isValid():
                    print(f"无效的代理索引: {target_dir}")
                    return
                    
                self.right_tree.setRootIndex(proxy_root_index)
                self._empty_dir = None
                
                # 功能1：自动展开文件数量少于50的文件夹（使用路径而不是索引）
                QTimer.singleShot(300, lambda: self._safe_auto_expand_small_folders(target_dir))
                
            except Exception as e:
                print(f"设置右侧根目录失败: {e}")
                
        except Exception as e:
            print(f"设置右侧视图失败: {e}")
    
    def _safe_expand_to_path(self, target_dir):
        """安全地展开到路径"""
        try:
            if target_dir and Path(target_dir).is_dir():
                self.expand_to_path(target_dir)
        except Exception as e:
            print(f"安全展开路径失败: {e}")
    
    def _safe_auto_expand_small_folders(self, target_dir):
        """安全地自动展开小文件夹"""
        try:
            if not target_dir or not Path(target_dir).is_dir():
                return
                
            # 重新获取索引，确保有效性
            root_source_index = self.right_model.index(target_dir)
            if not root_source_index.isValid():
                return
                
            proxy_root_index = self.right_proxy.mapFromSource(root_source_index)
            if not proxy_root_index.isValid():
                return
                
            self._auto_expand_small_folders(proxy_root_index)
            
        except Exception as e:
            print(f"安全自动展开失败: {e}")

    def _auto_expand_small_folders(self, parent_index):
        """自动展开文件数量少于50的文件夹"""
        try:
            if not parent_index.isValid():
                return
                
            # 递归检查并展开小文件夹
            self._expand_folders_recursive(parent_index, max_depth=3)  # 限制递归深度为3层
            
        except Exception as e:
            print(f"自动展开文件夹失败: {e}")
    
    def _expand_folders_recursive(self, parent_index, current_depth=0, max_depth=3):
        """递归展开小文件夹"""
        try:
            if current_depth >= max_depth:
                return
                
            # 检查索引有效性
            if not parent_index.isValid():
                return
                
            row_count = self.right_proxy.rowCount(parent_index)
            if row_count == 0:
                return
            
            # 收集需要处理的文件夹信息，避免在循环中使用lambda闭包
            folders_to_process = []
                
            for row in range(row_count):
                try:
                    child_index = self.right_proxy.index(row, 0, parent_index)
                    if not child_index.isValid():
                        continue
                        
                    source_index = self.right_proxy.mapToSource(child_index)
                    if not source_index.isValid() or not self.right_model.isDir(source_index):
                        continue
                        
                    # 获取文件夹路径并统计文件数量
                    folder_path = self.right_model.filePath(source_index)
                    if not folder_path or not Path(folder_path).is_dir():
                        continue
                        
                    # 统计文件夹中的文件数量（不包括子文件夹）
                    file_count = self._count_files_in_folder(folder_path)
                    
                    if file_count > 0 and file_count < 30:
                        # 立即展开这个文件夹
                        self.right_tree.expand(child_index)
                        print(f"自动展开文件夹: {Path(folder_path).name} (包含 {file_count} 个文件)")
                        
                        # 记录需要递归处理的文件夹路径
                        folders_to_process.append((folder_path, current_depth + 1))
                        
                    elif file_count >= 30:
                        print(f"跳过展开大文件夹: {Path(folder_path).name} (包含 {file_count} 个文件)")
                        
                except Exception as e:
                    print(f"处理单个文件夹时出错: {e}")
                    continue
            
            # 异步递归处理子文件夹，使用路径而不是索引
            if folders_to_process:
                QTimer.singleShot(150, lambda: self._process_folders_batch(folders_to_process, max_depth))
                    
        except Exception as e:
            print(f"递归展开文件夹失败: {e}")
    
    def _process_folders_batch(self, folders_info, max_depth):
        """批量处理文件夹列表"""
        try:
            for folder_path, depth in folders_info:
                if depth >= max_depth:
                    continue
                    
                try:
                    # 重新获取索引，确保有效性
                    source_index = self.right_model.index(folder_path)
                    if not source_index.isValid():
                        continue
                        
                    proxy_index = self.right_proxy.mapFromSource(source_index)
                    if not proxy_index.isValid():
                        continue
                        
                    # 递归处理这个文件夹
                    self._expand_folders_recursive(proxy_index, depth, max_depth)
                    
                except Exception as e:
                    print(f"批量处理文件夹 {folder_path} 失败: {e}")
                    continue
                    
        except Exception as e:
            print(f"批量处理文件夹失败: {e}")
    
    def _count_files_in_folder(self, folder_path):
        """统计文件夹中的文件数量（不包括子文件夹）"""
        try:
            folder = Path(folder_path)
            if not folder.is_dir():
                return 0
                
            file_count = 0
            for item in folder.iterdir():
                if item.is_file():
                    file_count += 1
                    # 如果文件数量已经超过50，提前返回
                    if file_count >= 30:
                        break
                        
            return file_count
            
        except (PermissionError, OSError) as e:
            print(f"无法访问文件夹 {folder_path}: {e}")
            return 0
        except Exception as e:
            print(f"统计文件数量失败 {folder_path}: {e}")
            return 0

    def format_file_size(self, size_bytes):
        """格式化文件大小，使用更简洁的实现"""
        if size_bytes == 0:
            return "0 B"
        
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"

    def format_time(self, timestamp):
        """格式化时间戳，使用datetime模块"""
        return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


    def add_to_right(self):
        """将左侧当前选中内容加入右侧"""
        selected = [idx for idx in self.left_tree.selectedIndexes() if idx.column() == 0]
        if not selected:
            return
            
        # 转为真实路径并使用Path对象处理
        paths = [self.left_model.filePath(idx) for idx in selected]
        normalized_dirs = []
        
        for p in paths:
            path_obj = Path(p)
            if path_obj.is_file():
                normalized_dirs.append(str(path_obj.parent))
            else:
                normalized_dirs.append(str(path_obj))
        
        # 计算共同父目录
        unique_dirs = list(dict.fromkeys(normalized_dirs))
        if len(unique_dirs) == 1:
            target_dir = unique_dirs[0]
        else:
            try:
                target_dir = os.path.commonpath(unique_dirs)
            except ValueError:
                target_dir = unique_dirs[0] if unique_dirs else None
                
        if target_dir and Path(target_dir).is_dir():
            # 清空之前的过滤状态并准备新的过滤
            self._right_excluded_paths = []
            self.right_proxy.clear_excluded()
            self.right_proxy.set_hide_all(False)
            # 根据选择内容设置白名单
            selected_files = [p for p in paths if Path(p).is_file()]
            selected_dirs = [p for p in paths if Path(p).is_dir()]
            
            if selected_files:
                self.right_proxy.set_included(set(selected_files))
            elif selected_dirs:
                self.right_proxy.set_included(set(selected_dirs))
            else:
                self.right_proxy.clear_included()
                
            # 设置右侧根到共同父目录
            try:
                root_source_index = self.right_model.index(target_dir)
                if root_source_index.isValid():
                    proxy_root_index = self.right_proxy.mapFromSource(root_source_index)
                    if proxy_root_index.isValid():
                        self.right_tree.setRootIndex(proxy_root_index)
                        self._empty_dir = None
                        self.right_proxy.invalidate()
                        
                        # 自动展开文件数量少于50的文件夹（使用路径而不是索引）
                        QTimer.singleShot(300, lambda: self._safe_auto_expand_small_folders(target_dir))
                    else:
                        print(f"无效的代理索引: {target_dir}")
                else:
                    print(f"无效的源索引: {target_dir}")
            except Exception as e:
                print(f"设置右侧根目录失败: {e}")


    def remove_from_right(self):
        """移除右侧选中的条目"""
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
                
        # 使用Path对象规范化路径并去重
        self._right_excluded_paths = [str(Path(p).resolve()) for p in dict.fromkeys(excluded)]
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
        """清空右侧视图（重置过滤并置空根索引）"""
        # 清空右侧视图
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
        
        # 在状态栏显示操作反馈
        if hasattr(self, 'status_bar'):
            self.status_bar.showMessage("已清空右侧视图 (Ctrl+D)", 2000)

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
        #     self.replace_line_edit.currentText()
        # #     # if self.replace_checkbox.isChecked()
        # #     # else None
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
            # 获取当前日期
            now = datetime.datetime.now()
            
            # 处理日期格式命令
            new_name = prefix.replace("$YYYY", str(now.year))  # 年，如 2025
            new_name = new_name.replace("$MM", f"{now.month:02d}")  # 月，如 02
            new_name = new_name.replace("$DD", f"{now.day:02d}")  # 日，如 02
            new_name = new_name.replace("$yyyy", str(now.year))  # 年，如 2025
            new_name = new_name.replace("$mm", f"{now.month:02d}")  # 月，如 02
            new_name = new_name.replace("$dd", f"{now.day:02d}")  # 日，如 02
            
            # 处理 # 字符 - 数字序号（支持新的格式）
            # 先处理带等号的格式，如 #=1, ##=1, ###=21
            hash_equals_number_pattern = r'#+=(\d+)'
            matches = re.finditer(hash_equals_number_pattern, new_name)
            
            # 从后往前替换，避免位置偏移问题
            for match in reversed(list(matches)):
                full_match = match.group()
                start_number = int(match.group(1))
                # 计算 # 的数量：总长度 - = 的长度 - 数字的长度
                hash_count_equals = len(full_match) - 1 - len(match.group(1))
                
                # 计算实际数字：index + start_number
                actual_number = index + start_number
                number_format = f"{{:0{hash_count_equals}d}}"
                formatted_number = number_format.format(actual_number)
                
                # 替换匹配的部分
                new_name = new_name[:match.start()] + formatted_number + new_name[match.end():]
            
            # 处理纯 # 字符 - 数字序号（原有功能，不包含等号和数字的）
            if hash_count > 0:
                number_format = f"{{:0{hash_count}d}}"
                new_name = new_name.replace("#" * hash_count, number_format.format(index))

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
        """自然排序键，使用Path对象简化处理"""
        name = Path(path_or_name).name
        parts = re.split(r'(\d+)', name)
        return [int(p) if p.isdigit() else p.lower() for p in parts]

    def preview_rename(self):
        rename_data = []
        prefix = self.line_edit.currentText()
        replace_text = (
            # self.replace_line_edit.currentText()
            # # if self.replace_checkbox.isChecked()
            # # else None
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
            
        # 打开PowerRename窗口
        self.power_rename_window = PowerRenameDialog(visible_files, self)
        self.power_rename_window.setWindowFlags(Qt.Window)
        self.power_rename_window.show()
        
        # 连接窗口关闭信号
        self.power_rename_window.window_closed.connect(self.on_power_rename_closed)
        
    def on_power_rename_closed(self):
        """PowerRename窗口关闭时的处理"""
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
            "# 是数字序号（从0开始）\n"
            "#=1 是数字序号（从1开始）\n"
            "##=1 是两位数字序号（从01开始）\n"
            "###=1 是三位数字序号（从001开始）\n"
            "* 表示保存原始文件名\n"
            "$p 表示文件夹名\n"
            "$$p 表示两级文件夹名\n"
            "$yyyy 或 $YYYY 表示当前年份（如2025）\n"
            "$mm 或 $MM 表示当前月份（如02）\n"
            "$dd 或 $DD 表示当前日期（如02）"
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
        folder_path_obj = Path(folder_path)
        if not folder_path_obj.is_dir():
            return
            
        # 获取路径的索引
        path_index = self.left_model.index(str(folder_path_obj))
        if not path_index.isValid():
            return
            
        # 展开路径上的所有父级目录
        current_path = folder_path_obj
        while current_path and current_path != current_path.parent:
            parent_index = self.left_model.index(str(current_path))
            if parent_index.isValid():
                self.left_tree.expand(parent_index)
            current_path = current_path.parent

        # 记录待滚动路径，并在加载完成后滚动
        try:
            self._request_scroll_to_path(folder_path)
        except Exception:
            pass

        # 立即尝试一次，再用定时器兜底
        try:
            self._try_scroll_to(folder_path)
            QTimer.singleShot(60, lambda: self._try_scroll_to(folder_path))
            QTimer.singleShot(200, lambda: self._try_scroll_to(folder_path))
        except Exception:
            pass

    def _request_scroll_to_path(self, folder_path):
        """注册一个待滚动路径，等待目录加载完成后执行滚动。"""
        try:
            self._pending_scroll_path = os.path.normcase(os.path.normpath(folder_path))
        except Exception:
            self._pending_scroll_path = folder_path

    def _on_left_dir_loaded(self, loaded_path):
        """当 QFileSystemModel 异步加载目录后回调，执行滚动到目标路径。"""
        try:
            if not self._pending_scroll_path:
                return
            try:
                loaded_norm = os.path.normcase(os.path.normpath(loaded_path))
            except Exception:
                loaded_norm = loaded_path
            if self._pending_scroll_path == loaded_norm:
                # 目标目录加载完成，执行滚动
                self._try_scroll_to(self._pending_scroll_path)
                # 清除待滚动
                self._pending_scroll_path = None
        except Exception:
            pass

    def _try_scroll_to(self, path):
        """尝试滚动并选中路径，前提是索引有效。"""
        try:
            # 确保路径是字符串格式
            path_str = str(Path(path))
            idx = self.left_model.index(path_str)
            if not idx.isValid():
                return
            # 确保已展开到该节点
            self.left_tree.expand(idx)
            # 滚动并选中
            self.left_tree.scrollTo(idx, QTreeView.PositionAtCenter)
            self.left_tree.setCurrentIndex(idx)
        except Exception:
            pass

        
    def set_folder_path(self, folder_path):
        """设置文件夹路径到文件模型"""
        if os.path.isdir(folder_path):
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


    def set_folder_list(self, file_list):
        """设置文件/文件夹列表：左侧定位，右侧打开（兼容入口）。"""
        try:
            self.set_paths(file_list)
        except Exception as e:
            print(f"set_folder_list 调用失败: {e}")

    def set_paths(self, paths):
        """接收文件/文件夹路径列表：
        - 左侧：定位并展开到共同父目录；
        - 右侧：以这些路径为白名单并设置根目录，直接进行重命名。
        """
        if not paths:
            return
            
        # 使用Path对象归一化并区分文件/目录
        unique_paths = list(dict.fromkeys(paths))
        files = []
        dirs = []
        
        for p in unique_paths:
            path_obj = Path(p)
            if path_obj.is_file():
                files.append(str(path_obj))
            elif path_obj.is_dir():
                dirs.append(str(path_obj))

        # 计算共同父目录
        candidate_dirs = list(dirs)
        candidate_dirs.extend([str(Path(f).parent) for f in files])
        
        target_dir = None
        if candidate_dirs:
            try:
                target_dir = os.path.commonpath(candidate_dirs)
            except ValueError:
                target_dir = candidate_dirs[0] if candidate_dirs else None

        # 左侧：定位并展开
        if target_dir and Path(target_dir).is_dir():
            try:
                self.expand_to_path(target_dir)
                # 选中共同父目录，便于用户感知当前位置
                idx = self.left_model.index(target_dir)
                if idx.isValid():
                    self.left_tree.setCurrentIndex(idx)
            except Exception:
                pass

        # 右侧：打开并建立白名单
        try:
            self._set_right_view_with_paths(unique_paths)
        except Exception as e:
            print(f"设置右侧视图失败: {e}")

    def on_left_tree_selection_changed(self, selected, deselected):
        """处理左侧文件树选择变化"""
        indexes = selected.indexes()
        if indexes:
            index = indexes[0]
            file_path = Path(self.left_model.filePath(index))
            
            if file_path.is_dir():
                # 更新文件夹输入框，仅更新统计，不自动添加到右侧
                self.update_folder_count_for_path(str(file_path))
            else:
                # 如果选择的是文件，仅更新输入框为其父目录
                parent_dir = file_path.parent
                if parent_dir.is_dir():
                    self.update_folder_count_for_path(str(parent_dir))

    def update_folder_count_for_path(self, folder_path):
        """更新指定路径的文件夹数量统计"""
        folder_path_obj = Path(folder_path)
        if not folder_path_obj.is_dir():
            return
            
        try:
            folder_count = sum(1 for item in folder_path_obj.iterdir() if item.is_dir())
        except PermissionError:
            folder_count = "无权限访问"

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = FileOrganizer()
    sys.exit(app.exec_())
