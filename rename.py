import sys
import os
import tempfile
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
)
from PyQt5.QtCore import QSettings, Qt, pyqtSignal, QDir, QModelIndex
from PyQt5.QtGui import QKeySequence, QIcon
from PyQt5.QtWidgets import QShortcut, QFileSystemModel
from PyQt5.QtCore import QSortFilterProxyModel


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
                # file_path 是 p 的祖先（目录）
                if p.startswith(file_path_norm + os.sep):
                    return True
            return False
        return True



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
        self.folder_input = QLineEdit(self)
        self.import_button = QPushButton("导入", self)
        self.import_button.clicked.connect(self.select_folder)
        folder_layout.addWidget(self.folder_input)
        folder_layout.addWidget(self.import_button)

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
        except Exception:
            self.right_tree.setRootIndex(QModelIndex())
        self.right_tree.setSelectionMode(QTreeView.ExtendedSelection)
        self.right_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.right_tree.customContextMenuRequested.connect(self.open_context_menu_right)
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

        # 右侧下方布局
        right_bottom_layout = QHBoxLayout()
        self.replace_checkbox = QCheckBox("查找替换", self)
        self.replace_checkbox.stateChanged.connect(self.toggle_replace)

        # 输入框
        self.line_edit = QComboBox(self)
        self.line_edit.setEditable(True)  # 设置 QComboBox 为可编辑状态
        self.line_edit.addItem("$p_*")
        self.line_edit.addItem("$$p_*")
        self.line_edit.addItem("#_*")
        self.line_edit.setFixedWidth(self.line_edit.width())  # 设置宽度

        self.replace_line_edit = QComboBox(self)
        self.replace_line_edit.setEditable(True)  # 设置 QComboBox 为可编辑状态
        # 设置输入框提示文本
        self.replace_line_edit.lineEdit().setPlaceholderText("请输入替换内容")

        # 默认隐藏
        self.replace_line_edit.setVisible(False)
        self.replace_line_edit.setFixedWidth(self.replace_line_edit.width())  # 设置宽度

        # 开始按钮
        self.start_button = QPushButton("开始", self)
        self.start_button.clicked.connect(self.rename_files)
        # 预览按钮
        self.preview_button = QPushButton("预览", self)
        self.preview_button.clicked.connect(self.preview_rename)

        # 新增帮助按钮
        self.help_button = QPushButton("帮助", self)
        self.help_button.clicked.connect(self.show_help)

        right_bottom_layout.addWidget(self.replace_checkbox)
        right_bottom_layout.addWidget(self.line_edit)
        right_bottom_layout.addWidget(self.replace_line_edit)

        right_bottom_layout.addWidget(self.start_button)
        right_bottom_layout.addWidget(self.preview_button)
        right_bottom_layout.addWidget(self.help_button)  # 添加帮助按钮

        # 在这里增加可伸缩的空间
        right_bottom_layout.addStretch(0)

        # 添加文件类型复选框
        self.jpg_checkbox = QCheckBox("jpg", self)
        self.txt_checkbox = QCheckBox("txt", self)
        self.xml_checkbox = QCheckBox("xml", self)

        # 默认选中所有复选框
        self.jpg_checkbox.setChecked(True)
        self.txt_checkbox.setChecked(True)
        self.xml_checkbox.setChecked(True)

        # 将复选框添加到布局
        right_bottom_layout.addWidget(self.jpg_checkbox)
        right_bottom_layout.addWidget(self.txt_checkbox)
        right_bottom_layout.addWidget(self.xml_checkbox)

        # 将右侧底部布局添加到右侧布局
        right_layout.addLayout(right_bottom_layout)

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

        # 新建列表布局，添加左侧布局、中间按钮组件布局、右侧布局
        list_layout = QHBoxLayout()
        list_layout.addLayout(left_layout)
        list_layout.addLayout(middle_button_layout)
        list_layout.addLayout(right_layout)

        # 整个界面主体布局设置，添加文件夹选择布局、列表布局，上下分布
        main_layout.addLayout(folder_layout)
        main_layout.addLayout(list_layout)

        self.setLayout(main_layout)
        self.setWindowTitle("重命名")

        # 加载上次打开的文件夹
        if last_folder := self.settings.value("lastFolder", ""):
            self.folder_input.setText(last_folder)
            self.set_folder_path(last_folder)

        self.folder_input.returnPressed.connect(self.on_folder_input_enter)

        # 添加ESC键退出快捷键
        self.shortcut_esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.shortcut_esc.activated.connect(self.close)

        self.show()

    def select_folder(self, folder=None):
        if not folder:
            folder = QFileDialog.getExistingDirectory(self, "选择文件夹")

        if folder:
            if isinstance(folder, str):
                if os.path.isdir(folder):
                    self.folder_input.setText(folder)
                    self.set_folder_path(folder)
                    self.settings.setValue("lastFolder", folder)
                else:
                    # 信息提示框
                    QMessageBox.information(self, "提示", "传入的路径不是有效的文件夹")
            elif isinstance(folder, list):
                # 选择列表中的首个文件的上上级文件夹添加到左侧列表
                folder_list = os.path.dirname(os.path.dirname(folder[0]))
                if os.path.isdir(folder_list):
                    self.folder_input.setText(folder_list)
                    self.set_folder_path(folder_list)
                else:
                    # 信息提示框
                    QMessageBox.information(self, "提示", "传入的路径不是有效的文件夹")
                # 将列表中的文件添加到右侧列表
                for file in folder:
                    if os.path.isfile(file):
                        self.add_file_to_right_tree(file)
                    else:
                        # 信息提示框
                        QMessageBox.information(self, "提示", "传入的文件路径不存在！")
                        break
                # self.update_file_count()
            else:
                # 信息提示框
                QMessageBox.information(
                    self, "提示", "传入的路径不是有效的文件夹字符串或文件完整路径列表"
                )


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
            # 右侧仅显示所选文件（若选择的是文件）
            selected_files = []
            for idx, p in zip(selected, paths):
                if os.path.isfile(p):
                    selected_files.append(p)
            if selected_files:
                self.right_proxy.set_included(set(selected_files))
            else:
                self.right_proxy.clear_included()
            # 最后再设置右侧根到共同父目录（确保过滤状态已生效）
            self.right_tree.setRootIndex(self.right_proxy.mapFromSource(self.right_model.index(target_dir)))
            # 取消空目录根
            self._empty_dir = None
            # 强制刷新与计数
            self.right_proxy.invalidate()
            # self.update_file_count()

    def add_all_to_right(self):
        root_path = self.folder_input.text()
        if os.path.isdir(root_path):
            # 设置右侧模型的根路径为当前选择的文件夹
            self.right_tree.setRootIndex(self.right_proxy.mapFromSource(self.right_model.index(root_path)))
            # 显示整个文件夹（清除仅包含过滤）
            if hasattr(self, 'right_proxy'):
                self.right_proxy.clear_included()
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

    def toggle_replace(self, state):
        self.replace_line_edit.setVisible(state == Qt.Checked)

    def rename_files(self):
        prefix = self.line_edit.currentText()
        replace_text = (
            self.replace_line_edit.currentText()
            if self.replace_checkbox.isChecked()
            else None
        )
        hash_count = prefix.count("#")
        try:
            root_index = self.right_tree.rootIndex()
            if not root_index.isValid():
                QMessageBox.information(self, "提示", "右侧没有可重命名的文件")
                return
            # 构建可见文件列表（通过代理模型遍历）
            visible_files = []
            def collect_files(proxy_index):
                rows = self.right_proxy.rowCount(proxy_index)
                for i in range(rows):
                    child_proxy = self.right_proxy.index(i, 0, proxy_index)
                    source_idx = self.right_proxy.mapToSource(child_proxy)
                    if self.right_model.isDir(source_idx):
                        collect_files(child_proxy)
                    else:
                        visible_files.append(self.right_model.filePath(source_idx))
            collect_files(root_index)
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
                files.sort()
                index_counter = 0
                for file_path in files:
                    original_name = os.path.basename(file_path)
                    parent_folder_name = os.path.basename(os.path.dirname(folder_path))
                    if self.should_rename_file(original_name):
                        new_name = self.generate_new_name(
                            original_name,
                            prefix,
                            replace_text,
                            parent_folder_name,
                            os.path.basename(folder_path),
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
            self.refresh_file_lists()

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

    def refresh_file_lists(self):
        # 重新填充左侧列表
        if current_folder := self.folder_input.text():
            self.set_folder_path(current_folder)

    def preview_rename(self):
        rename_data = []
        prefix = self.line_edit.currentText()
        replace_text = (
            self.replace_line_edit.currentText()
            if self.replace_checkbox.isChecked()
            else None
        )

        hash_count = prefix.count("#")

        root_index = self.right_tree.rootIndex()
        if root_index.isValid():
            # 基于可见文件生成预览
            def collect_preview(proxy_index):
                from collections import defaultdict
                folder_to_files = defaultdict(list)
                rows = self.right_proxy.rowCount(proxy_index)
                for i in range(rows):
                    child_proxy = self.right_proxy.index(i, 0, proxy_index)
                    source_idx = self.right_proxy.mapToSource(child_proxy)
                    if self.right_model.isDir(source_idx):
                        # 合并子目录结果
                        sub_map = collect_preview(child_proxy)
                        for k, v in sub_map.items():
                            folder_to_files[k].extend(v)
                    else:
                        file_path = self.right_model.filePath(source_idx)
                        folder_path = os.path.dirname(file_path)
                        folder_to_files[folder_path].append(file_path)
                return folder_to_files

            folder_to_files = collect_preview(root_index)
            for folder_path, files in folder_to_files.items():
                files.sort()
                local_idx = 0
                for file_path in files:
                    original_name = os.path.basename(file_path)
                    parent_folder_name = os.path.basename(os.path.dirname(folder_path))
                    if self.should_rename_file(original_name):
                        new_name = self.generate_new_name(
                            original_name,
                            prefix,
                            replace_text,
                            parent_folder_name,
                            os.path.basename(folder_path),
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
        # 获取文件的存储的子文件夹名称
        # 这里假设 filename 中不包含路径信息
        # 如果需要，可以调整为接收额外的参数
        if filename.endswith(".jpg") and not self.jpg_checkbox.isChecked():
            return False
        if filename.endswith(".txt") and not self.txt_checkbox.isChecked():
            return False
        if filename.endswith(".xml") and not self.xml_checkbox.isChecked():
            return False
        if filename.endswith(".png") and not self.jpg_checkbox.isChecked():
            return False
        return True

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

    def open_context_menu_right(self, position):
        menu = QMenu()
        open_folder_action = QAction("在文件资源管理器中打开", self)
        open_folder_action.triggered.connect(self.open_folder_in_explorer_right)
        menu.addAction(open_folder_action)
        menu.exec_(self.right_tree.viewport().mapToGlobal(position))

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

    def open_folder_in_explorer_right(self):
        selected_indexes = self.right_tree.selectedIndexes()
        if selected_indexes:
            index = selected_indexes[0]
            file_path = self.right_model.filePath(index)
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

    def on_left_tree_selection_changed(self, selected, deselected):
        """处理左侧文件树选择变化"""
        indexes = selected.indexes()
        if indexes:
            index = indexes[0]
            file_path = self.left_model.filePath(index)
            if os.path.isdir(file_path):
                # 更新文件夹输入框，仅更新统计，不自动添加到右侧
                self.folder_input.setText(file_path)
                self.update_folder_count_for_path(file_path)
            else:
                # 如果选择的是文件，仅更新输入框为其父目录
                parent_dir = os.path.dirname(file_path)
                if os.path.isdir(parent_dir):
                    self.folder_input.setText(parent_dir)
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
        
        # 显示当前选中文件夹的信息
        # folder_name = os.path.basename(folder_path) or folder_path
        # self.folder_count_label.setText(f"当前文件夹: {folder_name} (子文件夹: {folder_count})")

    def on_folder_input_enter(self):
        folder = self.folder_input.text()
        if os.path.isdir(folder):
            self.set_folder_path(folder)
            self.settings.setValue("lastFolder", folder)
        else:
            print("输入的路径不是有效的文件夹")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = FileOrganizer()
    sys.exit(app.exec_())
