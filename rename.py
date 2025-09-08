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
)
from PyQt5.QtCore import QSettings, Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence, QIcon
from PyQt5.QtWidgets import QShortcut



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
        self.left_list = QTreeWidget(self)
        self.left_list.setHeaderHidden(True)
        self.left_list.setSelectionMode(
            QTreeWidget.ExtendedSelection
        )  # 支持按住Ctrl或Shift进行多选
        self.left_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.left_list.customContextMenuRequested.connect(self.open_context_menu)
        left_layout.addWidget(self.folder_count_label)
        left_layout.addWidget(self.left_list)

        # 右侧布局
        right_layout = QVBoxLayout()
        self.file_count_label = QLabel("文件总数: 0", self)
        self.right_list = QTreeWidget(self)
        self.right_list.setSelectionMode(
            QTreeWidget.ExtendedSelection
        )  # 支持按住Ctrl或Shift进行多选
        self.right_list.setHeaderHidden(True)
        self.right_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.right_list.customContextMenuRequested.connect(self.open_context_menu_right)
        right_layout.addWidget(
            self.file_count_label
        )  # 将文件总数标签放在右侧布局的顶部
        right_layout.addWidget(self.right_list)

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
            self.populate_left_list(last_folder)

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
                    self.populate_left_list(folder)
                    self.settings.setValue("lastFolder", folder)
                else:
                    # 信息提示框
                    QMessageBox.information(self, "提示", "传入的路径不是有效的文件夹")
            elif isinstance(folder, list):
                self.left_list.clear()
                self.right_list.clear()
                # 选择列表中的首个文件的上上级文件夹添加到左侧列表
                folder_list = os.path.dirname(os.path.dirname(folder[0]))
                if os.path.isdir(folder_list):
                    self.folder_input.setText(folder_list)
                    self.populate_left_list(folder_list)
                else:
                    # 信息提示框
                    QMessageBox.information(self, "提示", "传入的路径不是有效的文件夹")
                # 将列表中的文件添加到右侧列表
                for file in folder:
                    if os.path.isfile(file):
                        file_name = os.path.basename(file)
                        file_item = QTreeWidgetItem(self.right_list, [file_name])
                        file_item.setData(
                            0, Qt.UserRole, file
                        )  # 将文件的完整路径存储在QTreeWidgetItem中
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

    def populate_left_list(self, folder):
        if not os.path.exists(folder):
            print(f"路径不存在: {folder}")
            # 这里可以选择设置一个默认路径或提示用户
            return

        self.left_list.clear()
        self.right_list.clear()
        folder_count = 0
        for subfolder in os.listdir(folder):
            subfolder_path = os.path.join(folder, subfolder)
            if os.path.isdir(subfolder_path):
                folder_item = QTreeWidgetItem(self.left_list, [subfolder])
                has_files = False  # 用于检查文件夹内是否有文件
                for file in os.listdir(subfolder_path):
                    file_path = os.path.join(subfolder_path, file)
                    if os.path.isfile(file_path):
                        file_item = QTreeWidgetItem(folder_item, [file])
                        file_item.setData(
                            0, Qt.UserRole, file_path
                        )  # 将文件的完整路径存储在QTreeWidgetItem中
                        has_files = True
                if has_files:
                    folder_count += 1
            else:
                # 如果是文件而不是文件夹，直接添加到左侧列表
                file_item = QTreeWidgetItem(self.left_list, [subfolder])
                file_item.setData(
                    0, Qt.UserRole, subfolder_path
                )  # 将文件的完整路径存储在QTreeWidgetItem中
                folder_count += 1

        self.folder_count_label.setText(f"文件夹数量: {folder_count}")
        self.update_file_count()

    def add_to_right(self):
        selected_items = self.left_list.selectedItems()
        for item in selected_items:
            # 检查是否为文件夹
            if item.childCount() > 0:
                # 如果选中的是文件夹，添加文件夹及其所有文件
                folder_name = item.text(0)
                folder_path = os.path.join(self.folder_input.text(), folder_name)
                folder_item = QTreeWidgetItem(self.right_list, [folder_name])
                folder_item.setData(0, Qt.UserRole, folder_path)  # 设置文件夹的完整路径
                for i in range(item.childCount()):
                    child = item.child(i)
                    file_name = child.text(0)
                    file_path = child.data(0, Qt.UserRole)
                    file_item = QTreeWidgetItem(folder_item, [file_name])
                    file_item.setData(0, Qt.UserRole, file_path)  # 设置文件的完整路径
            else:
                # 如果是文件，直接添加到右侧列表
                file_path = item.data(0, Qt.UserRole)
                if file_path:  # 确保 file_path 不为 None
                    file_name = os.path.basename(file_path)
                    file_item = QTreeWidgetItem(self.right_list, [file_name])
                    file_item.setData(0, Qt.UserRole, file_path)  # 设置文件的完整路径
        self.update_file_count()

    def add_all_to_right(self):
        self.right_list.clear()
        for i in range(self.left_list.topLevelItemCount()):
            item = self.left_list.topLevelItem(i)
            folder_name = item.text(0)
            folder_path = os.path.join(self.folder_input.text(), folder_name)
            folder_item = QTreeWidgetItem(self.right_list, [folder_name])
            folder_item.setData(0, Qt.UserRole, folder_path)  # 设置文件夹的完整路径
            for j in range(item.childCount()):
                child = item.child(j)
                file_name = child.text(0)
                file_path = child.data(0, Qt.UserRole)
                file_item = QTreeWidgetItem(folder_item, [file_name])
                file_item.setData(0, Qt.UserRole, file_path)  # 设置文件的完整路径
        self.update_file_count()

    def remove_from_right(self):
        selected_items = self.right_list.selectedItems()
        for item in selected_items:
            index = self.right_list.indexOfTopLevelItem(item)
            self.right_list.takeTopLevelItem(index)
        self.update_file_count()

    def remove_all_from_right(self):
        self.right_list.clear()
        self.update_file_count()

    def update_file_count(self):
        file_count = 0
        for i in range(self.right_list.topLevelItemCount()):
            item = self.right_list.topLevelItem(i)
            if item.childCount() > 0:
                file_count += item.childCount()
            else:
                # 如果是单个文件，直接计数
                file_count += 1
        self.file_count_label.setText(f"文件总数: {file_count}")

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
            for i in range(self.right_list.topLevelItemCount()):
                item = self.right_list.topLevelItem(i)
                if item.childCount() > 0:
                    # 处理文件夹
                    folder_name = item.text(0)
                    folder_path = os.path.join(self.folder_input.text(), folder_name)
                    parent_folder_name = os.path.basename(os.path.dirname(folder_path))

                    for j in range(item.childCount()):
                        file_item = item.child(j)
                        original_name = file_item.text(0)
                        original_path = os.path.join(folder_path, original_name)
                        if self.should_rename_file(original_name):
                            new_name = self.generate_new_name(
                                original_name,
                                prefix,
                                replace_text,
                                parent_folder_name,
                                folder_name,
                                j,
                                hash_count,
                            )
                            new_path = os.path.join(folder_path, new_name)
                            self.perform_rename(original_path, new_path)
                else:
                    # 处理单个文件
                    original_name = os.path.basename(item.data(0, Qt.UserRole))
                    folder_path = os.path.dirname(
                        item.data(0, Qt.UserRole)
                    )  # item.data(0, Qt.UserRole)获取文件完整路径
                    parent_folder_name = os.path.basename(os.path.dirname(folder_path))
                    original_path = item.data(0, Qt.UserRole)
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
                        self.perform_rename(original_path, new_path)

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
            self.populate_left_list(current_folder)

    def preview_rename(self):
        rename_data = []
        prefix = self.line_edit.currentText()
        replace_text = (
            self.replace_line_edit.currentText()
            if self.replace_checkbox.isChecked()
            else None
        )

        hash_count = prefix.count("#")

        for i in range(self.right_list.topLevelItemCount()):
            item = self.right_list.topLevelItem(i)
            if item.childCount() > 0:
                folder_name = item.text(0)
                folder_path = os.path.join(self.folder_input.text(), folder_name)
                parent_folder_name = os.path.basename(os.path.dirname(folder_path))

                for j in range(item.childCount()):
                    file_item = item.child(j)
                    original_path = file_item.data(0, Qt.UserRole)
                    if original_path:
                        original_name = os.path.basename(original_path)
                        if self.should_rename_file(original_name):
                            new_name = self.generate_new_name(
                                original_name,
                                prefix,
                                replace_text,
                                parent_folder_name,
                                folder_name,
                                j,
                                hash_count,
                            )
                            rename_data.append((folder_path, original_name, new_name))
                    else:
                        print(f"警告: 文件项 '{file_item.text(0)}' 缺少完整路径数据。")
            else:
                # 处理单个文件
                original_path = item.data(0, Qt.UserRole)
                if original_path:
                    original_name = os.path.basename(original_path)
                    folder_path = os.path.dirname(original_path)
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
                else:
                    print(f"警告: 文件项 '{item.text(0)}' 缺少完整路径数据。")

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
        menu.exec_(self.left_list.viewport().mapToGlobal(position))

    def open_context_menu_right(self, position):
        menu = QMenu()
        open_folder_action = QAction("在文件资源管理器中打开", self)
        open_folder_action.triggered.connect(self.open_folder_in_explorer_right)
        menu.addAction(open_folder_action)
        menu.exec_(self.right_list.viewport().mapToGlobal(position))

    def open_folder_in_explorer(self):
        if selected_items := self.left_list.selectedItems():
            item = selected_items[0]
            folder_name = item.text(0)
            folder_path = os.path.join(self.folder_input.text(), folder_name)
            if os.path.isdir(folder_path):
                os.startfile(folder_path)
            else:
                # 如果不是文件夹，打开文件所在的文件夹
                os.startfile(os.path.dirname(folder_path))

    def open_folder_in_explorer_right(self):
        if selected_items := self.right_list.selectedItems():
            item = selected_items[0]
            folder_name = item.text(0)
            folder_path = os.path.join(self.folder_input.text(), folder_name)
            if os.path.isdir(folder_path):
                os.startfile(folder_path)
            else:
                # 如果不是文件夹，打开文件所在的文件夹
                os.startfile(os.path.dirname(folder_path))

    def on_folder_input_enter(self):
        folder = self.folder_input.text()
        if os.path.isdir(folder):
            self.populate_left_list(folder)
            self.settings.setValue("lastFolder", folder)
        else:
            print("输入的路径不是有效的文件夹")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = FileOrganizer()
    sys.exit(app.exec_())
