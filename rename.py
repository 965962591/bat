import sys
import os
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QMessageBox,
    QTreeWidgetItem,
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
    QListView,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QFrame,
    QTreeView,
)
from PyQt5.QtCore import QSettings, Qt, pyqtSignal, QDir
from PyQt5.QtGui import QKeySequence, QIcon
from PyQt5.QtWidgets import QShortcut, QFileSystemModel



class PreviewDialog(QDialog):
    def __init__(self, rename_data):
        super().__init__()
        self.setWindowTitle("重命名预览")
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
        self.folder_count_label = QLabel("文件夹数量: 0", self)
        
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
        
        left_layout.addWidget(self.folder_count_label)
        left_layout.addWidget(self.left_tree)

        # 右侧布局
        right_layout = QVBoxLayout()
        self.file_count_label = QLabel("文件总数: 0", self)
        
        # 右侧使用QTreeView和QFileSystemModel来显示选中的文件
        self.right_tree = QTreeView(self)
        self.right_model = QFileSystemModel()
        self.right_model.setRootPath("")
        self.right_model.setFilter(QDir.Dirs | QDir.Files | QDir.NoDotAndDotDot)
        self.right_tree.setModel(self.right_model)
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
        
        right_layout.addWidget(self.file_count_label)
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
        self.add_all_button = QPushButton("增加全部", self)
        self.add_all_button.clicked.connect(self.add_all_to_right)
        self.remove_button = QPushButton("移除", self)
        self.remove_button.clicked.connect(self.remove_from_right)

        # 新增"移除全部"按钮
        self.remove_all_button = QPushButton("移除全部", self)
        self.remove_all_button.clicked.connect(self.remove_all_from_right)

        middle_button_layout.addWidget(self.add_button)
        middle_button_layout.addWidget(self.add_all_button)
        middle_button_layout.addWidget(self.remove_button)
        middle_button_layout.addWidget(self.remove_all_button)  # 添加"移除全部"按钮

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
                self.update_file_count()
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
        selected_indexes = self.left_tree.selectedIndexes()
        for index in selected_indexes:
            if index.column() == 0:  # 只处理第一列的选择
                file_path = self.left_model.filePath(index)
                if os.path.isdir(file_path):
                    # 如果是文件夹，设置右侧模型的根路径为该文件夹
                    self.right_tree.setRootIndex(self.right_model.index(file_path))
                elif os.path.isfile(file_path):
                    # 如果是文件，设置右侧模型的根路径为该文件所在的文件夹
                    folder_path = os.path.dirname(file_path)
                    self.right_tree.setRootIndex(self.right_model.index(folder_path))
        self.update_file_count()

    def add_all_to_right(self):
        root_path = self.folder_input.text()
        if os.path.isdir(root_path):
            # 设置右侧模型的根路径为当前选择的文件夹
            self.right_tree.setRootIndex(self.right_model.index(root_path))
        self.update_file_count()

    def remove_from_right(self):
        # 对于文件模型，我们无法直接删除项目，所以清空右侧视图
        self.right_tree.setRootIndex(self.right_model.index(""))
        self.update_file_count()

    def remove_all_from_right(self):
        # 清空右侧视图
        self.right_tree.setRootIndex(self.right_model.index(""))
        self.update_file_count()

    def update_file_count(self):
        file_count = 0
        root_index = self.right_tree.rootIndex()
        if root_index.isValid():
            # 计算右侧视图中的文件数量
            for i in range(self.right_model.rowCount(root_index)):
                child_index = self.right_model.index(i, 0, root_index)
                if self.right_model.isDir(child_index):
                    # 如果是文件夹，递归计算其中的文件数量
                    file_count += self.count_files_in_directory(child_index)
                else:
                    # 如果是文件，直接计数
                    file_count += 1
        self.file_count_label.setText(f"文件总数: {file_count}")
    
    def count_files_in_directory(self, dir_index):
        """递归计算目录中的文件数量"""
        count = 0
        for i in range(self.right_model.rowCount(dir_index)):
            child_index = self.right_model.index(i, 0, dir_index)
            if self.right_model.isDir(child_index):
                count += self.count_files_in_directory(child_index)
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
            if root_index.isValid():
                self.rename_files_recursive(root_index, prefix, replace_text, hash_count)

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
            self.preview_rename_recursive(root_index, prefix, replace_text, hash_count, rename_data)

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
            folder_name = os.path.basename(folder_path) or folder_path
            self.folder_count_label.setText(f"当前文件夹: {folder_name} (子文件夹: {folder_count})")
            self.update_file_count()

    def on_left_tree_selection_changed(self, selected, deselected):
        """处理左侧文件树选择变化"""
        indexes = selected.indexes()
        if indexes:
            index = indexes[0]
            file_path = self.left_model.filePath(index)
            if os.path.isdir(file_path):
                # 更新文件夹输入框
                self.folder_input.setText(file_path)
                # 更新文件夹数量统计
                self.update_folder_count_for_path(file_path)

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
        folder_name = os.path.basename(folder_path) or folder_path
        self.folder_count_label.setText(f"当前文件夹: {folder_name} (子文件夹: {folder_count})")

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
